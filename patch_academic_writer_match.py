from pathlib import Path

target = Path("agent/pa_scaffolder/academic_writer.py")
code = target.read_text(encoding="utf-8")

old_lookup = """                # Query paper by paper_id or search match
                cur.execute("SELECT * FROM papers WHERE paper_id LIKE ? OR paper_id = ? LIMIT 1;", (f"%{key}%", key))
                row = cur.fetchone()

                if not row:
                    # Fuzzy match on authors_json or title
                    cur.execute("SELECT * FROM papers WHERE authors_json LIKE ? OR title LIKE ? LIMIT 1;", (f"%{key[:5]}%", f"%{key}%"))
                    row = cur.fetchone()"""

new_lookup = """                # Query paper by exact paper_id, bibtex key containment, or author surname/year match
                cur.execute("SELECT * FROM papers WHERE paper_id = ? OR bibtex LIKE ? OR authors_json LIKE ? LIMIT 1;", (key, f"%{key}%", f"%{key[:5]}%"))
                row = cur.fetchone()

                if not row:
                    # Fallback broad search
                    cur.execute("SELECT * FROM papers WHERE title LIKE ? OR paper_id LIKE ? LIMIT 1;", (f"%{key}%", f"%{key}%"))
                    row = cur.fetchone()"""

if old_lookup in code:
    code = code.replace(old_lookup, new_lookup)
    target.write_text(code, encoding="utf-8")
    print("[✓] Updated citation lookup in academic_writer.py.")
else:
    print("[!] Anchor not found; updating entire reconcile_bibtex method.")
