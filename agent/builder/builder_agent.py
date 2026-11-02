import json
from pathlib import Path
from typing import Any, Dict, List
from tools.dashboard import dashboard


class BuilderAgent:
    """
    The General Contractor & Lead Architect.
    Deconstructs user instructions and GitHub issue contexts into clear
    architectural blueprints, designs file layouts, and allocates discrete
    work packages to specialized Masons (Frontend, Backend, DB, Config).
    """

    def __init__(self, router=None):
        self.router = router

    def plan_application_architecture(self, prompt: str, target_dir: Path) -> Dict[str, Any]:
        """
        Synthesizes user requests into concrete project layout trees and work orders.
        """
        dashboard.emit("STATE_CHANGE", {"state": "THINKING"})
        dashboard.emit("LOG_STREAM", {"message": "Builder Agent outlining project topology..."})

        if not self.router:
            return {
                "project_name": target_dir.name,
                "framework": "fullstack-vanilla",
                "tasks": [
                    {"mason": "BACKEND_MASON", "file": "app.py", "action": "CREATE", "objective": "Main API server"},
                    {"mason": "FRONTEND_MASON", "file": "index.html", "action": "CREATE", "objective": "Frontend UI"},
                ],
            }

        blueprint_prompt = (
            f"You are the Lead Architect / Builder Agent.\n"
            f"The user wants to construct the following application:\n'{prompt}'\n\n"
            "Return a strictly valid JSON object matching this schema:\n"
            "{\n"
            '  "project_name": "short-app-name",\n'
            '  "stack": "tech stack description",\n'
            '  "files": [\n'
            '    {"file_path": "path/relative/to/root.ext", "mason": "FRONTEND_MASON"|"BACKEND_MASON"|"CONFIG_MASON", "description": "detailed purpose"}\n'
            "  ],\n"
            '  "execution_order": ["step 1", "step 2"]\n'
            "}\n"
            "Return ONLY raw JSON, no markdown backticks."
        )

        try:
            raw_blueprint, _ = self.router.complete_with_fallback(
                "planning",
                [
                    {"role": "system", "content": "You are a master software architect. Always output strictly valid JSON."},
                    {"role": "user", "content": blueprint_prompt},
                ],
            )
            clean_json = raw_blueprint.strip("` \n")
            if clean_json.startswith("json\n"):
                clean_json = clean_json[5:]
            blueprint = json.loads(clean_json)
        except Exception:
            blueprint = {
                "project_name": target_dir.name,
                "stack": "Standard Full-Stack",
                "files": [
                    {"file_path": "server.py", "mason": "BACKEND_MASON", "description": "Backend API Server"},
                    {"file_path": "static/index.html", "mason": "FRONTEND_MASON", "description": "Interactive Web View"},
                ],
                "execution_order": ["Setup backend server", "Build interface view"],
            }

        for f in blueprint.get("files", []):
            f_path = f.get("file_path", "")
            if f_path:
                dashboard.emit("AST_NODE_DISCOVERED", {
                    "id": f_path,
                    "label": Path(f_path).name,
                    "mason": f.get("mason", "BACKEND_MASON")
                })

        return blueprint
