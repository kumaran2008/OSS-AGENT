import json
import time
import math
import sqlite3
from typing import List, Dict, Any, Optional, Tuple, Union

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    import array

from agent.memory.sqlite_driver import SQLiteMemoryDriver


class HybridRetriever:
    """
    High-Performance Associative Memory Engine.
    - Uses NumPy for vectorized matrix dot products when available.
    - Falls back to built-in array.array('f') with zero dependencies.
    """

    def __init__(self, driver: Optional[SQLiteMemoryDriver] = None, rrf_k: int = 60):
        self.driver = driver or SQLiteMemoryDriver()
        self.rrf_k = rrf_k
        self._cached_ids: List[str] = []
        self._cached_matrix: Any = None
        self._cache_dirty = True
        self._sync_vector_cache()

    def _sync_vector_cache(self) -> None:
        """Loads embeddings into memory."""
        with self.driver.get_connection() as conn:
            cursor = conn.execute("SELECT node_id, embedding FROM memory_vectors")
            rows = cursor.fetchall()

        if not rows:
            self._cached_ids = []
            self._cached_matrix = None
            self._cache_dirty = False
            return

        ids = []
        if HAS_NUMPY:
            vectors = []
            for node_id, blob in rows:
                arr = np.frombuffer(blob, dtype=np.float32)
                ids.append(node_id)
                vectors.append(arr)

            matrix = np.array(vectors, dtype=np.float32)
            norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-9
            self._cached_matrix = matrix / norms
        else:
            import array
            vectors = []
            for node_id, blob in rows:
                arr = array.array('f')
                arr.frombytes(blob)
                norm = math.sqrt(sum(x * x for x in arr)) + 1e-9
                vectors.append([x / norm for x in arr])
                ids.append(node_id)
            self._cached_matrix = vectors

        self._cached_ids = ids
        self._cache_dirty = False

    def insert_node(
        self,
        node_id: str,
        entity_type: str,
        label: str,
        properties: Dict[str, Any],
        content: str,
        embedding: Union[Any, List[float]]
    ) -> None:
        now = int(time.time())

        # Support both numpy array and Python list/array.array
        if hasattr(embedding, "astype") and hasattr(embedding, "tobytes"):
            emb_bytes = embedding.astype(np.float32).tobytes()
            dim = len(embedding)
        else:
            import array
            arr = array.array('f', embedding)
            emb_bytes = arr.tobytes()
            dim = len(arr)

        with self.driver.get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_nodes
                (id, entity_type, label, properties, access_count, decay_score, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, 1.0, ?, ?)
                """,
                (node_id, entity_type, label, json.dumps(properties), now, now)
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_vectors (node_id, dim, embedding)
                VALUES (?, ?, ?)
                """,
                (node_id, dim, emb_bytes)
            )
            conn.execute("DELETE FROM memory_fts WHERE node_id = ?", (node_id,))
            conn.execute(
                "INSERT INTO memory_fts (node_id, content) VALUES (?, ?)",
                (node_id, f"{label} {content}")
            )
            conn.commit()

        self._cache_dirty = True

    def insert_edge(self, source_id: str, target_id: str, relation: str, weight: float = 1.0) -> None:
        now = int(time.time())
        with self.driver.get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO memory_edges (source_id, target_id, relation, weight, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (source_id, target_id, relation, weight, now)
            )
            conn.commit()

    def hybrid_search(
        self,
        query: str,
        query_vector: Union[Any, List[float]],
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        if self._cache_dirty:
            self._sync_vector_cache()

        lexical_ranks: Dict[str, int] = {}
        with self.driver.get_connection() as conn:
            tokens = [f'"{tok}"' for tok in query.replace("'", " ").split() if tok.isalnum()]
            if tokens:
                fts_query = " OR ".join(tokens)
                try:
                    cursor = conn.execute(
                        """
                        SELECT node_id, rank
                        FROM memory_fts
                        WHERE memory_fts MATCH ?
                        ORDER BY rank
                        LIMIT 60
                        """,
                        (fts_query,)
                    )
                    for idx, (node_id, _) in enumerate(cursor.fetchall()):
                        lexical_ranks[node_id] = idx + 1
                except sqlite3.OperationalError:
                    pass

        # 2. Dense Vector Dot Product
        dense_ranks: Dict[str, int] = {}
        if self._cached_matrix is not None and len(self._cached_matrix) > 0:
            if HAS_NUMPY:
                q_arr = np.array(query_vector, dtype=np.float32)
                q_norm = q_arr / (np.linalg.norm(q_arr) + 1e-9)
                sim_scores = np.dot(self._cached_matrix, q_norm)
                top_indices = np.argsort(sim_scores)[::-1][:60]
                for idx, arr_idx in enumerate(top_indices):
                    node_id = self._cached_ids[arr_idx]
                    dense_ranks[node_id] = idx + 1
            else:
                # Pure-Python dot product
                q_norm_val = math.sqrt(sum(x * x for x in query_vector)) + 1e-9
                q_norm = [x / q_norm_val for x in query_vector]
                scores = []
                for idx, c_vec in enumerate(self._cached_matrix):
                    dot = sum(a * b for a, b in zip(c_vec, q_norm))
                    scores.append((idx, dot))
                scores.sort(key=lambda x: x[1], reverse=True)
                for rank_idx, (arr_idx, _) in enumerate(scores[:60]):
                    node_id = self._cached_ids[arr_idx]
                    dense_ranks[node_id] = rank_idx + 1

        # 3. Reciprocal Rank Fusion
        candidate_ids = set(lexical_ranks.keys()).union(dense_ranks.keys())
        scored_candidates: List[Tuple[str, float]] = []

        for node_id in candidate_ids:
            r_lex = lexical_ranks.get(node_id, 1000)
            r_vec = dense_ranks.get(node_id, 1000)
            rrf_score = (1.0 / (self.rrf_k + r_lex)) + (1.0 / (self.rrf_k + r_vec))
            scored_candidates.append((node_id, rrf_score))

        scored_candidates.sort(key=lambda x: x[1], reverse=True)
        top_candidates = scored_candidates[:top_k]

        # 4. Hydrate Node Metadata & Increment Access
        results = []
        now = int(time.time())
        with self.driver.get_connection() as conn:
            for node_id, score in top_candidates:
                cursor = conn.execute(
                    """
                    SELECT id, entity_type, label, properties, access_count, decay_score
                    FROM memory_nodes WHERE id = ?
                    """,
                    (node_id,)
                )
                row = cursor.fetchone()
                if row:
                    results.append({
                        "id": row[0],
                        "type": row[1],
                        "label": row[2],
                        "properties": json.loads(row[3]),
                        "access_count": row[4],
                        "decay": row[5],
                        "rrf_score": score
                    })
                    conn.execute(
                        """
                        UPDATE memory_nodes
                        SET access_count = access_count + 1, updated_at = ?
                        WHERE id = ?
                        """,
                        (now, node_id)
                    )
            conn.commit()

        return results

    def recursive_graph_traversal(self, root_node_id: str, max_depth: int = 3) -> List[Dict[str, Any]]:
        query = """
        WITH RECURSIVE GraphWalk(source_id, target_id, relation, depth) AS (
            SELECT source_id, target_id, relation, 1
            FROM memory_edges
            WHERE source_id = ?
            UNION ALL
            SELECT e.source_id, e.target_id, e.relation, gw.depth + 1
            FROM memory_edges e
            JOIN GraphWalk gw ON e.source_id = gw.target_id
            WHERE gw.depth < ?
        )
        SELECT DISTINCT n.id, n.label, n.entity_type, gw.relation, gw.depth
        FROM GraphWalk gw
        JOIN memory_nodes n ON n.id = gw.target_id
        ORDER BY gw.depth ASC;
        """
        with self.driver.get_connection() as conn:
            cursor = conn.execute(query, (root_node_id, max_depth))
            rows = cursor.fetchall()

        return [
            {"id": r[0], "label": r[1], "type": r[2], "relation": r[3], "depth": r[4]}
            for r in rows
        ]
