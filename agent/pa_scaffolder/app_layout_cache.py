import json
import sqlite3
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Tuple, Optional, List


@dataclass
class NormalizedCoord:
    x_norm: float  # 0.0 to 1.0
    y_norm: float  # 0.0 to 1.0


class AppLayoutCache:
    """
    Zero-latency coordinate resolver.
    Pre-populates known app templates and extracts dynamic bounds
    from the OS Accessibility Tree without calling an LLM.
    """
    # Pre-existing standard coordinate maps for common apps
    DEFAULT_LAYOUT_CATALOG: Dict[str, Dict[str, Tuple[float, float]]] = {
        "com.google.android.youtube": {
            "search_button": (0.88, 0.06),
            "cast_button": (0.76, 0.06),
            "explore_tab": (0.10, 0.95),
            "subscriptions_tab": (0.70, 0.95),
            "library_tab": (0.90, 0.95),
            "first_video": (0.50, 0.28)
        },
        "com.gamestar.perfectpiano": {
            "key_c4": (0.07, 0.82),
            "key_d4": (0.14, 0.82),
            "key_e4": (0.21, 0.82),
            "key_f4": (0.28, 0.82),
            "key_g4": (0.35, 0.82),
            "key_a4": (0.42, 0.82),
            "key_b4": (0.49, 0.82),
            "key_c5": (0.56, 0.82),
            "record_button": (0.50, 0.08),
            "song_menu": (0.92, 0.08)
        },
        "com.instagram.android": {
            "home_tab": (0.10, 0.95),
            "search_tab": (0.30, 0.95),
            "create_post": (0.50, 0.95),
            "reels_tab": (0.70, 0.95),
            "profile_tab": (0.90, 0.95),
            "direct_messages": (0.92, 0.05)
        }
    }

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or (Path.home() / ".personal_agent" / "memory" / "brain.db")
        self._init_cache_table()
        self._seed_default_layouts()

    def _init_cache_table(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS app_coordinate_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                package_name TEXT,
                element_identifier TEXT,
                x_norm REAL,
                y_norm REAL,
                verified_hits INTEGER DEFAULT 1,
                last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(package_name, element_identifier)
            )
        """)
        conn.commit()
        conn.close()

    def _seed_default_layouts(self):
        """Seeds standard pre-existing app maps into local SQLite."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        for pkg, elements in self.DEFAULT_LAYOUT_CATALOG.items():
            for elem, (xn, yn) in elements.items():
                cur.execute("""
                    INSERT OR IGNORE INTO app_coordinate_cache 
                    (package_name, element_identifier, x_norm, y_norm)
                    VALUES (?, ?, ?, ?)
                """, (pkg, elem.lower(), xn, yn))
        conn.commit()
        conn.close()

    def get_coordinates(
        self,
        package_name: str,
        element_key: str,
        screen_w: int,
        screen_h: int
    ) -> Optional[Tuple[int, int]]:
        """Tier 1: Instant lookup from pre-existing layout cache (<1ms)."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT x_norm, y_norm FROM app_coordinate_cache 
            WHERE package_name = ? AND element_identifier = ?
        """, (package_name, element_key.lower()))
        row = cur.fetchone()
        conn.close()

        if row:
            xn, yn = row
            return int(xn * screen_w), int(yn * screen_h)
        return None

    def resolve_from_os_hierarchy(
        self,
        package_name: str,
        target_text_or_id: str,
        screen_w: int,
        screen_h: int
    ) -> Optional[Tuple[int, int]]:
        """Tier 2: Inspects OS Accessibility tree (~150ms)."""
        dump_path = Path("/data/local/tmp/uidump.xml")
        try:
            subprocess.run(["uiautomator", "dump", str(dump_path)], capture_output=True, timeout=3)
            if not dump_path.exists():
                return None

            tree = ET.parse(str(dump_path))
            root = tree.getroot()

            target = target_text_or_id.lower()
            for node in root.iter("node"):
                text = node.attrib.get("text", "").lower()
                desc = node.attrib.get("content-desc", "").lower()
                res_id = node.attrib.get("resource-id", "").lower()

                if target in text or target in desc or target in res_id:
                    bounds_str = node.attrib.get("bounds", "")
                    bounds = bounds_str.replace("][", ",").replace("[", "").replace("]", "").split(",")
                    if len(bounds) == 4:
                        l, t, r, b = map(int, bounds)
                        cx, cy = (l + r) // 2, (t + b) // 2
                        self.save_coordinate(package_name, target_text_or_id, cx / screen_w, cy / screen_h)
                        return cx, cy
        except Exception:
            pass
        return None

    def save_coordinate(self, package_name: str, element_key: str, x_norm: float, y_norm: float):
        """Persists newly discovered coordinates to avoid future lookups."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO app_coordinate_cache 
            (package_name, element_identifier, x_norm, y_norm, verified_hits)
            VALUES (?, ?, ?, ?, COALESCE((SELECT verified_hits FROM app_coordinate_cache WHERE package_name=? AND element_identifier=?)+1, 1))
        """, (package_name, element_key.lower(), x_norm, y_norm, package_name, element_key.lower()))
        conn.commit()
        conn.close()
