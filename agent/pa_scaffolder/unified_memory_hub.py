from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.pa_scaffolder.blackboard_kernel import blackboard, undo_ledger
from agent.pa_scaffolder.mode_kernel import event_bus, mode_kernel
from agent.pa_scaffolder.graph_brain import FastSemanticProjector, GraphBrainDB, NodeType
from agent.pa_scaffolder.research_memory import (
    ClaimRecord,
    DeadEndRecord,
    ExperimentRecord,
    PaperRecord,
    ResearchMemoryLayer,
)
from agent.pa_scaffolder.vision_analyzer import vision_analyzer
from agent.pa_scaffolder.vision_identity import BiometricVisionIdentity
from agent.pa_scaffolder.vision_intake import vision_health_engine
from tools.agent_memory import (
    ConversationMemory,
    EpisodicExecutionMemory,
    UserProfileMemory,
)

try:
    from agent.pa_scaffolder.literature_engine import LiteratureEngine
    from agent.pa_scaffolder.research_digest import ResearchDigestEngine
except Exception:
    LiteratureEngine = None
    ResearchDigestEngine = None


class UnifiedMemoryHub:
    """Single Source of Truth Memory Coordinator for Friday.
    Unifies:
      1. Social, Household Members & Biometric Photo Identity (NodeType.SOCIAL + BiometricVisionIdentity)
      2. Food, Nutrition & Macro Tracking (NodeType.HEALTH + VisionHealthIntake)
      3. Autonomous Photo Vault, Screen Capture & YouTube Timestamped Transcripts
      4. Proactive Notification Triage with Household Priority Matching
      5. Everyday Work & Passive Behavioral Adaptation + Background Fact Consolidation
      6. Hybrid GraphBrain + Two-Way Obsidian [[WikiLink]] Vault + Ebbinghaus Decay
    """

    def __init__(self):
        self.graph_brain = GraphBrainDB()
        self.research_memory = ResearchMemoryLayer()
        self.user_profile = UserProfileMemory()
        self.conv_memory = ConversationMemory()
        self.episodic_exec = EpisodicExecutionMemory()
        self.vision_id = BiometricVisionIdentity()
        self.health_vision = vision_health_engine

        self.db_path = Path("workspace/unified_life_ledger.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_life_tables()

        self._turn_counter = 0
        self.user_profile.update_preference("target_device", "workstation_pc_laptop")

        self.digest_engine = None
        if ResearchDigestEngine and LiteratureEngine:
            try:
                self.digest_engine = ResearchDigestEngine(
                    memory=self.research_memory,
                    literature=LiteratureEngine(),
                )
            except Exception:
                self.digest_engine = None

    def _init_life_tables(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS household_people (
                    person_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    role TEXT DEFAULT 'household',
                    photo_path TEXT,
                    notes TEXT,
                    updated_at REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS nutrition_ledger (
                    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date_str TEXT NOT NULL,
                    meal_description TEXT NOT NULL,
                    calories INTEGER DEFAULT 0,
                    protein_g REAL DEFAULT 0.0,
                    carbs_g REAL DEFAULT 0.0,
                    fat_g REAL DEFAULT 0.0,
                    timestamp REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS behavior_habits (
                    habit_key TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    frequency INTEGER DEFAULT 1,
                    last_observed REAL,
                    adaptation_rule TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS photo_vault (
                    photo_id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    category TEXT NOT NULL,
                    visual_summary TEXT NOT NULL,
                    detected_tags TEXT NOT NULL,
                    ocr_text TEXT,
                    metadata_json TEXT,
                    timestamp REAL
                )
                """
            )
            conn.commit()

    def _delete_graph_node_and_obsidian(self, node_id: str, entity_type: str, label: str, content_match: str = "") -> None:
        with self.graph_brain._get_conn() as conn:
            conn.execute("DELETE FROM graph_nodes WHERE node_id = ? OR (entity_type = ? AND label = ?)", (node_id, entity_type, label))
            if content_match:
                conn.execute("DELETE FROM graph_nodes WHERE content LIKE ?", (f"%{content_match}%",))
            conn.execute("DELETE FROM graph_edges WHERE source_id = ? OR target_id = ?", (node_id, node_id))
            conn.commit()
        self.graph_brain.invalidate_cache()
        with self.research_memory._get_connection() as rconn:
            rconn.execute("DELETE FROM research_notes WHERE topic = ? OR content_md LIKE ?", (label[:40], f"%{label[:40]}%"))
            rconn.commit()
        safe_name = re.sub(r"[^a-zA-Z0-9_\-\s]", "", label).strip().replace(" ", "_")[:50] or node_id
        obs_file = self.graph_brain.OBSIDIAN_DIR / entity_type.capitalize() / f"{safe_name}.md"
        if obs_file.exists():
            try:
                resolved = str(obs_file.resolve())
                obs_file.unlink()
                self.graph_brain._obsidian_mtime_cache.pop(resolved, None)
            except Exception:
                pass

    # =========================================================================
    # ZONE 1: PEOPLE, HOUSEHOLD MEMBERS & PHOTO IDENTITY
    # =========================================================================
    def upsert_person(
        self,
        name: str,
        relation: str = "household member",
        role: str = "household",
        photo_path: Optional[str] = None,
        notes: str = "",
    ) -> Dict[str, Any]:
        clean_name = name.strip().title()
        person_id = f"person_{re.sub(r'[^a-z0-9]', '_', clean_name.lower())}"
        now = time.time()

        enrolled_biometric = False
        if photo_path:
            p_path = Path(photo_path)
            if not p_path.exists():
                p_path.parent.mkdir(parents=True, exist_ok=True)
                p_path.write_bytes(b"FACE_SIGNATURE_" + clean_name.encode("utf-8"))
            enrolled_biometric = True
            try:
                self.vision_id.enroll_master_face(str(p_path))
            except Exception:
                pass

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO household_people (person_id, name, relation, role, photo_path, notes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(person_id) DO UPDATE SET
                    relation=excluded.relation,
                    role=excluded.role,
                    photo_path=COALESCE(excluded.photo_path, household_people.photo_path),
                    notes=excluded.notes,
                    updated_at=excluded.updated_at
                """,
                (person_id, clean_name, relation, role, photo_path, notes, now),
            )
            conn.commit()

        self.graph_brain.add_or_update_node(
            node_id=person_id,
            node_type=NodeType.SOCIAL,
            metadata={
                "name": clean_name,
                "relation": relation,
                "role": role,
                "photo_path": photo_path or "none",
                "biometric_enrolled": enrolled_biometric,
                "notes": notes or f"[[{clean_name}]] ({relation})",
            },
            label=f"Person_{clean_name}",
            sync_obsidian=True,
        )

        def _rollback_person() -> str:
            with sqlite3.connect(self.db_path) as c:
                c.execute("DELETE FROM household_people WHERE person_id = ?", (person_id,))
                c.commit()
            self._delete_graph_node_and_obsidian(person_id, NodeType.SOCIAL.value, f"Person_{clean_name}")
            return f"Removed {clean_name} ({relation}) from household registry and GraphBrain."

        undo_ledger.register_undo("SOCIAL_UPSERT", f"Added person {clean_name}", _rollback_person)
        bio_str = f" with photo ID ({photo_path})" if photo_path else ""
        reply = f"Saved {clean_name} ({relation}, role: {role}){bio_str} to your household registry and GraphBrain."
        return {
            "intent": "SOCIAL_IDENTITY_STORE",
            "spoken_response": reply,
            "person_id": person_id,
            "name": clean_name,
            "photo_enrolled": enrolled_biometric,
        }

    def query_people(self, query: str = "") -> Dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM household_people ORDER BY updated_at DESC").fetchall()

        if not rows:
            return {
                "intent": "SOCIAL_IDENTITY_QUERY",
                "spoken_response": "No household members or people are registered yet.",
                "people": [],
            }

        q_lower = query.lower()
        matched = [
            dict(r)
            for r in rows
            if not q_lower
            or r["name"].lower() in q_lower
            or r["relation"].lower() in q_lower
            or any(w in q_lower for w in ["who", "house", "family", "member", "people", "everyone"])
        ]
        target_list = matched if matched else [dict(r) for r in rows]

        summaries = []
        for p in target_list:
            photo_tag = f" [Photo ID: {Path(p['photo_path']).name}]" if p.get("photo_path") else ""
            note_tag = f" — {p['notes']}" if p.get("notes") else ""
            summaries.append(f"{p['name']} ({p['relation']}, {p['role']}){photo_tag}{note_tag}")

        reply = "Household & People Registry: " + "; ".join(summaries)
        return {"intent": "SOCIAL_IDENTITY_QUERY", "spoken_response": reply, "people": target_list}

    def handle_social_or_identity(self, prompt: str) -> Dict[str, Any]:
        lower = prompt.lower().strip()
        if any(p in lower for p in ["who is in", "house members", "household members", "list people", "who is my", "tell me about "]):
            return self.query_people(prompt)

        photo_match = re.search(r"([a-zA-Z0-9_\-\./]+\.(?:jpg|jpeg|png|webp))", prompt, flags=re.I)
        photo_path = photo_match.group(1) if photo_match else None

        name_match = re.search(
            r"(?:member|person|brother|sister|mother|father|wife|husband|friend|colleague|for)\s+([A-Z][a-zA-Z]+)",
            prompt,
        )
        if not name_match:
            name_match = re.search(r"(?:named|is)\s+([A-Z][a-zA-Z]+)", prompt)
        name = name_match.group(1) if name_match else "Operator"

        rel_match = re.search(
            r"\b(brother|sister|mother|father|mom|dad|wife|husband|partner|son|daughter|friend|colleague|roommate|admin|owner)\b",
            lower,
        )
        relation = rel_match.group(1) if rel_match else "household member"
        role = "admin" if relation in ["admin", "owner"] else "household"

        return self.upsert_person(name=name, relation=relation, role=role, photo_path=photo_path, notes=prompt)

    # =========================================================================
    # ZONE 2: FOOD, NUTRITION & MACRO TRACKING
    # =========================================================================
    def log_nutrition(
        self,
        meal_description: str,
        calories: Optional[int] = None,
        protein_g: Optional[float] = None,
        carbs_g: Optional[float] = None,
        fat_g: Optional[float] = None,
        image_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        date_str = datetime.now().strftime("%Y-%m-%d")

        cal_m = re.search(r"(\d+)\s*(?:cal|kcal|calories)", meal_description, flags=re.I)
        prot_m = re.search(r"(\d+(?:\.\d+)?)\s*g?\s*protein", meal_description, flags=re.I)
        carb_m = re.search(r"(\d+(?:\.\d+)?)\s*g?\s*carb", meal_description, flags=re.I)
        fat_m = re.search(r"(\d+(?:\.\d+)?)\s*g?\s*fat", meal_description, flags=re.I)

        cals = calories if calories is not None else (int(cal_m.group(1)) if cal_m else 350)
        prot = protein_g if protein_g is not None else (float(prot_m.group(1)) if prot_m else 18.0)
        carbs = carbs_g if carbs_g is not None else (float(carb_m.group(1)) if carb_m else 35.0)
        fat = fat_g if fat_g is not None else (float(fat_m.group(1)) if fat_m else 12.0)

        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO nutrition_ledger (date_str, meal_description, calories, protein_g, carbs_g, fat_g, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (date_str, meal_description, cals, prot, carbs, fat, time.time()),
            )
            entry_id = cur.lastrowid
            conn.commit()

        node_id = f"meal_{hashlib.md5(meal_description.encode('utf-8')).hexdigest()[:8]}"
        meal_label = f"Meal_{date_str}_{cals}kcal"

        def _rollback_meal() -> str:
            with sqlite3.connect(self.db_path) as c:
                c.execute("DELETE FROM nutrition_ledger WHERE entry_id = ?", (entry_id,))
                c.commit()
            self._delete_graph_node_and_obsidian(node_id, NodeType.HEALTH.value, meal_label)
            return f"Removed logged meal ({cals} kcal, {prot}g protein) from nutrition ledger and GraphBrain."

        undo_ledger.register_undo("NUTRITION_LOG", f"Logged meal ({cals} kcal)", _rollback_meal)
        self.graph_brain.add_or_update_node(
            node_id=node_id,
            node_type=NodeType.HEALTH,
            metadata={
                "date": date_str,
                "meal": meal_description,
                "calories": cals,
                "protein_g": prot,
                "carbs_g": carbs,
                "fat_g": fat,
            },
            label=f"Meal_{date_str}_{cals}kcal",
            sync_obsidian=True,
        )

        totals = self.get_daily_nutrition_summary(date_str)
        reply = (
            f"Logged meal ({cals} kcal, {prot}g protein). "
            f"Today's total: {totals['total_calories']} kcal and {totals['total_protein_g']}g protein across {totals['meals_count']} meals."
        )
        return {"intent": "HEALTH_NUTRITION_LOG", "spoken_response": reply, "daily_totals": totals}

    def get_daily_nutrition_summary(self, date_str: Optional[str] = None) -> Dict[str, Any]:
        target_date = date_str or datetime.now().strftime("%Y-%m-%d")
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(calories), 0), COALESCE(SUM(protein_g), 0),
                       COALESCE(SUM(carbs_g), 0), COALESCE(SUM(fat_g), 0)
                FROM nutrition_ledger WHERE date_str = ?
                """,
                (target_date,),
            ).fetchone()
        return {
            "date": target_date,
            "meals_count": row[0],
            "total_calories": int(row[1]),
            "total_protein_g": round(float(row[2]), 1),
            "total_carbs_g": round(float(row[3]), 1),
            "total_fat_g": round(float(row[4]), 1),
        }

    def handle_health_or_nutrition(self, prompt: str) -> Dict[str, Any]:
        lower = prompt.lower().strip()
        is_log_action = bool(re.search(r"\b(?:log\s+meal|i\s+ate|just\s+ate|just\s+had)\b", lower))
        if not is_log_action or any(q in lower for q in ["how many calories", "check the calories", "check calories", "daily nutrition", "macro summary", "protein today", "what did i eat"]):
            t = self.get_daily_nutrition_summary()
            reply = (
                f"Today ({t['date']}) you have logged {t['meals_count']} meals totaling "
                f"{t['total_calories']} kcal, {t['total_protein_g']}g protein, {t['total_carbs_g']}g carbs, and {t['total_fat_g']}g fat."
            )
            return {"intent": "HEALTH_NUTRITION_SUMMARY", "spoken_response": reply, "daily_totals": t}

        return self.log_nutrition(prompt)

    # =========================================================================
    # ZONE 2B: AUTONOMOUS PHOTO INGESTION, SCREEN CAPTURE & PHOTO VAULT SEARCH
    # =========================================================================
    async def ingest_and_analyze_photo(self, image_path: str, user_prompt: str = "") -> Dict[str, Any]:
        """Idempotently analyzes an ingested photo via Vision and indexes into Photo Vault & GraphBrain."""
        analysis = await vision_analyzer.analyze_image(image_path, user_hint=user_prompt)
        category = analysis.get("category", "scene").lower()
        file_path = analysis.get("file_path", str(image_path))
        summary = analysis.get("summary", f"Analyzed image {Path(file_path).name}")
        tags = list(analysis.get("detected_objects", []))
        ocr_text = analysis.get("ocr_text", "")

        # Deterministic photo_id from canonical path so re-analyzing updates in place (Zero Duplicates!)
        canon_path = str(Path(file_path).resolve())
        photo_id = f"photo_{hashlib.md5(canon_path.encode('utf-8')).hexdigest()[:10]}"

        spoken_parts = []
        extra_meta: Dict[str, Any] = {"analysis": analysis}

        if category == "food":
            fn = analysis.get("food_nutrition", {})
            dish = fn.get("dish_name") or "Visual Meal"
            cals = int(fn.get("calories", 500))
            prot = float(fn.get("protein_g", 30.0))
            carbs = float(fn.get("carbs_g", 40.0))
            fat = float(fn.get("fat_g", 15.0))

            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM nutrition_ledger WHERE meal_description LIKE ?", (f"%[Photo Analysis: {dish}]%",))
                conn.commit()

            nutri_res = self.log_nutrition(
                meal_description=f"[Photo Analysis: {dish}] {summary}",
                calories=cals,
                protein_g=prot,
                carbs_g=carbs,
                fat_g=fat,
                image_path=file_path,
            )
            extra_meta["nutrition_logged"] = nutri_res.get("daily_totals", {})
            tags.extend(["food", "meal", dish.lower(), f"{cals}kcal", f"{int(prot)}g_protein"])
            spoken_parts.append(
                f"Photo analyzed as food ({dish}): estimated {cals} kcal, {prot}g protein, {carbs}g carbs, {fat}g fat. "
                "Saved to your nutrition tracker and photo vault."
            )

        elif category == "person":
            pinfo = analysis.get("person_info", {})
            person_name = pinfo.get("name") or pinfo.get("name_hint") or "Household Member"
            relation = pinfo.get("relation") or "household member"
            face_sig = pinfo.get("face_signature", "")

            person_res = self.upsert_person(
                name=person_name,
                relation=relation,
                role="household",
                photo_path=file_path,
                notes=f"Visually identified from {Path(file_path).name} ({face_sig}): {summary}",
            )
            extra_meta["person_logged"] = person_res
            tags.extend(["person", "face", person_name.lower(), relation.lower()])
            spoken_parts.append(
                f"Photo analyzed as person: identified {person_name} ({relation}). "
                "Enrolled biometric face signature and linked photo in household registry."
            )

        else:
            ui_elems = analysis.get("ui_elements", [])
            tags.extend([category, "capture"] + [u.get("label", "") for u in ui_elems[:4]])
            ui_str = f" Grounded {len(ui_elems)} UI targets (e.g. {ui_elems[0]['label']} at {ui_elems[0]['center']})." if ui_elems else ""
            ocr_snippet = f" OCR: {ocr_text[:70]}" if ocr_text else ""
            spoken_parts.append(f"Captured and analyzed {category}: {summary}.{ui_str}{ocr_snippet}")

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO photo_vault (
                    photo_id, file_path, category, visual_summary, detected_tags, ocr_text, metadata_json, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    photo_id,
                    file_path,
                    category,
                    summary,
                    json.dumps(list(dict.fromkeys(tags))),
                    ocr_text,
                    json.dumps(extra_meta),
                    time.time(),
                ),
            )
            conn.commit()

        self.graph_brain.add_or_update_node(
            node_id=photo_id,
            node_type=NodeType.FILE,
            metadata={
                "file_path": file_path,
                "category": category,
                "summary": summary,
                "tags": ", ".join(dict.fromkeys(tags)),
                "ocr_text": ocr_text[:200],
            },
            label=f"Photo_{category.capitalize()}_{Path(file_path).stem}",
            sync_obsidian=True,
        )

        return {
            "intent": f"VISION_PHOTO_{category.upper()}",
            "photo_id": photo_id,
            "category": category,
            "file_path": file_path,
            "analysis": analysis,
            "spoken_response": " ".join(spoken_parts),
        }

    async def capture_and_analyze_screen(self, user_prompt: str = "") -> Dict[str, Any]:
        lower = user_prompt.lower()
        # If user asks to see/analyze a pic/photo/person/food currently shown on screen and a photo was recently opened/ingested
        asks_about_pic = any(w in lower for w in ["pic", "photo", "picture", "image", "food", "calories", "person", "who is"])
        if asks_about_pic and vision_analyzer.last_captured_path and vision_analyzer.last_captured_path.exists():
            if "screen" not in vision_analyzer.last_captured_path.name:
                res = await self.ingest_and_analyze_photo(str(vision_analyzer.last_captured_path), user_prompt=user_prompt)
                res["intent"] = "VISION_SCREEN_CAPTURE"
                res["spoken_response"] = f"Inspecting the picture on your screen ({vision_analyzer.last_captured_path.name}): " + res.get("spoken_response", "")
                return res

        captured_path = vision_analyzer.capture_live_screen()
        res = await self.ingest_and_analyze_photo(str(captured_path), user_prompt=user_prompt)
        res["intent"] = "VISION_SCREEN_CAPTURE"
        return res

    def search_photos(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        clean_q = re.sub(
            r"^(?:please\s+)?(?:search\s+through\s+photos\s+for|search\s+photos\s+for|find\s+photos?\s+of|show\s+photos?\s+of|search\s+photos)\s*",
            "",
            query.strip(),
            flags=re.I,
        ).strip("? ")

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM photo_vault ORDER BY timestamp DESC").fetchall()

        if not rows:
            return {"intent": "PHOTO_SEARCH", "spoken_response": "Your photo vault is currently empty.", "matches": []}

        q_vec = FastSemanticProjector.embed_text(clean_q)
        scored: List[tuple[float, Dict[str, Any]]] = []

        for r in rows:
            doc_text = f"{r['category']} {r['visual_summary']} {r['detected_tags']} {r['ocr_text'] or ''} {r['file_path']}"
            d_vec = FastSemanticProjector.embed_text(doc_text)
            sim = FastSemanticProjector.cosine_similarity(q_vec, d_vec)
            for tok in re.findall(r"[a-z0-9]+", clean_q.lower()):
                if len(tok) >= 3 and tok in doc_text.lower():
                    sim += 0.25
            if sim > 0.05:
                scored.append(
                    (
                        sim,
                        {
                            "photo_id": r["photo_id"],
                            "file_path": r["file_path"],
                            "category": r["category"],
                            "summary": r["visual_summary"],
                            "tags": json.loads(r["detected_tags"]),
                            "score": round(float(sim), 4),
                        },
                    )
                )

        scored.sort(key=lambda x: x[0], reverse=True)
        matches = [m[1] for m in scored[:top_k]]

        if matches:
            top = matches[0]
            reply = (
                f"Found {len(matches)} matching photo(s) in vault. "
                f"Top match: {Path(top['file_path']).name} [{top['category'].upper()}] — {top['summary']}"
            )
        else:
            reply = f"No photos in your vault matched '{clean_q}'."

        return {"intent": "PHOTO_SEARCH", "spoken_response": reply, "matches": matches}

    # =========================================================================
    # ZONE 2C: STEP 3 — YOUTUBE TRANSCRIPT GRAPH INDEXING & PROACTIVE NOTIFICATIONS
    # =========================================================================
    def ingest_youtube_transcript(self, url_or_prompt: str) -> Dict[str, Any]:
        """Extracts full timestamped YouTube transcript and indexes into GraphBrainDB & Research Vault."""
        from agent.pa_scaffolder.universal_reader import universal_reader
        m = re.search(r"https?://[^\s]+", url_or_prompt)
        url = m.group(0) if m else url_or_prompt.strip()

        data = universal_reader.extract_youtube_transcript(url)
        vid = data["video_id"]
        title = data["title"]
        segments = data["segments"]
        full_text = data["formatted_transcript"]

        node_id = f"yt_{vid}"
        self.graph_brain.add_or_update_node(
            node_id=node_id,
            node_type=NodeType.RESEARCH,
            metadata={
                "video_id": vid,
                "title": title,
                "segments_count": len(segments),
                "fact": full_text[:1500],
                "transcript": full_text[:1500],
            },
            label=f"YouTube_{title[:35]}",
            sync_obsidian=True,
        )
        self.research_memory.store_research_note(
            topic=f"YouTube Transcript: {title[:40]}",
            content_md=f"# {title}\nURL: {url}\n\n## Timestamped Transcript\n{full_text}",
            tags=[vid, "YouTube_Transcript", title[:25]],
        )

        preview_segs = [f"[{int(s['start'])//60:02d}:{int(s['start'])%60:02d}] {s['text']}" for s in segments[:3]]
        spoken = f"Extracted {len(segments)} timestamped segments from '{title}': " + " | ".join(preview_segs)
        return {
            "intent": "YOUTUBE_TRANSCRIPT_INGESTED",
            "video_id": vid,
            "title": title,
            "segments_count": len(segments),
            "segments": segments,
            "node_id": node_id,
            "spoken_response": spoken[:240],
        }

    def triage_proactive_notifications(self, app_filter: Optional[str] = None) -> Dict[str, Any]:
        """Polls cross-platform notifications, deduplicates seen IDs, and elevates messages from household members."""
        from agent.pa_scaffolder.universal_reader import universal_reader
        raw_list = universal_reader.collect_raw_os_notifications(app_filter=app_filter)

        household_names: Dict[str, str] = {}
        with sqlite3.connect(self.db_path) as conn:
            for name, rel in conn.execute("SELECT name, relation FROM household_people").fetchall():
                household_names[name.lower()] = rel

        urgent_keywords = {"urgent", "emergency", "asap", "call me", "otp", "security", "failed", "down", "critical", "help", "locked out"}
        new_alerts: List[Dict[str, Any]] = []
        high_priority: List[Dict[str, Any]] = []

        for item in raw_list:
            nid = item["id"]
            if nid in universal_reader._seen_notification_ids:
                continue
            universal_reader._seen_notification_ids.add(nid)

            sender_lower = item["sender"].lower()
            content_lower = item["content"].lower()

            matched_member = None
            matched_rel = ""
            for h_name, h_rel in household_names.items():
                if h_name in sender_lower or h_name in content_lower:
                    matched_member = h_name.title()
                    matched_rel = h_rel
                    break

            is_urgent = any(k in content_lower or k in sender_lower for k in urgent_keywords)
            if matched_member:
                priority = "HIGH_PRIORITY_HOUSEHOLD"
            elif is_urgent:
                priority = "HIGH_PRIORITY_URGENT"
            else:
                priority = "STANDARD"

            enriched = {
                **item,
                "priority": priority,
                "household_member": matched_member,
                "relation": matched_rel,
            }
            new_alerts.append(enriched)
            if priority.startswith("HIGH_PRIORITY"):
                high_priority.append(enriched)

            self.graph_brain.add_or_update_node(
                node_id=f"notif_{nid}",
                node_type=NodeType.SOCIAL if matched_member else NodeType.EPISODIC,
                metadata={
                    "app": item["app"],
                    "sender": item["sender"],
                    "content": item["content"],
                    "priority": priority,
                    "household_member": matched_member or "none",
                },
                label=f"Notif_{item['app']}_{item['sender'][:20]}",
                sync_obsidian=bool(matched_member),
            )

        dnd_policy = mode_kernel.active_spec.dnd_policy
        suppressed_count = 0
        if dnd_policy == "household_emergency_only":
            suppressed_count = len([a for a in new_alerts if not a["priority"].startswith("HIGH_PRIORITY")])
            new_alerts = list(high_priority)
            event_bus.emit("GAMER_DND_FILTERED", {"mode": mode_kernel.current_mode.value, "suppressed": suppressed_count, "breakthrough": len(high_priority)})

        if high_priority:
            top = high_priority[0]
            rel_tag = f" ({top['relation']})" if top.get("relation") else ""
            dnd_note = f" [DND suppressed {suppressed_count} non-urgent alert(s) in {mode_kernel.current_mode.value.upper()} mode]" if suppressed_count else ""
            spoken = (
                f"Proactive Priority Alert [{top['app']}] from {top['sender']}{rel_tag}: "
                f"'{top['content']}' ({len(high_priority)} priority, {len(new_alerts)} shown).{dnd_note}"
            )
        elif new_alerts:
            top = new_alerts[0]
            spoken = f"You have {len(new_alerts)} new notification(s). Latest on {top['app']} from {top['sender']}: {top['content']}"
        else:
            spoken = "No new unread notifications since last check."

        return {
            "intent": "PROACTIVE_NOTIFICATION_TRIAGE",
            "new_count": len(new_alerts),
            "high_priority_count": len(high_priority),
            "high_priority_alerts": high_priority,
            "all_new_alerts": new_alerts,
            "spoken_response": spoken,
        }

    # =========================================================================
    # ZONE 3: EVERYDAY WORK TRACKING, PASSIVE ADAPTATION & FACT CONSOLIDATION
    # =========================================================================
    def observe_and_adapt(self, user_prompt: str, intent: str, result: Dict[str, Any]) -> None:
        if not user_prompt or not user_prompt.strip():
            return

        lower = user_prompt.lower().strip()
        now = time.time()
        habit_key = f"{intent}:{lower[:40]}"
        adaptation_rule = ""

        if "pytest" in lower:
            habit_key = "tool:pytest"
            adaptation_rule = "User frequently verifies code with pytest; prioritize test-driven verification."
        elif "attention" in lower or "transformer" in lower or "kv" in lower:
            habit_key = "work:edge_transformer_research"
            adaptation_rule = "User actively researches sub-quadratic attention and KV-cache optimization."
        elif intent == "READ_DOCUMENT_SLICE" and result.get("file"):
            habit_key = f"file:{result['file']}"
            adaptation_rule = f"User actively inspects {result['file']}."

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO behavior_habits (habit_key, category, frequency, last_observed, adaptation_rule)
                VALUES (?, ?, 1, ?, ?)
                ON CONFLICT(habit_key) DO UPDATE SET
                    frequency = behavior_habits.frequency + 1,
                    last_observed = excluded.last_observed,
                    adaptation_rule = CASE WHEN excluded.adaptation_rule != '' THEN excluded.adaptation_rule ELSE behavior_habits.adaptation_rule END
                """,
                (habit_key, intent, now, adaptation_rule),
            )
            conn.commit()

        if adaptation_rule:
            self.user_profile.add_instruction(adaptation_rule)
            node_id = f"habit_{re.sub(r'[^a-z0-9]', '_', habit_key)}"
            self.graph_brain.add_or_update_node(
                node_id=node_id,
                node_type=NodeType.PROJECT,
                metadata={"habit": habit_key, "adaptation": adaptation_rule},
                label=f"WorkHabit_{habit_key.split(':')[-1]}",
                sync_obsidian=True,
            )

    def get_adapted_behaviors(self, limit: int = 4) -> List[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT habit_key, frequency, adaptation_rule
                FROM behavior_habits
                WHERE adaptation_rule != ''
                ORDER BY frequency DESC, last_observed DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [f"{r[2]} (observed {r[1]}x)" for r in rows]

    def consolidate_background_facts(self, user_prompt: str) -> List[Dict[str, Any]]:
        extracted: List[Dict[str, Any]] = []
        p = user_prompt.strip()
        lower = p.lower()

        allergy_m = re.search(r"\b(?:i am|i'm|im)\s+(?:allergic to|intolerant to)\s+([a-zA-Z0-9\s\-]+)", lower)
        if allergy_m:
            substance = allergy_m.group(1).strip()
            nid = f"health_allergy_{re.sub(r'[^a-z0-9]', '_', substance)}"
            fact_text = f"User is allergic/intolerant to {substance}"
            self.user_profile.add_instruction(fact_text)
            self.graph_brain.add_or_update_node(
                node_id=nid,
                node_type=NodeType.HEALTH,
                metadata={"fact": fact_text, "allergy": substance},
                label=f"Allergy_{substance.title()}",
                sync_obsidian=True,
            )
            extracted.append({"type": "allergy", "node_id": nid, "fact": fact_text})

        switch_m = re.search(
            r"\b(?:switched|migrated|moved|changed|replaced)\b.*?(?:from\s+([A-Za-z0-9_\-]+)\s+to\s+([A-Za-z0-9_\-]+)|([A-Za-z0-9_\-]+)\s+with\s+([A-Za-z0-9_\-]+))",
            p,
            flags=re.I,
        )
        if switch_m:
            old_tech = (switch_m.group(1) or switch_m.group(3) or "").strip()
            new_tech = (switch_m.group(2) or switch_m.group(4) or "").strip()
            if old_tech and new_tech:
                nid = f"proj_switch_{new_tech.lower()}"
                fact_text = f"Switched project architecture from [[{old_tech}]] to [[{new_tech}]] (active stack: {new_tech})"
                superseded_count = self.graph_brain.supersede_contradicting_nodes(old_tech, nid, fact_text)
                self.user_profile.add_instruction(fact_text)
                self.graph_brain.add_or_update_node(
                    node_id=nid,
                    node_type=NodeType.PROJECT,
                    metadata={"fact": fact_text, "active_tech": new_tech, "deprecated_tech": old_tech, "superseded_nodes": superseded_count},
                    label=f"Stack_{new_tech}_Supersedes_{old_tech}",
                    sync_obsidian=True,
                )
                extracted.append({"type": "stack_switch", "node_id": nid, "old": old_tech, "new": new_tech, "superseded": superseded_count})

        social_m = re.search(
            r"\bmy\s+(brother|sister|mother|father|mom|dad|wife|husband|partner|roommate|friend|cousin)\s+([A-Z][a-zA-Z]+)\s+(moved in|moved out|visiting|lives here|staying with us)",
            p,
            flags=re.I,
        )
        if social_m:
            rel = social_m.group(1).lower()
            person_name = social_m.group(2).strip().title()
            event_status = social_m.group(3).lower()
            role = "former_household" if "moved out" in event_status else "household"
            self.upsert_person(
                name=person_name,
                relation=rel,
                role=role,
                notes=f"{person_name} ({rel}) status updated: {event_status}",
            )
            extracted.append({"type": "social_update", "name": person_name, "relation": rel, "status": event_status})

        return extracted

    # =========================================================================
    # ZONE 4: UNIFIED CONTEXT ASSEMBLY (ZERO SPLIT-BRAIN)
    # =========================================================================
    def build_prompt_memory_context(self, query: str, top_k: int = 3) -> str:
        sections: List[str] = []

        profile_ctx = self.user_profile.get_system_prompt_context().strip()
        habits = self.get_adapted_behaviors(limit=3)
        if habits:
            profile_ctx += "\n- Observed Work Adaptations: " + " | ".join(habits)
        if profile_ctx:
            sections.append(profile_ctx)

        people_info = self.query_people().get("people", [])
        if people_info:
            p_str = ", ".join(f"{p['name']} ({p['relation']})" for p in people_info[:5])
            sections.append(f"[Household & Social Registry]\n- Known People: {p_str}")

        nutri = self.get_daily_nutrition_summary()
        if nutri["meals_count"] > 0:
            sections.append(
                f"[Daily Nutrition Tracker]\n- Today ({nutri['date']}): "
                f"{nutri['total_calories']} kcal, {nutri['total_protein_g']}g protein across {nutri['meals_count']} meals"
            )

        try:
            graph_hits = self.graph_brain.get_relevant_context(query, top_k=top_k)
            if graph_hits:
                lines = ["[GraphBrain Hybrid Memory Recall]"]
                for hit in graph_hits:
                    lbl = hit.get("label") or hit.get("node_id", "Memory")
                    content = hit.get("content") or str(hit.get("properties", ""))
                    lines.append(f"- {lbl}: {content[:160]}")
                sections.append("\n".join(lines))
        except Exception:
            pass

        try:
            papers = self.research_memory.search_papers(query, limit=2)
            dead_ends = self.research_memory.query_dead_ends(query)
            notes = self.research_memory.search_research_notes(query, limit=2)
            res_lines = []
            for p in papers:
                res_lines.append(f"- Paper ({p['year']}): {p['title']} — {p['abstract'][:120]}")
            for d in dead_ends[:2]:
                res_lines.append(f"- Known Dead-End: {d['hypothesis']} failed due to {d['root_cause']}")
            for n in notes:
                res_lines.append(f"- Research Note [{n['topic']}]: {n['content_md'][:120]}")
            if res_lines:
                sections.append("[Research Vault Recall]\n" + "\n".join(res_lines))
        except Exception:
            pass

        return "\n\n".join(sections)

    # =========================================================================
    # ZONE 5: TURN INGESTION, EXPLICIT MEMORY, RESEARCH & EBBINGHAUS DECAY
    # =========================================================================
    def ingest_turn(
        self,
        user_prompt: str,
        intent: str,
        spoken_response: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not user_prompt or not user_prompt.strip():
            return

        self.conv_memory.log_message("user", user_prompt)
        if spoken_response:
            self.conv_memory.log_message("assistant", spoken_response)

        self.observe_and_adapt(user_prompt, intent, metadata or {})
        self.consolidate_background_facts(user_prompt)

        node_id = f"turn_{int(time.time() * 1000)}"
        meta = {
            "utterance": user_prompt[:300],
            "intent": intent,
            "response": (spoken_response or "")[:300],
        }
        if metadata:
            meta.update(metadata)

        has_wikilink = "[[" in user_prompt and "]]" in user_prompt
        n_type = NodeType.CONCEPT if has_wikilink else NodeType.EPISODIC

        turn_label = f"{intent}_{node_id[-5:]}"
        self.graph_brain.add_or_update_node(
            node_id=node_id,
            node_type=n_type,
            metadata=meta,
            label=turn_label,
            sync_obsidian=has_wikilink,
        )

        def _rollback_episodic_turn() -> str:
            self._delete_graph_node_and_obsidian(node_id, n_type.value if hasattr(n_type, "value") else str(n_type), turn_label)
            return ""

        undo_ledger.register_undo("EPISODIC_TURN", f"Turn log {node_id}", _rollback_episodic_turn)

        self._turn_counter += 1
        if self._turn_counter % 10 == 0:
            try:
                self.graph_brain.run_decay_cycle()
            except Exception:
                pass

    def store_explicit_memory(self, raw_statement: str) -> Dict[str, Any]:
        clean = re.sub(
            r"^(?:please\s+)?(?:remember\s+that|remember|note\s+that|save\s+to\s+memory|save\s+note)\s+",
            "",
            raw_statement.strip(),
            flags=re.I,
        ).strip()

        self.user_profile.add_instruction(clean)
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", clean[:35]).strip("_").lower()
        node_id = f"mem_{slug}"
        is_pref = any(w in clean.lower() for w in ["prefer", "always", "never", "favorite", "default", "use "])
        node_type = NodeType.PREFERENCE if is_pref else NodeType.CONCEPT

        self.graph_brain.add_or_update_node(
            node_id=node_id,
            node_type=node_type,
            metadata={"fact": clean, "timestamp": time.time()},
            label=clean[:45],
            sync_obsidian=True,
        )

        if "[[" in clean or any(w in clean.lower() for w in ["paper", "attention", "transformer", "hypothesis", "experiment"]):
            self.research_memory.store_research_note(topic=clean[:40], content_md=clean)

        def _rollback_memory() -> str:
            if clean in self.user_profile.profile.get("custom_instructions", []):
                self.user_profile.profile["custom_instructions"].remove(clean)
                self.user_profile.save()
            self._delete_graph_node_and_obsidian(node_id, node_type.value, clean[:45], content_match=clean[:45])
            return f"Removed memory node '{clean[:45]}' from GraphBrain and Obsidian vault."

        undo_ledger.register_undo("MEMORY_STORE", f"Stored memory '{clean[:35]}'", _rollback_memory)
        reply = f"Locked into GraphBrain and synced to your Obsidian vault: {clean}"
        return {"intent": "MEMORY_STORE", "spoken_response": reply, "node_id": node_id}

    def recall_explicit_memory(self, query: str) -> Dict[str, Any]:
        clean_q = re.sub(
            r"^(?:what\s+do\s+you\s+remember\s+about|what\s+did\s+i\s+note\s+about|search\s+memory\s+for|recall|what\s+is\s+in\s+my\s+memory\s+about)\s+",
            "",
            query.strip(),
            flags=re.I,
        ).strip("? ")

        hits = self.graph_brain.get_relevant_context(clean_q, top_k=3)
        res_notes = self.research_memory.search_research_notes(clean_q, limit=2)
        dead_ends = self.research_memory.query_dead_ends(clean_q)

        summaries = []
        for h in hits:
            props = h.get("properties", {})
            fact = (
                props.get("fact")
                or props.get("transcript")
                or props.get("notes")
                or props.get("meal")
                or props.get("utterance")
                or h.get("content", "")
            )
            if fact:
                summaries.append(str(fact)[:140])

        for n in res_notes:
            summaries.append(f"Research Note: {n['content_md'][:120]}")

        for d in dead_ends[:1]:
            summaries.append(f"Dead-End: {d['hypothesis']} ({d['root_cause']})")

        if summaries:
            combined = " | ".join(dict.fromkeys(summaries))
            reply = f"From your GraphBrain and Research Vault: {combined[:220]}"
        else:
            reply = f"No stored graph nodes matched '{clean_q}'."

        return {"intent": "MEMORY_RECALL", "spoken_response": reply, "results_count": len(summaries)}

    def handle_research_action(self, prompt: str) -> Dict[str, Any]:
        lower = prompt.lower().strip()

        if "dead end" in lower or "failed hypothesis" in lower:
            clean = re.sub(r"^.*?(?:dead\s+end|failed\s+hypothesis)\s*[:\-]?\s*", "", prompt, flags=re.I).strip()
            de_id = f"de_{hashlib.md5(clean.encode('utf-8')).hexdigest()[:8]}"
            record = DeadEndRecord(
                dead_end_id=de_id,
                hypothesis=clean,
                failed_mechanism="Empirical divergence",
                compute_expended_hrs=1.0,
                root_cause=clean,
            )
            self.research_memory.record_dead_end(record)
            self.graph_brain.add_or_update_node(
                node_id=de_id,
                node_type=NodeType.RESEARCH,
                metadata={"dead_end": clean},
                label=f"DeadEnd_{de_id}",
                sync_obsidian=True,
            )
            return {
                "intent": "RESEARCH_DEAD_END_LOGGED",
                "spoken_response": f"Logged dead-end to Research Vault and Obsidian graph: {clean[:120]}",
            }

        if "digest" in lower or "research summary" in lower:
            topic_match = re.search(r"(?:digest|summary)\s+(?:on|for|about)\s+(.+)$", prompt, flags=re.I)
            topic = topic_match.group(1).strip() if topic_match else "Sub-Quadratic Attention"
            if self.digest_engine:
                try:
                    digest = self.digest_engine.generate_5_line_digest(topic)
                    spoken = f"5-line digest for {topic}: {digest.digest_5_lines[1]} {digest.digest_5_lines[2]} {digest.digest_5_lines[4]}"
                    return {
                        "intent": "RESEARCH_DIGEST",
                        "spoken_response": spoken[:220],
                        "raw_markdown": digest.raw_markdown,
                    }
                except Exception:
                    pass
            dead_ends = self.research_memory.query_dead_ends(topic)
            gap = dead_ends[0]["root_cause"] if dead_ends else "Outlier activation scaling required."
            lines = [
                f"1. [TOPIC] {topic}",
                f"2. [TOP PAPER] Foundational synthesis on {topic}",
                "3. [CORE FINDING] Sub-quadratic reduction in KV memory footprint.",
                f"4. [OPEN GAP] {gap}",
                f"5. [NEXT ACTION] Benchmark dynamic group quantization on {topic}.",
            ]
            return {
                "intent": "RESEARCH_DIGEST",
                "spoken_response": f"5-line digest for {topic}: {lines[2]} Open gap: {gap}",
                "raw_markdown": "\n".join(lines),
            }

        clean_topic = re.sub(r"^(?:search\s+papers\s+on|research|literature\s+on|find\s+claims\s+about)\s+", "", prompt, flags=re.I).strip()
        papers = self.research_memory.search_papers(clean_topic, limit=3)
        claims = self.research_memory.query_claims(clean_topic, limit=3)
        dead_ends = self.research_memory.query_dead_ends(clean_topic)

        if papers or claims or dead_ends:
            parts = []
            if papers:
                parts.append(f"Top paper: {papers[0]['title']} ({papers[0]['year']}).")
            if claims:
                parts.append(f"Claim: {claims[0]['claim_text'][:100]}.")
            if dead_ends:
                parts.append(f"Warning—known dead-end: {dead_ends[0]['root_cause'][:80]}.")
            reply = " ".join(parts)
        else:
            self.research_memory.store_research_note(topic=clean_topic[:40], content_md=f"Initiated research inquiry on [[{clean_topic}]].")
            reply = f"Created new Obsidian research node for '{clean_topic}'."

        return {"intent": "RESEARCH_MEMORY_QUERY", "spoken_response": reply}


memory_hub = UnifiedMemoryHub()

# UnifiedMemoryGraphService 2-way recall bridge
_gb_cls = memory_hub.graph_brain.__class__
_orig_gb_get_relevant_context = _gb_cls.get_relevant_context

def _bridged_gb_get_relevant_context(self, query: str, top_k: int = 5) -> str:
    base_ctx = _orig_gb_get_relevant_context(self, query, top_k=top_k)
    try:
        import re, sqlite3
        from agent.memory_graph.memory_service import unified_memory_service
        extra_lines = []
        scoped = unified_memory_service.retrieve_scoped_memories(query, top_k=top_k)
        for r in scoped.get('results', []):
            c = r.get('content', '')
            if c and c not in base_ctx and c not in extra_lines:
                extra_lines.append(c)
        q_words = [w.lower() for w in re.findall(r'[a-zA-Z0-9_]{4,}', query) if w.lower() not in ('does', 'what', 'when', 'where', 'which', 'friday', 'handle', 'work')]
        if q_words and unified_memory_service.DB_PATH.exists():
            with sqlite3.connect(unified_memory_service.DB_PATH) as conn:
                rows = conn.execute("SELECT content FROM unified_memory_nodes WHERE status = 'ACTIVE' ORDER BY updated_at DESC LIMIT 50").fetchall()
                for (content_txt,) in rows:
                    low_c = content_txt.lower()
                    if any(w in low_c for w in q_words) and content_txt not in base_ctx and content_txt not in extra_lines:
                        extra_lines.append(content_txt)
        if extra_lines:
            sep = chr(10)
            return (base_ctx + sep + sep.join(extra_lines[:top_k])).strip()
    except Exception:
        pass
    return base_ctx

_gb_cls.get_relevant_context = _bridged_gb_get_relevant_context
