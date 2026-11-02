from pathlib import Path

target = Path("agent/pa_scaffolder/rooms_engine.py")
code = target.read_text(encoding="utf-8")

# 1. Add import
if "from agent.pa_scaffolder.workspace_orchestrator import WorkspaceOrchestrator" not in code:
    code = "from agent.pa_scaffolder.workspace_orchestrator import WorkspaceOrchestrator\n" + code

# 2. Add orchestrator to BuilderAutonomousSupervisor __init__
old_supervisor_init = "self.did_stash_changes: bool = False"
new_supervisor_init = "self.did_stash_changes: bool = False\n        self.orchestrator = WorkspaceOrchestrator(self.workspace)"

if old_supervisor_init in code and "self.orchestrator =" not in code:
    code = code.replace(old_supervisor_init, new_supervisor_init)

# 3. Add orchestrator to RoomsEngine __init__
old_engine_init = "self.builder_supervisor = BuilderAutonomousSupervisor(self.workspace)"
new_engine_init = "self.builder_supervisor = BuilderAutonomousSupervisor(self.workspace)\n        self.orchestrator = self.builder_supervisor.orchestrator"

if old_engine_init in code and "self.orchestrator = self.builder_supervisor.orchestrator" not in code:
    code = code.replace(old_engine_init, new_engine_init)

# 4. Enhance patch application inside execute_autonomous_task to handle both single and multi-file patches
old_patch_apply = """            # Invoke Patch Solver (AST Patcher / LLM function)
            patch_result = patch_solver_fn(task_description, pruned_err)
            if not patch_result:
                break

            target_rel_file, new_content = patch_result
            target_path = self.workspace / target_rel_file
            target_path.write_text(new_content, encoding="utf-8")"""

new_patch_apply = """            # Invoke Patch Solver (Supports single-file tuple or multi-file dict/list)
            patch_result = patch_solver_fn(task_description, pruned_err)
            if not patch_result:
                break

            # Normalize to manifest dict: {file_path: content}
            manifest: Dict[str, str] = {}
            if isinstance(patch_result, dict):
                manifest = patch_result
            elif isinstance(patch_result, list):
                manifest = {item[0]: item[1] for item in patch_result}
            elif isinstance(patch_result, tuple):
                manifest = {patch_result[0]: patch_result[1]}

            # Apply via atomic multi-file orchestrator (with syntax pre-flight)
            ok_patch, patch_msg, touched = self.orchestrator.atomic_multi_file_patch(manifest)
            if not ok_patch:
                # Syntax error caught in-memory in <5ms! Feed directly back to planner
                current_error = patch_msg
                continue

            # Focus active editor on primary modified file
            if touched:
                self.orchestrator.open_in_editor(touched[0], line_number=1)"""

if old_patch_apply in code:
    code = code.replace(old_patch_apply, new_patch_apply)

target.write_text(code, encoding="utf-8")
print("[✓] Integrated WorkspaceOrchestrator and Multi-File Atomic Transactions into rooms_engine.py")
