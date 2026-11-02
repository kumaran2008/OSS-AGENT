from pathlib import Path

target = Path("agent/pa_scaffolder/literature_engine.py")
code = target.read_text(encoding="utf-8")

old_native = """    @staticmethod
    def _native_pdf_stream_extractor(pdf_path: Path) -> str:
        \"\"\"Pure-Python standard-library extractor for deflated PDF text streams.\"\"\"
        raw_bytes = pdf_path.read_bytes()
        extracted_chunks: List[str] = []

        # Find all FlateDecode streams
        stream_matches = re.finditer(b"stream[\\r\\n]+(.*?)[\\r\\n]+endstream", raw_bytes, re.DOTALL)
        for m in stream_matches:
            stream_data = m.group(1)
            try:
                decomp = zlib.decompress(stream_data)
                # Extract text within parentheses: (text) Tj or [(text)] TJ
                text_tokens = re.findall(rb"\\((.*?)\\)\\s*(?:Tj|'|\\")", decomp)
                if not text_tokens:
                    text_tokens = re.findall(rb"\\[(.*?)\\]\\s*TJ", decomp)

                for tok in text_tokens:
                    decoded = tok.decode("utf-8", errors="replace")
                    if len(decoded.strip()) > 1 and not re.match(r"^[\\x00-\\x1f]+$", decoded):
                        extracted_chunks.append(decoded.strip())
            except Exception:
                continue

        if extracted_chunks:
            return " ".join(extracted_chunks)

        # Fallback to ASCII string scanner
        ascii_matches = re.findall(rb"[A-Za-z0-9\\s\\.,;:!\\?\\-\\(\\)\\[\\]\\{\\}\\=\\+\\/\\*\\<\\>\\|\\$\\@\\%]{5,}", raw_bytes)
        decoded_text = "\\n".join(b.decode("utf-8", errors="replace") for b in ascii_matches[:300])
        return decoded_text if decoded_text.strip() else "# Empty or Unparseable PDF Binary\""""

new_native = """    @staticmethod
    def _native_pdf_stream_extractor(pdf_path: Path) -> str:
        \"\"\"Pure-Python standard-library extractor for deflated PDF text streams.\"\"\"
        raw_bytes = pdf_path.read_bytes()
        extracted_chunks: List[str] = []

        # Find all FlateDecode streams
        stream_matches = re.finditer(b"stream[\\r\\n]+(.*?)[\\r\\n]+endstream", raw_bytes, re.DOTALL)
        for m in stream_matches:
            stream_data = m.group(1)
            decomp = None
            try:
                decomp = zlib.decompress(stream_data)
            except Exception:
                try:
                    decomp = zlib.decompress(stream_data.strip())
                except Exception:
                    decomp = stream_data

            if decomp:
                try:
                    # 1. Try extracting text from standard PDF drawing operators: (text) Tj
                    tokens: List[str] = []
                    for t in re.findall(rb"\\((.*?)\\)\\s*(?:Tj|'|\\")", decomp):
                        tokens.append(t.decode("utf-8", errors="replace"))

                    for arr in re.findall(rb"\\[(.*?)\\]\\s*TJ", decomp):
                        for sub in re.findall(rb"\\((.*?)\\)", arr):
                            tokens.append(sub.decode("utf-8", errors="replace"))

                    if tokens:
                        text_blob = " ".join(t.strip() for t in tokens if len(t.strip()) > 0)
                        if text_blob.strip():
                            extracted_chunks.append(text_blob)
                    else:
                        # 2. Decompressed stream is markdown, layout text, or structural blocks
                        decoded = decomp.decode("utf-8", errors="replace")
                        lines = [line.strip() for line in decoded.splitlines()]
                        if any(any(c.isalnum() for c in l) for l in lines):
                            extracted_chunks.append("\\n".join(lines))
                except Exception:
                    continue

        if extracted_chunks:
            return "\\n\\n".join(extracted_chunks)

        # Fallback to ASCII string scanner
        ascii_matches = re.findall(rb"[A-Za-z0-9\\s\\.,;:!\\?\\-\\(\\)\\[\\]\\{\\}\\=\\+\\/\\*\\<\\>\\|\\$\\@\\%]{5,}", raw_bytes)
        decoded_text = "\\n".join(b.decode("utf-8", errors="replace") for b in ascii_matches[:300])
        return decoded_text if decoded_text.strip() else "# Empty or Unparseable PDF Binary\""""

if old_native in code:
    code = code.replace(old_native, new_native)
else:
    # Direct regex fallback replacement
    import re
    code = re.sub(r'def _native_pdf_stream_extractor\(pdf_path: Path\) -> str:.*?(?=\n    # -+\n    # Layout-Aware)', new_native.strip(), code, flags=re.DOTALL)

# Also ensure title extraction in ingest_full_paper_pdf handles preambles
old_title_logic = "paper_title = title or (sections[0].heading if sections else pdf_file.stem)"
new_title_logic = """paper_title = title
        if not paper_title:
            if sections and sections[0].heading == "Preamble" and sections[0].content_md:
                paper_title = sections[0].content_md.splitlines()[0][:120].strip()
            elif sections and sections[0].heading.lower() != "abstract":
                paper_title = sections[0].heading
            else:
                paper_title = pdf_file.stem"""

if old_title_logic in code:
    code = code.replace(old_title_logic, new_title_logic)

target.write_text(code, encoding="utf-8")
print("[✓] Patched _native_pdf_stream_extractor and ingest_full_paper_pdf in literature_engine.py.")
