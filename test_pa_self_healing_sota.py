import asyncio
import shutil
from pathlib import Path

from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine


async def test_pa_self_healing():
    print("=" * 70)
    print("     TESTER AGENT SELF-HEALING & META-REPAIR BENCHMARK")
    print("=" * 70)

    test_ws = Path("workspace/test_self_heal_sandbox").resolve()
    test_ws.mkdir(parents=True, exist_ok=True)

    # Create a source file with 60 lines of code
    sample_lines = [f"# Code line {i}: value = {i * 2}\n" for i in range(1, 65)]
    (test_ws / "source.py").write_text("".join(sample_lines), encoding="utf-8")

    harness = UnifiedAsyncEngine()
    harness.tools.workspace_root = test_ws

    print("\n[1/3] Setting Up Intentional Bug in Internal PA Method...")
    target_tool_file = Path("agent/pa_scaffolder/tool_registry.py")
    orig_registry_code = target_tool_file.read_text(encoding="utf-8")

    try:
        # Inject an intentional IndexError bug in file_read tool logic
        buggy_anchor = "lines = fpath.read_text(encoding=\"utf-8\", errors=\"replace\").splitlines(keepends=True)"
        injected_bug = (
            "lines = fpath.read_text(encoding=\"utf-8\", errors=\"replace\").splitlines(keepends=True)\n"
            "                if int(args.get('line_count', 0)) > 20:\n"
            "                    raise IndexError('PA Internal Buffer Limit Exceeded in file_read')\n"
        )

        assert buggy_anchor in orig_registry_code, "Anchor not found in tool_registry.py"
        buggy_registry_code = orig_registry_code.replace(buggy_anchor, injected_bug, 1)
        target_tool_file.write_text(buggy_registry_code, encoding="utf-8")

        # Hot-reload buggy registry and rebind harness.tools
        ok, mod, _ = harness.self_healer.hot_reload_module("agent/pa_scaffolder/tool_registry.py")
        assert ok is True
        harness.tools = mod.ToolRegistry(workspace_root=test_ws)

        print(" • Injected intentional bug into 'agent/pa_scaffolder/tool_registry.py'.")
        print(" • Normal PA execution will now fail on line_count > 20 requests.")

        # ---------------------------------------------------------------------
        # 2. Simulate User Query ("Copy lines 3 to 48")
        # ---------------------------------------------------------------------
        print("\n[2/3] Simulating User Query: 'Copy from line 3 to 48'...")
        user_args = {"file_path": "source.py", "start_line": 3, "line_count": 45}

        # Synthesizer removes the artificial exception and restores clean slicing
        def test_patch_synthesizer(rel_path: str, faulty_code: str, error_trace: str) -> str:
            print(f" • [Tester Synthesizer] Analyzing Fault in '{rel_path}'...")
            print(f"   └─ Fault Trace: {error_trace.splitlines()[-1]}")
            fixed_code = faulty_code.replace(
                "if int(args.get('line_count', 0)) > 20:\n                    raise IndexError('PA Internal Buffer Limit Exceeded in file_read')\n",
                ""
            )
            return fixed_code

        t0 = asyncio.get_event_loop().time()
        result = await harness.dispatch_tool_with_self_healing(
            tool_name="file_read",
            tool_args=user_args,
            patch_synthesizer=test_patch_synthesizer
        )
        elapsed = asyncio.get_event_loop().time() - t0

        # ---------------------------------------------------------------------
        # 3. Verify Self-Healing, Hot-Reload & Task Completion
        # ---------------------------------------------------------------------
        print("\n[3/3] Inspecting Self-Healing Results & Resumed Task Output...")
        print(f" • Task Success:          {result.get('success')}")
        print(f" • Self-Healed:           {result.get('repaired')}")
        print(f" • Diagnostic Log:        \"{result.get('explanation')}\"")
        print(f" • Execution Time:        {elapsed:.3f}s")

        assert result.get("success") is True, "Task failed to complete after self-healing!"
        assert result.get("repaired") is True, "Tester failed to execute self-repair!"
        assert "Code line 3" in result.get("output"), "Output missing requested start line!"
        assert "Code line 47" in result.get("output"), "Output missing requested range!"

    finally:
        # Restore clean tool_registry.py on disk
        target_tool_file.write_text(orig_registry_code, encoding="utf-8")
        harness.self_healer.hot_reload_module("agent/pa_scaffolder/tool_registry.py")

    # Cleanup
    harness.tools.close()
    shutil.rmtree(test_ws, ignore_errors=True)

    print("\n" + "=" * 70)
    print(">>> TESTER AGENT SELF-HEALING PIPELINE 100% OPERATIONAL <<<")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_pa_self_healing())
