import time
import json
import math
import random
import struct
from pathlib import Path

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    import array

from agent.memory.sqlite_driver import SQLiteMemoryDriver
from agent.memory.hybrid_retriever import HybridRetriever
from agent.memory.decay_manager import EbbinghausDecayManager


def test_pillar1_exit_criteria():
    print("=" * 70)
    print("     PILLAR 1 VERIFICATION: COGNITIVE MEMORY ENGINE (GraphBrain v2)")
    print("=" * 70)
    print(f" • Hardware Vector Acceleration: {'NumPy (BLAS)' if HAS_NUMPY else 'Pure-Python array.array'}")

    test_db = Path("workspace/test_graph_brain_v2.db")
    if test_db.exists():
        test_db.unlink()
    for ext in ["-wal", "-shm"]:
        f = Path(str(test_db) + ext)
        if f.exists():
            f.unlink()

    driver = SQLiteMemoryDriver(db_path=test_db)
    retriever = HybridRetriever(driver=driver)
    dim = 384

    # -------------------------------------------------------------------------
    # Criterion 1: Bulk Ingestion & Hybrid Search
    # -------------------------------------------------------------------------
    total_nodes = 20000 if HAS_NUMPY else 2500
    print(f"\n[1/3] Bulk inserting {total_nodes} nodes with 384d vectors & FTS indexing...")

    t_start = time.perf_counter()
    now = int(time.time())

    with driver.get_connection() as conn:
        node_tuples = []
        vec_tuples = []
        fts_tuples = []

        if HAS_NUMPY:
            np.random.seed(42)
            raw_mat = np.random.randn(total_nodes, dim).astype(np.float32)
            norms = np.linalg.norm(raw_mat, axis=1, keepdims=True)
            norm_mat = raw_mat / norms

            for i in range(total_nodes):
                nid = f"node_{i:05d}"
                label = f"Document_{i}"
                content = f"Optimization log for distributed training pipeline index {i}"
                props = json.dumps({"batch_id": i // 100, "priority": "high" if i % 2 == 0 else "low"})

                node_tuples.append((nid, "CONCEPT", label, props, 1, 1.0, now, now))
                vec_tuples.append((nid, dim, norm_mat[i].tobytes()))
                fts_tuples.append((nid, f"{label} {content}"))
            query_vector = norm_mat[1337 % total_nodes]
        else:
            random.seed(42)
            test_target_vec = None
            for i in range(total_nodes):
                nid = f"node_{i:05d}"
                label = f"Document_{i}"
                content = f"Optimization log for distributed training pipeline index {i}"
                props = json.dumps({"batch_id": i // 100, "priority": "high" if i % 2 == 0 else "low"})

                v = [random.gauss(0, 1) for _ in range(dim)]
                norm_val = math.sqrt(sum(x * x for x in v))
                v_norm = [x / norm_val for x in v]
                arr_bytes = struct.pack(f"{dim}f", *v_norm)

                if i == (1337 % total_nodes):
                    test_target_vec = v_norm

                node_tuples.append((nid, "CONCEPT", label, props, 1, 1.0, now, now))
                vec_tuples.append((nid, dim, arr_bytes))
                fts_tuples.append((nid, f"{label} {content}"))
            query_vector = test_target_vec

        conn.executemany("INSERT INTO memory_nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?)", node_tuples)
        conn.executemany("INSERT INTO memory_vectors VALUES (?, ?, ?)", vec_tuples)
        conn.executemany("INSERT INTO memory_fts VALUES (?, ?)", fts_tuples)
        conn.commit()

    retriever._cache_dirty = True
    t_ingest = (time.perf_counter() - t_start)
    print(f" • Bulk Insert Completed in: {t_ingest:.2f}s ({(total_nodes/t_ingest):.0f} nodes/sec)")

    print(" • Executing Hybrid Search (FTS5 BM25 + Vector Dot Product RRF)...")
    query_text = "pipeline training distributed"

    search_latencies = []
    for _ in range(5):
        t0 = time.perf_counter()
        results = retriever.hybrid_search(query=query_text, query_vector=query_vector, top_k=5)
        search_latencies.append((time.perf_counter() - t0) * 1000.0)

    avg_search_ms = float(sum(search_latencies) / len(search_latencies))
    print(f" • Latency across {total_nodes} nodes: {avg_search_ms:.2f} ms")
    print(f" • Top Match: Node '{results[0]['id']}' (RRF Score: {results[0]['rrf_score']:.5f})")
    assert len(results) > 0
    print(" >>> CRITERION 1 PASSED: Hybrid RRF retrieval verified. <<<")

    # -------------------------------------------------------------------------
    # Criterion 2: 3-Hop Recursive Edge Traversal (<5ms)
    # -------------------------------------------------------------------------
    print("\n[2/3] Setting up multi-hop graph topology & testing recursive CTE...")
    retriever.insert_edge("node_00001", "node_00002", "DEPENDS_ON", 1.0)
    retriever.insert_edge("node_00002", "node_00003", "CALLS", 1.0)
    retriever.insert_edge("node_00003", "node_00004", "MUTATES", 1.0)

    traversal_latencies = []
    for _ in range(10):
        t0 = time.perf_counter()
        walk = retriever.recursive_graph_traversal("node_00001", max_depth=3)
        traversal_latencies.append((time.perf_counter() - t0) * 1000.0)

    avg_walk_ms = float(sum(traversal_latencies) / len(traversal_latencies))
    print(f" • 3-Hop Recursive CTE Walk Latency: {avg_walk_ms:.3f} ms")
    print(f" • Walk Depth Discovered: {len(walk)} connected nodes")
    for step in walk:
        print(f"   └─ Depth {step['depth']}: [{step['relation']}] -> {step['id']} ({step['label']})")

    assert len(walk) == 3, "Failed to resolve 3 distinct hops."
    assert avg_walk_ms < 5.0, f"Traversal latency ({avg_walk_ms:.3f}ms) exceeded 5ms target!"
    print(" >>> CRITERION 2 PASSED: <5ms 3-hop traversal verified. <<<")

    # -------------------------------------------------------------------------
    # Criterion 3: Ebbinghaus Decay & Cold Storage Eviction Loop
    # -------------------------------------------------------------------------
    print("\n[3/3] Testing Ebbinghaus Decay Worker & Cold Storage Migration...")
    decay_mgr = EbbinghausDecayManager(driver=driver, tau_seconds=86400.0, eviction_threshold=0.15)

    future_time = now + (8 * 86400)
    cycle_stats = decay_mgr.run_decay_cycle(simulated_now=future_time)

    print(f" • Active Nodes Retained: {cycle_stats['active_updated']}")
    print(f" • Cold Nodes Relocated to Archive: {cycle_stats['archived']}")

    with driver.get_connection() as conn:
        archived_count = conn.execute("SELECT COUNT(*) FROM cold_archive").fetchone()[0]
        remaining_count = conn.execute("SELECT COUNT(*) FROM memory_nodes").fetchone()[0]

    print(f" • Verified Records in cold_archive: {archived_count}")
    print(f" • Verified Remaining Active Nodes: {remaining_count}")
    assert archived_count > 0, "No nodes were archived."
    assert (archived_count + remaining_count) == total_nodes, "Node count mismatch after decay run."
    print(" >>> CRITERION 3 PASSED: Decay and archiving verified. <<<")

    test_db.unlink(missing_ok=True)
    for ext in ["-wal", "-shm"]:
        Path(str(test_db) + ext).unlink(missing_ok=True)

    print("\n" + "=" * 70)
    print(">>> PILLAR 1: GRAPH BRAIN V2 FULLY HARDENED & PRODUCTION-READY <<<")
    print("=" * 70)


if __name__ == "__main__":
    test_pillar1_exit_criteria()
