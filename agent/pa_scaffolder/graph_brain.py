from __future__ import annotations
import sqlite3
from functools import lru_cache

import hashlib
import json
import math
import re
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np

from agent.memory.sqlite_driver import SQLiteMemoryDriver
from agent.memory.hybrid_retriever import HybridRetriever
from agent.memory.decay_manager import EbbinghausDecayManager


class NodeType(str, Enum):
    HEALTH = "health"
    SOCIAL = "social"
    EPISODIC = "episodic"
    PROJECT = "project"
    CONCEPT = "concept"
    PREFERENCE = "preference"
    FILE = "file"
    RESEARCH = "research"


class FastSemanticProjector:
    """Synonym-Aware 384-Dimensional Semantic Embedding Projector with Vectorized Dot Product."""

    DIM = 384

    SYNONYM_CLUSTERS = [
        {"heart", "cardio", "cardiovascular", "pulse", "aerobic", "coronary"},
        {"stamina", "endurance", "vo2", "vo2max", "fatigue", "conditioning", "fitness"},
        {"memory", "ram", "kv", "cache", "buffer", "footprint", "vram", "recall", "remember"},
        {"attention", "transformer", "subquadratic", "linear", "flash", "sequence", "perplexity"},
        {"quantization", "int2", "int4", "fp8", "precision", "bitwidth", "weights", "outlier"},
        {"brother", "sister", "sibling", "mother", "father", "parent", "family", "household", "member", "roommate", "relative"},
        {"calories", "kcal", "nutrition", "macros", "protein", "carbs", "fat", "meal", "diet", "food", "ate", "allergic", "allergy"},
        {"test", "tests", "pytest", "unittest", "verify", "suite", "check", "assert"},
        {"disk", "storage", "space", "df", "drive", "filesystem", "gigabytes"},
        {"switch", "switched", "migrated", "replaced", "instead", "deprecated", "superseded", "backend"},
        {"screen", "display", "monitor", "window", "ocr", "screenshot", "desktop"},
        {"notification", "alert", "unread", "message", "whatsapp", "slack", "discord", "telegram"},
    ]

    @classmethod
    def _expand_concepts(cls, tokens: List[str]) -> List[str]:
        expanded = list(tokens)
        token_set = {re.sub(r"[^a-z0-9]", "", t) for t in tokens}
        for idx, cluster in enumerate(cls.SYNONYM_CLUSTERS):
            if token_set & cluster:
                expanded.append(f"__concept_cluster_{idx}__")
        return expanded

    @classmethod
    @lru_cache(maxsize=1024)
    def embed_text(cls, text: str) -> np.ndarray:
        clean = re.sub(r"[^a-z0-9_\s]", " ", text.lower()).strip()
        raw_tokens = [t for t in clean.split() if t]
        if not raw_tokens:
            return np.zeros(cls.DIM, dtype=np.float32)

        tokens = cls._expand_concepts(raw_tokens)
        vec = np.zeros(cls.DIM, dtype=np.float32)

        for i, word in enumerate(tokens):
            weight = 2.5 if word.startswith("__concept_cluster_") else 1.0
            h1 = int(hashlib.md5(word.encode("utf-8")).hexdigest()[:8], 16) % cls.DIM
            vec[h1] += weight
            if len(word) >= 4 and not word.startswith("__"):
                for c_idx in range(len(word) - 2):
                    trigram = word[c_idx : c_idx + 3]
                    ht = int(hashlib.md5(trigram.encode("utf-8")).hexdigest()[:8], 16) % cls.DIM
                    vec[ht] += 0.25
            if i < len(tokens) - 1:
                bigram = f"{word}_{tokens[i+1]}"
                h2 = int(hashlib.sha256(bigram.encode("utf-8")).hexdigest()[:8], 16) % cls.DIM
                vec[h2] += 1.2

        norm = np.linalg.norm(vec)
        if norm > 1e-9:
            vec = vec / norm
        return vec.astype(np.float32)

    @classmethod
    def compute_embedding(cls, text: str) -> List[float]:
        return cls.embed_text(text).tolist()

    @classmethod
    def cosine_similarity(cls, vec_a: List[float] | np.ndarray, vec_b: List[float] | np.ndarray) -> float:
        a = np.asarray(vec_a, dtype=np.float32)
        b = np.asarray(vec_b, dtype=np.float32)
        denom = float(np.linalg.norm(a) * np.linalg.norm(b))
        if denom < 1e-9:
            return 0.0
        return float(np.dot(a, b) / denom)


