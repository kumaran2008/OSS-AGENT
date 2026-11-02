import json
import time
import math
from typing import Dict, Any
from agent.memory.sqlite_driver import SQLiteMemoryDriver


class EbbinghausDecayManager:
    """
    Maintains memory lifecycle by applying the Ebbinghaus forgetting curve.
    Relocates cold nodes (decay < 0.15) to cold_archive to prevent memory bloat.
    """

    def __init__(
        self,
        driver: SQLiteMemoryDriver,
        tau_seconds: float = 86400.0,       # 24-hour half-life base
        eviction_threshold: float = 0.15
    ):
        self.driver = driver
        self.tau = tau_seconds
        self.threshold = eviction_threshold

    def calculate_decay(self, current_decay: float, elapsed_sec: float, access_count: int) -> float:
        """
        Calculates retained memory strength.
        Repetition (access_count) slows the rate of decay.
        """
        retention_factor = self.tau * (1.0 + math.log(1.0 + access_count))
        decay_val = current_decay * math.exp(-elapsed_sec / retention_factor)
        return max(0.0, min(1.0, decay_val))

    def run_decay_cycle(self, simulated_now: int = 0) -> Dict[str, int]:
        """
        Updates decay scores across nodes and archives degraded entities.
        """
        now = simulated_now if simulated_now > 0 else int(time.time())
        updated_count = 0
        archived_count = 0

        with self.driver.get_connection() as conn:
            cursor = conn.execute(
                "SELECT id, entity_type, label, properties, access_count, decay_score, updated_at FROM memory_nodes"
            )
            nodes = cursor.fetchall()

            for node_id, e_type, label, props_json, access_cnt, decay_score, updated_at in nodes:
                elapsed = max(0, now - updated_at)
                new_decay = self.calculate_decay(decay_score, elapsed, access_cnt)

                if new_decay < self.threshold:
                    # Move to cold_archive
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO cold_archive (id, entity_type, label, properties, final_decay_score, archived_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (node_id, e_type, label, props_json, new_decay, now)
                    )
                    # Remove from active nodes (cascades to vectors and edges)
                    conn.execute("DELETE FROM memory_nodes WHERE id = ?", (node_id,))
                    conn.execute("DELETE FROM memory_fts WHERE node_id = ?", (node_id,))
                    archived_count += 1
                else:
                    conn.execute(
                        "UPDATE memory_nodes SET decay_score = ? WHERE id = ?",
                        (new_decay, node_id)
                    )
                    updated_count += 1

            conn.commit()

        return {"active_updated": updated_count, "archived": archived_count}
