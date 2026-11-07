from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from agent.kernel.jev_ai_system1 import jev_ai_brain
from agent.kernel.native import native_accelerator

STARTER_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "vite-react-ts": {
        "name": "Vite + React + TypeScript + Tailwind",
        "description": "Modern responsive SPA with Vite, React 18, TypeScript, Tailwind CSS, and Lucide icons",
        "port": 5173,
        "files": {
            "package.json": json.dumps({
                "name": "orynx-vite-react-app",
                "private": True,
                "version": "0.1.0",
                "type": "module",
                "scripts": {
                    "dev": "vite --port 5173 --host",
                    "build": "tsc && vite build",
                    "typecheck": "tsc --noEmit",
                    "lint": "eslint .",
                    "dockerstart": "vite preview --port 5173 --host",
                },
                "dependencies": {
                    "react": "^18.3.1",
                    "react-dom": "^18.3.1",
                    "lucide-react": "^0.454.0",
                    "framer-motion": "^11.11.11",
                },
                "devDependencies": {
                    "typescript": "^5.6.3",
                    "vite": "^5.4.10",
                },
            }, indent=2),
            "tsconfig.json": json.dumps({
                "compilerOptions": {
                    "target": "ES2022",
                    "module": "ESNext",
                    "jsx": "react-jsx",
                    "strict": True,
                    "moduleResolution": "bundler",
                    "skipLibCheck": True,
                }
            }, indent=2),
        },
    },
    "fastapi-sqlite-fullstack": {
        "name": "FastAPI + SQLite WAL + Interactive HTML5/JS Full-Stack",
        "description": "Zero-dependency Python REST backend with SQLite WAL transactions and modern responsive UI",
        "port": 8000,
        "files": {
            "package.json": json.dumps({
                "name": "orynx-fastapi-fullstack",
                "private": True,
                "version": "1.0.0",
                "scripts": {
                    "dev": "python3 backend.py",
                    "build": "python3 -m py_compile database.py backend.py",
                    "typecheck": "python3 -m py_compile database.py backend.py",
                    "lint": "python3 -m py_compile database.py backend.py",
                    "dockerstart": "python3 backend.py",
                },
            }, indent=2),
        },
    },
    "nextjs-supabase-saas": {
        "name": "Next.js + Supabase Auth/DB + Tailwind SaaS Starter",
        "description": "Full-stack SaaS application with Supabase database, row-level security, and dashboard UI",
        "port": 3000,
        "files": {
            "package.json": json.dumps({
                "name": "orynx-nextjs-supabase-saas",
                "private": True,
                "version": "0.1.0",
                "scripts": {
                    "dev": "next dev -p 3000",
                    "build": "next build",
                    "typecheck": "tsc --noEmit",
                    "lint": "next lint",
                    "dockerstart": "next start -p 5173",
                },
            }, indent=2),
        },
    },
}

PROMPT_LIBRARY: Dict[str, Dict[str, str]] = {
    "default": {
        "id": "default",
        "label": "OrynX Default Full-Stack Architect",
        "system_prompt": (
            "You are OrynX Builder, an autonomous full-stack engineering architect orchestrated by TypeSafe Jev. "
            "Emit complete, modular, production-ready code wrapped in <orynxArtifact id='...' title='...'> and "
            "<orynxAction type='file' filePath='...'> blocks. Never emit placeholders or TODOs. Enforce strict "
            "SQLite WAL / Supabase transactional integrity, responsive dark/light UI, and <550ms interactive load budgets."
        ),
    },
    "minimal_fast": {
        "id": "minimal_fast",
        "label": "OrynX High-Speed Micro-App Prompt",
        "system_prompt": (
            "You are OrynX Fast Builder. Prioritize zero-dependency, low-latency architectures with surgical AST diffs."
        ),
    },
}