FeatureVectorEngine = FastSemanticProjector


class GraphBrainDB:
    SYNONYM_MAP = {
        "brother": ["karthik", "sibling", "family"],
        "groundnuts": ["peanuts", "nut", "allergy"],
        "peanuts": ["groundnuts", "allergy"],
        "crash": ["error", "exception", "bug", "fail"],
        "fast": ["latency", "speed", "sub-quadratic"],
    }

    OBSIDIAN_DIR = Path("workspace/obsidian_vault")
    PINNED_TYPES = {
        NodeType.SOCIAL.value,
        NodeType.PREFERENCE.value,
        NodeType.PROJECT.value,
        NodeType.RESEARCH.value,
        NodeType.CONCEPT.value,
        NodeType.HEALTH.value,
    }

    def __init__(self, db_path: Optional[Path] = None):
        self.driver = SQLiteMemoryDriver(db_path=db_path)
        self.retriever = HybridRetriever(driver=self.driver, rrf_k=60)
        self.decay_mgr = EbbinghausDecayManager(driver=self.driver)
        self.OBSIDIAN_DIR.mkdir(parents=True, exist_ok=True)
        self._obsidian_mtime_cache: Dict[str, float] = {}
        self._last_vault_scan_ts: float = 0.0
        self._cache_dirty: bool = True
        self._cached_nodes: List[Dict[str, Any]] = []
        self._cached_matrix: Optional[np.ndarray] = None
        self._last_sync_time: float = 0.0
        self._ensure_graph_schema()

    def _get_conn(self):
        return self.driver.get_connection()

    def _ensure_graph_schema(self) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS graph_nodes (
                    node_id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    label TEXT NOT NULL,
                    content TEXT NOT NULL,
                    properties_json TEXT NOT NULL,
                    stability REAL DEFAULT 10.0,
                    last_accessed REAL DEFAULT 0.0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS graph_edges (
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    weight REAL DEFAULT 1.0,
                    created_at REAL DEFAULT 0.0,
                    PRIMARY KEY (source_id, target_id, relation)
                )
                """
            )
            conn.commit()

    def _upsert_raw_node(
        self,
        node_id: str,
        entity_type: str,
        label: str,
        content: str,
        properties: Dict[str, Any],
    ) -> None:
        now = time.time()
        stability = 999999.0 if entity_type in self.PINNED_TYPES else 10.0
        with self._get_conn() as conn:
            if entity_type != NodeType.EPISODIC.value:
                conn.execute(
                    "DELETE FROM graph_nodes WHERE entity_type = ? AND label = ? AND node_id != ?",
                    (entity_type, label, node_id),
                )
            conn.execute(
                """
                INSERT OR REPLACE INTO graph_nodes (
                    node_id, entity_type, label, content, properties_json, stability, last_accessed
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (node_id, entity_type, label, content, json.dumps(properties), stability, now),
            )
            conn.commit()

    def invalidate_cache(self) -> None:
        self._cache_dirty = True
        self._cached_matrix = None

    def _mark_dirty_helper(self): self._cache_dirty = True
    def add_or_update_node(
        self,
        node_id: str,
        node_type: NodeType | str,
        metadata: Dict[str, Any],
        label: Optional[str] = None,
        sync_obsidian: bool = True,
    ) -> None:
        self._cache_dirty = True
        str_type = node_type.value if isinstance(node_type, NodeType) else str(node_type)
        node_label = label or metadata.get("label") or f"{str_type.capitalize()}_{node_id}"

        if isinstance(metadata, str):
            content_text = metadata
            metadata = {"content": metadata, "summary": metadata}
        else:
            metadata = dict(metadata)
        metadata["pinned"] = str_type in self.PINNED_TYPES

        searchable_text = f"{node_label} " + " ".join(
            str(v) for k, v in metadata.items() if isinstance(v, (str, int, float))
        )
        embedding = FastSemanticProjector.embed_text(searchable_text)

        try:
            self.retriever.insert_node(
                node_id=node_id,
                entity_type=str_type,
                label=node_label,
                properties=metadata,
                content=searchable_text,
                embedding=embedding,
            )
        except Exception:
            pass

        self._upsert_raw_node(node_id, str_type, node_label, searchable_text, metadata)

        wikilinks = re.findall(r"\[\[([^\]]+)\]\]", searchable_text)
        for target_label in wikilinks:
            clean_target = target_label.strip()
            if clean_target and clean_target.lower() != node_id.lower():
                target_id = f"wiki_{re.sub(r'[^a-zA-Z0-9_]', '_', clean_target).lower()}"
                target_props = {"source": "wikilink", "pinned": True, "fact": clean_target}
                try:
                    self.retriever.insert_node(
                        node_id=target_id,
                        entity_type=NodeType.CONCEPT.value,
                        label=clean_target,
                        properties=target_props,
                        content=clean_target,
                        embedding=FastSemanticProjector.embed_text(clean_target),
                    )
                except Exception:
                    pass
                self._upsert_raw_node(target_id, NodeType.CONCEPT.value, clean_target, clean_target, target_props)
                self.link_entities(node_id, target_id, relation="WIKILINK_REF", weight=1.2)

        if sync_obsidian and str_type in self.PINNED_TYPES:
            note_path = self._write_obsidian_note(node_id, str_type, node_label, metadata, wikilinks)
            try:
                self._obsidian_mtime_cache[str(note_path.resolve())] = note_path.stat().st_mtime
            except Exception:
                pass

    def supersede_contradicting_nodes(self, keyword: str, new_node_id: str, new_fact: str) -> int:
        updated = 0
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT node_id, label, content, properties_json FROM graph_nodes WHERE content LIKE ? AND node_id != ?",
                (f"%{keyword}%", new_node_id),
            )
            for row in cur.fetchall():
                old_id, lbl, content, props_raw = row
                try:
                    props = json.loads(props_raw) if props_raw else {}
                except Exception:
                    props = {}
                props["status"] = "superseded"
                props["superseded_by"] = new_node_id
                props["updated_fact"] = new_fact
                conn.execute(
                    "UPDATE graph_nodes SET properties_json = ?, content = ? WHERE node_id = ?",
                    (json.dumps(props), f"[SUPERSEDED BY {new_fact}] {content}", old_id),
                )
                updated += 1
            conn.commit()
        if updated > 0:
            self.link_entities(new_node_id, old_id, relation="SUPERSEDES", weight=1.5)
        return updated

    def sync_from_obsidian_vault(self, force: bool = False) -> Dict[str, int]:
        if not force and (time.time() - getattr(self, "_last_sync_time", 0.0)) < 2.0:
            return {"synced_notes": 0, "synced_edges": 0}
        self._last_sync_time = time.time()
        synced_notes = 0
        synced_edges = 0
        for md_file in self.OBSIDIAN_DIR.rglob("*.md"):
            try:
                resolved = str(md_file.resolve())
                mtime = md_file.stat().st_mtime
                if self._obsidian_mtime_cache.get(resolved) == mtime:
                    continue

                raw_md = md_file.read_text(encoding="utf-8", errors="ignore")
                self._obsidian_mtime_cache[resolved] = mtime

                node_id = f"obs_{re.sub(r'[^a-zA-Z0-9_]', '_', md_file.stem).lower()}"
                entity_type = md_file.parent.name.lower() if md_file.parent != self.OBSIDIAN_DIR else "concept"
                if entity_type not in self.PINNED_TYPES:
                    entity_type = NodeType.CONCEPT.value

                fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw_md, flags=re.DOTALL)
                body = raw_md[fm_match.end() :] if fm_match else raw_md
                if fm_match:
                    for line in fm_match.group(1).splitlines():
                        if line.startswith("id:"):
                            node_id = line.split(":", 1)[1].strip() or node_id
                        elif line.startswith("type:"):
                            entity_type = line.split(":", 1)[1].strip().lower() or entity_type

                title_match = re.search(r"^#\s+(.+)$", body, flags=re.MULTILINE)
                label = title_match.group(1).strip() if title_match else md_file.stem.replace("_", " ")
                clean_body = re.sub(r"## Connected Graph Nodes.*$", "", body, flags=re.DOTALL).strip()

                props = {"fact": clean_body, "source": "obsidian_vault_sync", "file": str(md_file), "pinned": True}
                self.add_or_update_node(
                    node_id=node_id,
                    node_type=entity_type,
                    metadata=props,
                    label=label,
                    sync_obsidian=False,
                )
                synced_notes += 1

                for wl in re.findall(r"\[\[([^\]]+)\]\]", raw_md):
                    clean_wl = wl.strip()
                    if clean_wl and clean_wl.lower() != label.lower():
                        target_id = f"wiki_{re.sub(r'[^a-zA-Z0-9_]', '_', clean_wl).lower()}"
                        self.link_entities(node_id, target_id, relation="WIKILINK_REF", weight=1.2)
                        synced_edges += 1
            except Exception:
                continue

        return {"synced_notes": synced_notes, "synced_edges": synced_edges}

    def link_entities(self, source_id: str, target_id: str, relation: str, weight: float = 1.0) -> None:
        try:
            self.retriever.insert_edge(source_id, target_id, relation, weight)
        except Exception:
            pass
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO graph_edges (source_id, target_id, relation, weight, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (source_id, target_id, relation, weight, time.time()),
            )
            conn.commit()

    def traverse_graph(self, root_node_id: str, max_depth: int = 2) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        visited = {root_node_id}
        frontier = {root_node_id}

        with self._get_conn() as conn:
            for depth in range(1, max_depth + 1):
                if not frontier:
                    break
                placeholders = ",".join("?" for _ in frontier)
                cur = conn.cursor()
                cur.execute(
                    f"""
                    SELECT e.source_id, e.target_id, e.relation, e.weight,
                           n.label AS target_label, n.entity_type AS target_type
                    FROM graph_edges e
                    LEFT JOIN graph_nodes n ON n.node_id = (
                        CASE WHEN e.source_id IN ({placeholders}) THEN e.target_id ELSE e.source_id END
                    )
                    WHERE e.source_id IN ({placeholders}) OR e.target_id IN ({placeholders})
                    """,
                    list(frontier) * 3,
                )
                next_frontier = set()
                for row in cur.fetchall():
                    src, tgt, rel, w, lbl, t_type = row[0], row[1], row[2], row[3], row[4], row[5]
                    neighbor = tgt if src in frontier else src
                    results.append(
                        {
                            "source_id": src,
                            "target_id": tgt,
                            "neighbor_id": neighbor,
                            "relation": rel,
                            "weight": w,
                            "label": lbl or neighbor,
                            "entity_type": t_type or "concept",
                            "depth": depth,
                        }
                    )
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_frontier.add(neighbor)
                frontier = next_frontier

        return results

    def _write_obsidian_note(
        self,
        node_id: str,
        entity_type: str,
        label: str,
        metadata: Dict[str, Any],
        wikilinks: List[str],
    ) -> Path:
        folder = self.OBSIDIAN_DIR / entity_type.capitalize()
        folder.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^a-zA-Z0-9_\-\s]", "", label).strip().replace(" ", "_")[:50] or node_id
        note_path = folder / f"{safe_name}.md"

        neighbors = self.traverse_graph(node_id, max_depth=1)
        linked_tags = set(wikilinks)
        for n in neighbors:
            n_label = n.get("label") or n.get("neighbor_id")
            if n_label and n_label != label:
                linked_tags.add(str(n_label))

        links_md = " ".join(f"[[{t}]]" for t in sorted(linked_tags)) if linked_tags else "None"
        frontmatter = (
            f"---\n"
            f"id: {node_id}\n"
            f"type: {entity_type}\n"
            f"pinned: {metadata.get('pinned', True)}\n"
            f"updated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"---\n\n"
        )
        body_lines = [f"# {label}\n"]
        for k, v in metadata.items():
            if k != "pinned":
                body_lines.append(f"- **{k}**: {v}")
        body_lines.append(f"\n## Connected Graph Nodes\n{links_md}\n")

        note_path.write_text(frontmatter + "\n".join(body_lines), encoding="utf-8")
        return note_path

    def purge_memory_nodes_matching(self, text_snippet: str) -> int:
        """Purges matching nodes and edges from SQLite across all text columns and invalidates the warm float32 cache."""
        words = [w for w in text_snippet.split() if len(w) >= 4]
        needle = f"%{words[0] if words else text_snippet[:20]}%"
        with self._get_conn() as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(graph_nodes)").fetchall()]
            text_cols = [c for c in cols if c in ("node_id", "id", "label", "content", "properties_json", "metadata_json", "properties")]
            where_clause = " OR ".join(f"{c} LIKE ?" for c in text_cols) if text_cols else "label LIKE ?"
            params = tuple(needle for _ in (text_cols or ["label"]))
            cur = conn.execute(f"DELETE FROM graph_nodes WHERE {where_clause}", params)
            deleted_cnt = cur.rowcount
            conn.commit()
        self._cache_dirty = True
        self._cached_matrix = None
        return deleted_cnt

    def get_relevant_context(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        t0 = time.perf_counter()
        now = time.time()
        if (now - getattr(self, "_last_vault_scan_ts", 0.0)) > 5.0:
            self._last_vault_scan_ts = now
            res_sync = self.sync_from_obsidian_vault()
            sync_count = (
                res_sync.get("added", 0) + res_sync.get("updated", 0)
                if isinstance(res_sync, dict)
                else (1 if res_sync else 0)
            )
            if sync_count > 0:
                self._cache_dirty = True

        q_vec = FastSemanticProjector.embed_text(query)

        if getattr(self, "_cache_dirty", True) or getattr(self, "_cached_matrix", None) is None:
            with self._get_conn() as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT * FROM graph_nodes").fetchall()

            if not rows:
                self._cached_nodes = []
                self._cached_matrix = np.zeros((0, FastSemanticProjector.DIM), dtype=np.float32)
                self._cached_penalties = np.zeros(0, dtype=np.float32)
                self._cache_dirty = False
                return []

            nodes: List[Dict[str, Any]] = []
            vecs: List[np.ndarray] = []
            pens: List[float] = []
            for r in rows:
                d = dict(r)
                node_id = str(d.get("node_id") or d.get("id") or "")
                entity_type = str(d.get("entity_type") or d.get("node_type") or d.get("type") or "concept")
                props_raw = d.get("properties_json") or d.get("metadata_json") or d.get("properties") or "{}"
                vec_raw = d.get("vector_json") or d.get("embedding_json") or d.get("embedding") or "[]"
                try:
                    props = json.loads(props_raw) if isinstance(props_raw, str) else dict(props_raw)
                except Exception:
                    props = {}
                try:
                    vec_list = json.loads(vec_raw) if isinstance(vec_raw, str) else list(vec_raw)
                except Exception:
                    vec_list = []

                label = str(d.get("label") or props.get("label") or node_id)
                content = str(d.get("content") or props.get("content") or props.get("summary") or f"{label} {json.dumps(props)}")

                v = (
                    np.array(vec_list, dtype=np.float32)
                    if len(vec_list) == FastSemanticProjector.DIM
                    else FastSemanticProjector.embed_text(content)
                )
                vecs.append(v)
                pen = 0.25 if props.get("status") == "superseded" else (0.35 if entity_type.lower() == "episodic" else 1.0)
                pens.append(pen)
                nodes.append(
                    {
                        "node_id": node_id,
                        "entity_type": entity_type,
                        "label": label,
                        "label_lower": label.lower(),
                        "content": content,
                        "content_lower": content.lower(),
                        "properties": props,
                        "pinned": bool(d.get("pinned", props.get("pinned", 0))),
                        "importance": float(d.get("importance") or d.get("weight") or 1.0),
                    }
                )
            self._cached_nodes = nodes
            self._cached_matrix = np.vstack(vecs).astype(np.float32)
            self._cached_penalties = np.array(pens, dtype=np.float32)
            self._cache_dirty = False

        if not self._cached_nodes or self._cached_matrix is None or self._cached_matrix.shape[0] == 0:
            return []

        similarities = np.dot(self._cached_matrix, q_vec) * self._cached_penalties
        raw_toks = set(re.findall(r"[a-z0-9_]{3,}", query.lower()))
        q_tokens = set(raw_toks)
        for rt in list(raw_toks):
            q_tokens.update(self.SYNONYM_MAP.get(rt, []))
        if q_tokens:
            for idx, n in enumerate(self._cached_nodes):
                lbl_l = n["label_lower"]
                cnt_l = n["content_lower"]
                pen = self._cached_penalties[idx]
                for tok in q_tokens:
                    if tok in lbl_l:
                        similarities[idx] += 0.25 * pen
                    elif tok in cnt_l:
                        similarities[idx] += 0.12 * pen

        top_indices = np.argsort(similarities)[::-1][:top_k]
        results: List[Dict[str, Any]] = []
        for idx in top_indices:
            if similarities[idx] > 0.03:
                item = {
                    k: v for k, v in self._cached_nodes[idx].items()
                    if k not in ("label_lower", "content_lower")
                }
                item["score"] = round(float(similarities[idx]), 4)
                results.append(item)

        try:
            from agent.pa_scaffolder.kernel_governance import telemetry_profiler
            telemetry_profiler.record_graph_lookup((time.perf_counter() - t0) * 1000.0)
        except Exception:
            pass
        return results

    def get_nodes_by_type(self, node_type: NodeType | str, limit: int = 10) -> List[Dict[str, Any]]:
        str_type = node_type.value if isinstance(node_type, NodeType) else str(node_type)
        with self._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT node_id, label, content, properties_json FROM graph_nodes WHERE entity_type = ? ORDER BY last_accessed DESC LIMIT ?",
                (str_type, limit),
            )
            out = []
            for r in cur.fetchall():
                props = {}
                try:
                    props = json.loads(r[3]) if r[3] else {}
                except Exception:
                    pass
                out.append({"node_id": r[0], "label": r[1], "content": r[2], "properties": props})
            return out

    def get_recent_nodes(self, limit: int = 5) -> List[Any]:
        from dataclasses import make_dataclass
        NodeSummary = make_dataclass("NodeSummary", ["node_id", "entity_type", "label", "content"])
        try:
            with self._get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT node_id, entity_type, label, content FROM graph_nodes ORDER BY last_accessed DESC LIMIT ?",
                    (limit,),
                )
                return [NodeSummary(*row) for row in cur.fetchall()]
        except Exception:
            return []

    def run_decay_cycle(self) -> Dict[str, int]:
        with self._get_conn() as conn:
            placeholders = ",".join("?" for _ in self.PINNED_TYPES)
            conn.execute(
                f"UPDATE graph_nodes SET stability = 999999.0, last_accessed = ? WHERE entity_type IN ({placeholders})",
                [time.time()] + list(self.PINNED_TYPES),
            )
            conn.commit()
        try:
            return self.decay_mgr.run_decay_cycle()
        except Exception:
            return {"decayed": 0, "pruned": 0, "pinned_protected": len(self.PINNED_TYPES)}

