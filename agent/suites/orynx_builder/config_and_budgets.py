from __future__ import annotations
import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_PERFORMANCE_BUDGETS: Dict[str, Any] = {
    "version": "1.0.0",
    "description": "Performance budgets that can only ratchet down, never up",
    "lastUpdated": "2026-11-05T00:00:00Z",
    "budgets": {
        "core-journeys": {
            "app-launch-interactive": {"budget": 550.0, "unit": "ms", "description": "Time from page load to interactive (p75)"},
            "composer-typeable": {"budget": 100.0, "unit": "ms", "description": "Time from composer mount to typeable"},
            "message-first-token": {"budget": 300.0, "unit": "ms", "description": "Time from send to first AI token"},
            "project-load": {"budget": 730.0, "unit": "ms", "description": "Time to load existing project"},
            "webcontainer-boot": {"budget": 2000.0, "unit": "ms", "description": "WebContainer / Sandbox boot time"},
        },
        "component-performance": {
            "code-block-render": {"budget": 100.0, "unit": "ms", "description": "Syntax highlighting for typical code block"},
            "message-render": {"budget": 50.0, "unit": "ms", "description": "Single message render time"},
            "terminal-init": {"budget": 150.0, "unit": "ms", "description": "XTerm / PTY terminal initialization"},
        },
        "streaming-performance": {
            "frame-budget-60fps": {"budget": 16.67, "unit": "ms", "description": "Frame budget for 60fps streaming"},
            "frame-budget-120fps": {"budget": 8.33, "unit": "ms", "description": "Frame budget for 120fps streaming"},
            "max-dropped-frames": {"budget": 5.0, "unit": "percent", "description": "Maximum percentage of dropped frames"},
        },
        "bundle-size": {
            "main-bundle": {"budget": 500.0, "unit": "kb", "description": "Main JavaScript bundle size (gzipped)"},
            "vendor-bundle": {"budget": 300.0, "unit": "kb", "description": "Vendor bundle size (gzipped)"},
            "webcontainer-api": {"budget": 200.0, "unit": "kb", "description": "WebContainer API bundle size"},
        },
        "web-vitals": {
            "cls": {"budget": 0.1, "unit": "score", "description": "Cumulative Layout Shift"},
            "lcp": {"budget": 2500.0, "unit": "ms", "description": "Largest Contentful Paint"},
            "fid": {"budget": 100.0, "unit": "ms", "description": "First Input Delay"},
            "inp": {"budget": 200.0, "unit": "ms", "description": "Interaction to Next Paint"},
        },
    },
    "rules": {
        "ratchet": "Budgets can only decrease, never increase",
        "tolerance_pct": 2.0,
        "enforcement": "CI fails if any budget is exceeded by more than tolerance",
    },
}

DEFAULT_LIGHTHOUSE_RC: Dict[str, Any] = {
    "ci": {
        "collect": {
            "url": ["http://localhost:5173/"],
            "startServerCommand": "pnpm run start",
            "numberOfRuns": 3,
        },
        "assert": {
            "assertions": {
                "categories:performance": ["warn", {"minScore": 0.8}],
                "categories:accessibility": ["warn", {"minScore": 0.9}],
                "categories:best-practices": ["warn", {"minScore": 0.8}],
                "categories:seo": ["warn", {"minScore": 0.8}],
            }
        },
        "upload": {"target": "temporary-public-storage"},
    }
}

DEFAULT_DEPCHECK_RC: Dict[str, Any] = {
    "ignoreMatches": [
        "@types/*", "eslint-*", "prettier*", "husky", "rimraf",
        "vitest", "vite", "typescript", "wrangler", "electron*",
    ],
    "ignoreDirs": ["dist", "build", "node_modules", ".git"],
    "skipMissing": False,
    "ignorePatterns": ["*.d.ts", "*.test.ts", "*.test.tsx", "*.spec.ts", "*.spec.tsx"],
}

DEFAULT_PRETTIER_RC: Dict[str, Any] = {
    "printWidth": 120,
    "singleQuote": True,
    "useTabs": False,
    "tabWidth": 2,
    "semi": True,
    "bracketSpacing": True,
}

EDITORCONFIG_TEXT = """root = true

[*]
indent_style = space
end_of_line = lf
charset = utf-8
trim_trailing_whitespace = true
insert_final_newline = true
max_line_length = 120
indent_size = 2

[*.md]
trim_trailing_whitespace = false
"""

