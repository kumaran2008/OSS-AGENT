from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class QuarantineAuditResult:
    file_name: str
    safe_to_ingest: bool
    detected_mime: str
    javascript_or_launch_actions_stripped: int
    prompt_injection_attempts_isolated: int
    taint_tag: str
    sha256_hash: str
    sanitized_text_preview: str = ""
    rejection_reason: str = ""


class ResearchQuarantineGate:
    """Section 6.6: 6-Stage Research Safety & Quarantine Pipeline.
    Stage 1: Quarantine file isolation
    Stage 2: Executable magic-byte & extension block (PE/MZ, ELF, Mach-O, Shebang, scripts)
    Stage 3: Extension-to-header consistency check
    Stage 4: Active payload sanitization (PDF /JS, /Launch, /EmbeddedFiles stripping)
    Stage 5: Prompt-injection isolation (treats document text strictly as UNTRUSTED_EXTERNAL data)
    Stage 6: Safe data access descriptor
    """

    QUARANTINE_DIR = Path("workspace/.quarantine")
    BLOCKED_EXTENSIONS = {
        ".exe", ".dll", ".so", ".dylib", ".bin", ".sh", ".bat", ".cmd",
        ".scr", ".msi", ".apk", ".com", ".vbs", ".ps1",
    }
    EXECUTABLE_MAGIC_HEADERS = (
        (b"MZ", "application/x-dosexec-pe"),
        (b"\x7fELF", "application/x-elf-executable"),
        (b"\xfe\xed\xfa\xcf", "application/x-mach-binary"),
        (b"\xca\xfe\xba\xbe", "application/x-mach-universal"),
        (b"#!", "application/x-shellscript"),
    )
    INJECTION_PATTERNS = (
        r"ignore\s+(?:all\s+)?previous\s+instructions",
        r"execute\s+this\s+command",
        r"system\s+override",
        r"rm\s+-rf",
        r"curl\s+http",
    )

    def __init__(self):
        self.QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)

    def quarantine_and_inspect_file(self, file_name: str, raw_bytes: bytes) -> QuarantineAuditResult:
        sha256 = hashlib.sha256(raw_bytes).hexdigest()
        safe_name = Path(file_name).name
        ext = Path(safe_name).suffix.lower()
        dest = self.QUARANTINE_DIR / f"{sha256[:10]}_{safe_name}"
        dest.write_bytes(raw_bytes)

        # Stage 2A: Check blocked executable extensions first
        if ext in self.BLOCKED_EXTENSIONS:
            return QuarantineAuditResult(
                file_name=safe_name,
                safe_to_ingest=False,
                detected_mime="application/x-blocked-executable-extension",
                javascript_or_launch_actions_stripped=0,
                prompt_injection_attempts_isolated=0,
                taint_tag="REJECTED_EXECUTABLE_EXTENSION",
                sha256_hash=sha256,
                rejection_reason=f"Blocked executable or script file extension '{ext}'.",
            )

        # Stage 2B: Check binary executable magic headers before any text decoding
        for magic_sig, mime_name in self.EXECUTABLE_MAGIC_HEADERS:
            if raw_bytes.startswith(magic_sig):
                return QuarantineAuditResult(
                    file_name=safe_name,
                    safe_to_ingest=False,
                    detected_mime=mime_name,
                    javascript_or_launch_actions_stripped=0,
                    prompt_injection_attempts_isolated=0,
                    taint_tag="REJECTED_EXECUTABLE_MAGIC_BYTES",
                    sha256_hash=sha256,
                    rejection_reason=f"File starts with executable magic header ({mime_name}).",
                )

        # Stage 3: Check document format & extension consistency
        is_pdf = raw_bytes.startswith(b"%PDF-")
        if ext == ".pdf" and not is_pdf:
            return QuarantineAuditResult(
                file_name=safe_name,
                safe_to_ingest=False,
                detected_mime="application/octet-stream",
                javascript_or_launch_actions_stripped=0,
                prompt_injection_attempts_isolated=0,
                taint_tag="REJECTED_HEADER_MISMATCH",
                sha256_hash=sha256,
                rejection_reason="File has .pdf extension but lacks valid %PDF- magic header.",
            )

        is_text = False
        decoded_text = ""
        if not is_pdf:
            try:
                decoded_text = raw_bytes.decode("utf-8")
                # Reject binary streams with null bytes
                if "\x00" not in decoded_text:
                    is_text = True
            except Exception:
                is_text = False

        if not is_pdf and not is_text and not raw_bytes.startswith((b"\x89PNG", b"\xff\xd8\xff")):
            return QuarantineAuditResult(
                file_name=safe_name,
                safe_to_ingest=False,
                detected_mime="application/x-unknown-binary",
                javascript_or_launch_actions_stripped=0,
                prompt_injection_attempts_isolated=0,
                taint_tag="REJECTED_UNSAFE_MAGIC_BYTES",
                sha256_hash=sha256,
                rejection_reason="File magic bytes do not match permitted document or UTF-8 text formats.",
            )

        # Stage 4: Active PDF object sanitization
        js_count = 0
        if is_pdf:
            active_pdf_pattern = rb"/(?:JS|JavaScript|Launch|EmbeddedFiles|OpenAction|AA)\b"
            js_count = len(re.findall(active_pdf_pattern, raw_bytes, flags=re.IGNORECASE))
            sanitized_bytes = re.sub(active_pdf_pattern, b"/RemovedUnsafeObject", raw_bytes, flags=re.IGNORECASE)
            dest.write_bytes(sanitized_bytes)
            decoded_text = sanitized_bytes.decode("latin-1", errors="ignore")
            mime = "application/pdf"
        else:
            mime = "text/plain"

        # Stage 5: Prompt-injection detection & data-only isolation
        inj_hits = 0
        sanitized_text = decoded_text
        for pat in self.INJECTION_PATTERNS:
            matches = re.findall(pat, sanitized_text, flags=re.IGNORECASE)
            inj_hits += len(matches)
            sanitized_text = re.sub(
                pat,
                "[ISOLATED_UNTRUSTED_DOCUMENT_STRING]",
                sanitized_text,
                flags=re.IGNORECASE,
            )

        return QuarantineAuditResult(
            file_name=safe_name,
            safe_to_ingest=True,
            detected_mime=mime,
            javascript_or_launch_actions_stripped=js_count,
            prompt_injection_attempts_isolated=inj_hits,
            taint_tag="UNTRUSTED_EXTERNAL",
            sha256_hash=sha256,
            sanitized_text_preview=sanitized_text[:240],
        )


quarantine_gate = ResearchQuarantineGate()
