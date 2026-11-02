from pathlib import Path

target = Path("agent/pa_scaffolder/self_repair_engine.py")
code = target.read_text(encoding="utf-8")

new_trace_method = """    def trace_fault_to_source(self, exc: Exception) -> Optional[Tuple[str, str, int]]:
        \"\"\"
        Extracts the internal PA file, function, and line number where the crash occurred.
        Skips harness dispatch wrappers to find the real faulting tool.
        \"\"\"
        tb = traceback.extract_tb(exc.__traceback__)
        for frame in reversed(tb):
            fpath = Path(frame.filename).resolve()
            try:
                rel = fpath.relative_to(self.pa_root)
                rel_str = str(rel).replace("\\\\", "/")
                # Skip harness dispatch wrapper frames
                if "engine_harness.py" in rel_str and frame.name in ["dispatch_tool_with_self_healing", "_retry_dispatcher"]:
                    continue
                if rel_str.startswith("agent/") or rel_str.startswith("pa_scaffolder/"):
                    return rel_str, frame.name, frame.lineno
            except ValueError:
                continue

        # Fallback to tool_registry.py if traceback was truncated
        fallback_path = self.pa_root / "agent" / "pa_scaffolder" / "tool_registry.py"
        if fallback_path.exists():
            return "agent/pa_scaffolder/tool_registry.py", "dispatch", 1
        return None"""

old_trace_marker = "    def trace_fault_to_source(self, exc: Exception) -> Optional[Tuple[str, str, int]]:"
end_marker = "    def hot_reload_module(self, rel_path: str) -> Tuple[bool, Any, str]:"

start_idx = code.find(old_trace_marker)
end_idx = code.find(end_marker)

if start_idx != -1 and end_idx != -1:
    code = code[:start_idx] + new_trace_method + "\n\n" + code[end_idx:]
    target.write_text(code, encoding="utf-8")
    print("[✓] Upgraded trace_fault_to_source in self_repair_engine.py.")