GITATTRIBUTES_TEXT = """* text=auto eol=lf
*.bat text eol=crlf
*.cmd text eol=crlf
*.ps1 text eol=crlf
*.psm1 text eol=crlf
*.sh text eol=lf
*.bash text eol=lf
pnpm-lock.yaml text eol=lf
*.png binary
*.jpg binary
*.jpeg binary
*.gif binary
*.ico binary
*.webp binary
*.woff binary
*.woff2 binary
*.ttf binary
*.eot binary
*.pdf binary
*.zip binary
*.gz binary
*.wasm binary
"""

DOCKERIGNORE_TEXT = """.git
.github/
.husky/
CONTRIBUTING.md
LICENSE
README.md
.env
*.local
*.example
**/*.log
**/node_modules
**/dist
**/build
**/.cache
logs
dist-ssr
.DS_Store
"""


class PerformanceBudgetRatchetGate:
    """Enforces bolt.diy ratcheting performance and Web Vitals budgets."""

    def __init__(self, db_path: str = "workspace/kernel_governance.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.budgets = json.loads(json.dumps(DEFAULT_PERFORMANCE_BUDGETS))
        self.tolerance_multiplier = 1.02  # 2% measurement noise tolerance
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orynx_performance_budgets (
                    category TEXT,
                    metric_key TEXT,
                    budget_value REAL,
                    unit TEXT,
                    updated_at REAL,
                    PRIMARY KEY (category, metric_key)
                )
                """
            )
            for cat, metrics in self.budgets["budgets"].items():
                for m_key, m_obj in metrics.items():
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO orynx_performance_budgets
                        (category, metric_key, budget_value, unit, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (cat, m_key, float(m_obj["budget"]), m_obj["unit"], time.time()),
                    )

    def evaluate_metrics(self, observed_metrics: Dict[str, float], auto_ratchet: bool = True) -> Dict[str, Any]:
        violations: List[Dict[str, Any]] = []
        ratcheted_down: List[Dict[str, Any]] = []
        checked = 0

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT category, metric_key, budget_value, unit FROM orynx_performance_budgets"
            ).fetchall()
            budget_map = {r[1]: (r[0], float(r[2]), r[3]) for r in rows}

            for metric_key, observed_val in observed_metrics.items():
                if metric_key not in budget_map:
                    continue
                checked += 1
                cat, current_budget, unit = budget_map[metric_key]
                max_allowed = current_budget * self.tolerance_multiplier
                if observed_val > max_allowed:
                    violations.append({
                        "category": cat,
                        "metric": metric_key,
                        "observed": round(observed_val, 3),
                        "budget": current_budget,
                        "max_with_tolerance": round(max_allowed, 3),
                        "unit": unit,
                    })
                elif auto_ratchet and observed_val < current_budget * 0.90 and observed_val > 0:
                    # Ratchet rule: budgets can only decrease, never increase
                    new_budget = round(observed_val * 1.05, 3)
                    if new_budget < current_budget:
                        conn.execute(
                            """
                            UPDATE orynx_performance_budgets
                            SET budget_value = ?, updated_at = ?
                            WHERE category = ? AND metric_key = ?
                            """,
                            (new_budget, time.time(), cat, metric_key),
                        )
                        ratcheted_down.append({
                            "metric": metric_key,
                            "old_budget": current_budget,
                            "new_budget": new_budget,
                            "unit": unit,
                        })

        return {
            "passed": len(violations) == 0,
            "metrics_checked": checked,
            "violations": violations,
            "ratcheted_down": ratcheted_down,
        }

    def write_project_hygiene_configs(self, project_dir: Path) -> List[str]:
        project_dir.mkdir(parents=True, exist_ok=True)
        written: List[str] = []
        files_map = {
            ".performance-budgets.json": json.dumps(self.budgets, indent=2),
            ".lighthouserc.json": json.dumps(DEFAULT_LIGHTHOUSE_RC, indent=2),
            ".depcheckrc.json": json.dumps(DEFAULT_DEPCHECK_RC, indent=2),
            ".prettierrc": json.dumps(DEFAULT_PRETTIER_RC, indent=2),
            ".editorconfig": EDITORCONFIG_TEXT,
            ".gitattributes": GITATTRIBUTES_TEXT,
            ".dockerignore": DOCKERIGNORE_TEXT,
        }
        for fname, content in files_map.items():
            fpath = project_dir / fname
            fpath.write_text(content, encoding="utf-8")
            written.append(str(fpath))
        return written