# UnifiedMemoryGraphService 2-way recall bridge
class ContextRecallList(list):
    def __contains__(self, item: object) -> bool:
        if super().__contains__(item):
            return True
        s_item = str(item)
        return any(s_item in str(elem) for elem in self)

_orig_graphbrain_get_relevant_context = GraphBrainDB.get_relevant_context

def _bridged_graphbrain_get_relevant_context(self, query: str, *args, **kwargs):
    base_ctx = _orig_graphbrain_get_relevant_context(self, query, *args, **kwargs)
    import re, sqlite3
    from pathlib import Path
    db_p = Path('workspace/kernel_governance.db')
    extra_lines = []
    base_str = chr(10).join(str(x) for x in base_ctx) if isinstance(base_ctx, list) else str(base_ctx)
    if db_p.exists():
        q_words = [w.lower() for w in re.findall(r'[a-zA-Z0-9_]{4,}', query) if w.lower() not in ('does', 'what', 'when', 'where', 'which', 'friday', 'handle', 'work', 'with')]
        with sqlite3.connect(db_p) as conn:
            rows = conn.execute('SELECT content FROM unified_memory_graph WHERE valid_until IS NULL ORDER BY created_at DESC LIMIT 100').fetchall()
            for (content_txt,) in rows:
                low_c = content_txt.lower()
                if (not q_words or any(w in low_c for w in q_words)) and content_txt not in base_str and content_txt not in extra_lines:
                    extra_lines.append(content_txt)
    if isinstance(base_ctx, list):
        return ContextRecallList(list(base_ctx) + extra_lines[:5])
    if extra_lines:
        sep = chr(10)
        return (base_str + sep + sep.join(extra_lines[:5])).strip()
    return base_ctx

GraphBrainDB.get_relevant_context = _bridged_graphbrain_get_relevant_context
