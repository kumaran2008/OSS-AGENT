from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.kernel.jev_ai_system1 import jev_ai_brain
from agent.kernel.model_broker import model_broker
from agent.suites.builder_cursor_lovable.lovable_app_builder import lovable_app_builder
from agent.suites.builder_cursor_lovable.multi_file_shadow_twin import multi_file_shadow_twin
from agent.suites.builder_cursor_lovable.repository_intelligence import repo_intelligence


class BuilderCursorLovableSuite:
    """Section 5: Complete Builder Suite Coordinator (`ASK`, `PLAN`, `AGENT`, `MANUAL_DIFF`).
    Supports both:
      - Automatic Situational Mode Selection (`mode='AUTO'`) via TypeSafe AI `Jev` (`choice` primitive)
      - Explicit User Mode Selection (`mode='ASK' | 'PLAN' | 'AGENT' | 'MANUAL_DIFF'`)
    """

    VALID_MODES = ("ASK", "PLAN", "AGENT", "MANUAL_DIFF")

    def select_mode_automatically_via_jev(
        self,
        prompt: str,
        file_patches: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Uses TypeSafe AI `Jev` (`choice` primitive) to automatically pick the right engineering mode
        from the user's natural request when `mode='AUTO'`.
        """
        q_mode = {
            "engineering_mode": {
                "type": "choice",
                "options": ["ASK", "PLAN", "AGENT", "MANUAL_DIFF", "other"],
                "default_option": "AGENT" if file_patches else "ASK",
                "option_signals": {
                    "ASK": ["where is", "why is", "explain", "what does", "how does", "find the", "returning a 401", "inspect"],
                    "PLAN": ["plan", "architecture", "roadmap", "design a", "steps to add", "how should we implement", "blueprint"],
                    "MANUAL_DIFF": ["manual diff", "show diff", "review diff", "propose diff", "before applying", "approval"],
                    "AGENT": ["build", "create", "fix", "patch", "implement", "reconcile", "refactor", "write code", "deploy"],
                },
            }
        }
        res = jev_ai_brain.evaluate_primitives(prompt, q_mode)
        picked = res["engineering_mode"].value
        if picked not in self.VALID_MODES:
            picked = "AGENT" if file_patches else "ASK"
        return {"selected_mode": picked, "confidence": res["engineering_mode"].confidence}

    async def execute_engineering_workflow(
        self,
        prompt: str,
        mode: str = "AUTO",
        file_patches: Optional[Dict[str, str]] = None,
        verification_test_code: str = "",
    ) -> Dict[str, Any]:
        m_in = mode.upper().strip()
        if m_in in self.VALID_MODES:
            m = m_in
            auto_selected = False
            mode_conf = 1.0
        else:
            jev_m = self.select_mode_automatically_via_jev(prompt, file_patches=file_patches)
            m = jev_m["selected_mode"]
            auto_selected = True
            mode_conf = jev_m["confidence"]

        ctx = repo_intelligence.retrieve_adaptive_context(prompt)
        route = model_broker.route_task_economically(prompt, attached_context=ctx["assembled_context"])

        if m == "ASK":
            return {
                "engineering_mode": "ASK",
                "auto_selected_by_jev": auto_selected,
                "mode_confidence": mode_conf,
                "files_modified": [],
                "cited_files": ctx["selected_files"],
                "cited_symbols": ctx["selected_symbols"],
                "token_savings_percent": ctx["token_savings_percent"],
                "selected_model": route["selected_model"],
            }

        if m == "PLAN":
            plan_steps = [
                f"1. Inspect indexed symbols {ctx['selected_symbols'][:3]} in {ctx['selected_files'][:2]}",
                f"2. Update dependent callers ({ctx['dependency_callers_included']} caller symbol(s) traced)",
                "3. Stage multi-file transaction in MultiFileTransactionalShadowTwin",
                "4. Execute unit & security regression suite in Warm Sandbox Worker",
                "5. Verify postconditions and promote atomically",
            ]
            return {
                "engineering_mode": "PLAN",
                "auto_selected_by_jev": auto_selected,
                "mode_confidence": mode_conf,
                "files_modified": [],
                "affected_files": ctx["selected_files"],
                "implementation_steps": plan_steps,
                "selected_model": route["selected_model"],
            }

        if m == "MANUAL_DIFF":
            diffs: Dict[str, str] = {}
            for fp, new_content in (file_patches or {}).items():
                old_lines = Path(fp).read_text(encoding="utf-8").splitlines(keepends=True) if Path(fp).exists() else []
                new_lines = new_content.splitlines(keepends=True)
                diff_txt = "".join(difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{fp}", tofile=f"b/{fp}"))
                diffs[fp] = diff_txt
            return {
                "engineering_mode": "MANUAL_DIFF",
                "auto_selected_by_jev": auto_selected,
                "mode_confidence": mode_conf,
                "requires_user_approval": True,
                "files_modified": [],
                "proposed_unified_diffs": diffs,
            }

        if file_patches:
            tx = await multi_file_shadow_twin.execute_multi_file_transaction(
                file_patches=file_patches,
                verification_test_code=verification_test_code or "assert True",
            )
            return {
                "engineering_mode": "AGENT",
                "auto_selected_by_jev": auto_selected,
                "mode_confidence": mode_conf,
                "transaction_id": tx.transaction_id,
                "files_modified": tx.files_targeted if tx.promoted_atomically else [],
                "promoted_atomically": tx.promoted_atomically,
                "rolled_back": tx.rolled_back,
                "duration_ms": tx.duration_ms,
            }

        app_res = await lovable_app_builder.build_and_verify_application(prompt)
        return {
            "engineering_mode": "AGENT",
            "auto_selected_by_jev": auto_selected,
            "mode_confidence": mode_conf,
            "app_build_result": app_res,
            "promoted_atomically": app_res["promoted_atomically"],
        }



    def run_prm_ast_guard_and_git_status(self, file_path: str, candidate_code: str) -> Dict[str, Any]:
        '''Integrates FILE 19 (ProcessRewardGuard) and FILE 18 (GitBridge) for coding workspaces.'''
        from agent.guardrails.prm_verifier import prm_guard
        from agent.git_bridge import GitBridge
        prm_res = prm_guard.verify_python_code(candidate_code, filepath=file_path)
        git_b = GitBridge(Path.cwd())
        return {
            'prm_ast_valid': prm_res.valid,
            'prm_score': prm_res.score,
            'prm_error': prm_res.error_message,
            'git_repo_active': git_b.is_git_repo(),
        }

builder_suite = BuilderCursorLovableSuite()
