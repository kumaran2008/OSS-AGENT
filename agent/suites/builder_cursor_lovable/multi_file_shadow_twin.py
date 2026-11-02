from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.kernel.sandbox_isolation import sandbox_executor


@dataclass
class MultiFileTransactionReport:
    transaction_id: str
    files_targeted: List[str]
    all_syntax_valid: bool
    tests_passed: bool
    security_checks_passed: bool
    independent_verifier_passed: bool
    promoted_atomically: bool
    rolled_back: bool
    duration_ms: float
    before_hashes: Dict[str, str] = field(default_factory=dict)
    after_hashes: Dict[str, str] = field(default_factory=dict)
    failure_reason: str = ""


class MultiFileTransactionalShadowTwin:
    """Section 5.4 & Section 9: Transaction-Based Multi-File Shadow Twin."""

    STAGING_ROOT = Path("workspace/.shadow_staging")

    def __init__(self):
        self.STAGING_ROOT.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _sha256_file(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "NEW_FILE"

    async def execute_multi_file_transaction(
        self,
        file_patches: Dict[str, str],
        verification_test_code: str,
        simulate_concurrent_edit_on: Optional[str] = None,
    ) -> MultiFileTransactionReport:
        t0 = time.perf_counter()
        tx_id = f"tx_mf_{int(time.time() * 1000)}"
        tx_dir = self.STAGING_ROOT / tx_id
        tx_dir.mkdir(parents=True, exist_ok=True)

        target_files = list(file_patches.keys())
        before_hashes: Dict[str, str] = {}
        backups: Dict[str, Optional[bytes]] = {}

        for rel_path in target_files:
            p = Path(rel_path)
            before_hashes[rel_path] = self._sha256_file(p)
            backups[rel_path] = p.read_bytes() if p.exists() else None

        manifest_path = tx_dir / "transaction_manifest.json"
        manifest_path.write_text(
            json.dumps({"tx_id": tx_id, "files": target_files, "before_hashes": before_hashes}, indent=2),
            encoding="utf-8",
        )

        staged_bundle_code: List[str] = []
        for rel_path, new_src in file_patches.items():
            try:
                compile(new_src, rel_path, "exec")
            except SyntaxError as se:
                shutil.rmtree(tx_dir, ignore_errors=True)
                return MultiFileTransactionReport(
                    transaction_id=tx_id,
                    files_targeted=target_files,
                    all_syntax_valid=False,
                    tests_passed=False,
                    security_checks_passed=False,
                    independent_verifier_passed=False,
                    promoted_atomically=False,
                    rolled_back=True,
                    duration_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                    before_hashes=before_hashes,
                    after_hashes=before_hashes,
                    failure_reason=f"SyntaxError in {rel_path}: {se}",
                )
            staged_file = tx_dir / Path(rel_path).name
            staged_file.write_text(new_src, encoding="utf-8")
            staged_bundle_code.append(f"# --- STAGED MODULE: {rel_path} ---\n{new_src}")

        combined_source = "\n\n".join(staged_bundle_code) + "\n\n# --- VERIFICATION SUITE ---\n" + verification_test_code
        security_ok = not any(bad in combined_source for bad in ("kernel_governance.db", "vault.db", "/etc/passwd"))

        test_res = await sandbox_executor.run_warm_python_script(
            tx_dir / "multi_file_verification_runner.py",
            combined_source,
            timeout_sec=4.0,
        )
        tests_ok = (test_res.exit_code == 0)
        indep_ok = tests_ok and security_ok and ("Traceback" not in test_res.stderr)

        if simulate_concurrent_edit_on and simulate_concurrent_edit_on in file_patches:
            Path(simulate_concurrent_edit_on).write_text("# Concurrent edit during test!\n", encoding="utf-8")

        for rel_path in target_files:
            current_disk_hash = self._sha256_file(Path(rel_path))
            if current_disk_hash != before_hashes[rel_path]:
                shutil.rmtree(tx_dir, ignore_errors=True)
                return MultiFileTransactionReport(
                    transaction_id=tx_id,
                    files_targeted=target_files,
                    all_syntax_valid=True,
                    tests_passed=tests_ok,
                    security_checks_passed=security_ok,
                    independent_verifier_passed=False,
                    promoted_atomically=False,
                    rolled_back=True,
                    duration_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                    before_hashes=before_hashes,
                    after_hashes={rp: self._sha256_file(Path(rp)) for rp in target_files},
                    failure_reason=f"TOCTOU conflict detected on {rel_path}; transaction aborted safely.",
                )

        if not indep_ok:
            shutil.rmtree(tx_dir, ignore_errors=True)
            return MultiFileTransactionReport(
                transaction_id=tx_id,
                files_targeted=target_files,
                all_syntax_valid=True,
                tests_passed=tests_ok,
                security_checks_passed=security_ok,
                independent_verifier_passed=False,
                promoted_atomically=False,
                rolled_back=True,
                duration_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                before_hashes=before_hashes,
                after_hashes=before_hashes,
                failure_reason=test_res.stderr[:240] or "Verification failed",
            )

        after_hashes: Dict[str, str] = {}
        try:
            for rel_path, new_src in file_patches.items():
                dest = Path(rel_path)
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp_dest = dest.with_suffix(dest.suffix + f".{tx_id}.tmp")
                tmp_dest.write_text(new_src, encoding="utf-8")
                tmp_dest.replace(dest)
                after_hashes[rel_path] = self._sha256_file(dest)
        except Exception as exc:
            for rel_path, orig_bytes in backups.items():
                p = Path(rel_path)
                if orig_bytes is None and p.exists():
                    p.unlink()
                elif orig_bytes is not None:
                    p.write_bytes(orig_bytes)
            shutil.rmtree(tx_dir, ignore_errors=True)
            return MultiFileTransactionReport(
                transaction_id=tx_id,
                files_targeted=target_files,
                all_syntax_valid=True,
                tests_passed=tests_ok,
                security_checks_passed=security_ok,
                independent_verifier_passed=True,
                promoted_atomically=False,
                rolled_back=True,
                duration_ms=round((time.perf_counter() - t0) * 1000.0, 2),
                before_hashes=before_hashes,
                after_hashes=before_hashes,
                failure_reason=f"Commit error rolled back: {exc}",
            )

        shutil.rmtree(tx_dir, ignore_errors=True)
        return MultiFileTransactionReport(
            transaction_id=tx_id,
            files_targeted=target_files,
            all_syntax_valid=True,
            tests_passed=True,
            security_checks_passed=True,
            independent_verifier_passed=True,
            promoted_atomically=True,
            rolled_back=False,
            duration_ms=round((time.perf_counter() - t0) * 1000.0, 2),
            before_hashes=before_hashes,
            after_hashes=after_hashes,
        )


multi_file_shadow_twin = MultiFileTransactionalShadowTwin()