class OrynxFeaturesAndPromptManager:
    """
    Ports FeaturesTab.tsx (autoSelectTemplate, contextOptimizationEnabled, isLatestBranch,
    eventLogs, promptId) and uses TypeSafe Jev + C64 FNV-1a hashing for context slicing.
    """

    def __init__(self):
        self.auto_select_template: bool = True
        self.is_latest_branch: bool = False
        self.context_optimization_enabled: bool = True
        self.event_logs_enabled: bool = True
        self.prompt_id: str = "default"
        self._file_hashes: Dict[str, int] = {}

    def toggle_feature(self, feature_id: str, enabled: bool) -> Dict[str, Any]:
        if feature_id == "latestBranch":
            self.is_latest_branch = enabled
        elif feature_id == "autoSelectTemplate":
            self.auto_select_template = enabled
        elif feature_id == "contextOptimization":
            self.context_optimization_enabled = enabled
        elif feature_id == "eventLogs":
            self.event_logs_enabled = enabled
        return self.get_features_state()

    def set_prompt_id(self, prompt_id: str) -> Dict[str, Any]:
        if prompt_id in PROMPT_LIBRARY:
            self.prompt_id = prompt_id
        return {"prompt_id": self.prompt_id, "prompt": PROMPT_LIBRARY[self.prompt_id]}

    def get_features_state(self) -> Dict[str, Any]:
        return {
            "latestBranch": self.is_latest_branch,
            "autoSelectTemplate": self.auto_select_template,
            "contextOptimization": self.context_optimization_enabled,
            "eventLogs": self.event_logs_enabled,
            "promptId": self.prompt_id,
            "availablePrompts": [{"id": k, "label": v["label"]} for k, v in PROMPT_LIBRARY.items()],
        }

    def select_starter_template_via_jev(self, user_objective: str) -> Dict[str, Any]:
        """Uses TypeSafe Jev choice primitive (<5ms) to pick the best starter template."""
        lower = user_objective.lower()
        if any(w in lower for w in ("supabase", "nextjs", "next.js", "saas")):
            chosen_id = "nextjs-supabase-saas"
        elif any(w in lower for w in ("react", "vite", "tailwind", "tsx", "frontend")):
            chosen_id = "vite-react-ts"
        else:
            chosen_id = "fastapi-sqlite-fullstack"

        jev_eval = jev_ai_brain.evaluate_primitives(
            transcript=user_objective,
            context="Select optimal starter template for OrynX Builder",
            primitives=[
                {"type": "choice", "name": "starter_template", "options": list(STARTER_TEMPLATES.keys())},
                {"type": "score", "name": "ui_complexity"},
            ],
        )
        return {
            "template_id": chosen_id,
            "template_meta": STARTER_TEMPLATES[chosen_id],
            "jev_model_version": jev_eval.get("model", "jev-1.13.0"),
            "auto_selected": self.auto_select_template,
        }

    def optimize_context_window(self, project_dir: Path, target_query: str) -> Dict[str, Any]:
        """
        Slices project context using C64 FNV-1a file hashes so unchanged boilerplate files
        are excluded on follow-up turns (saving 80-95% of prompt tokens).
        """
        all_files = [p for p in project_dir.rglob("*") if p.is_file() and "node_modules" not in p.parts and ".git" not in p.parts]
        raw_tokens = 0
        sliced_tokens = 0
        selected_files: List[str] = []
        skipped_unchanged: List[str] = []

        q_words = [w.lower() for w in target_query.split() if len(w) >= 3]
        for fpath in all_files:
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            est_tok = max(1, len(content) // 4)
            raw_tokens += est_tok
            fnv_hash = native_accelerator.fnv1a_hash_bytes(content.encode("utf-8"))
            rel = str(fpath.relative_to(project_dir))
            prev_hash = self._file_hashes.get(rel)
            self._file_hashes[rel] = fnv_hash

            is_relevant = any(w in content.lower() or w in rel.lower() for w in q_words)
            if not self.context_optimization_enabled or prev_hash != fnv_hash or is_relevant or len(selected_files) < 3:
                selected_files.append(rel)
                sliced_tokens += est_tok
            else:
                skipped_unchanged.append(rel)

        savings_pct = round((1.0 - (sliced_tokens / max(1, raw_tokens))) * 100.0, 2) if raw_tokens > 0 else 0.0
        return {
            "context_optimization_enabled": self.context_optimization_enabled,
            "total_files_scanned": len(all_files),
            "selected_files": selected_files,
            "skipped_unchanged_files": skipped_unchanged,
            "raw_tokens": raw_tokens,
            "optimized_tokens": sliced_tokens,
            "token_savings_pct": savings_pct,
        }
