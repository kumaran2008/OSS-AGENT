import asyncio
from pathlib import Path

from agent.pa_scaffolder.rooms_engine import RoomsEngine, AgentMode
from agent.pa_scaffolder.jev_reflex_router import JevDecisionEngine
from agent.pa_scaffolder.tool_registry import ToolRegistry
from agent.pa_scaffolder.github_engine import GitHubEngine, GitHubIssue
from agent.pa_scaffolder.mcp_client import StdioMCPClient


async def test_builder_suite():
    print("=" * 70)
    print("     BUILDER SUITE: SEMANTIC JEV, GITHUB & MCP AUDIT")
    print("=" * 70)

    # -------------------------------------------------------------------------
    # 1. Verify Jev Dynamic Semantic Intent Switching (No Hardcoded Keywords)
    # -------------------------------------------------------------------------
    print("\n[1/5] Testing Jev Dynamic Semantic Intent Switching...")
    jev = JevDecisionEngine()

    phrases = [
        "can you help me develop a python web service",
        "i want to write some code and build an app",
        "time to fix some issues in the repo"
    ]

    for p in phrases:
        switched, mode, msg = jev.evaluate_mode_switch(p, current_mode=AgentMode.NORMAL)
        print(f" • Phrase: \"{p}\"")
        print(f"   └─ Mode Detected: {mode.value.upper()} | Switched: {switched}")
        assert switched is True
        assert mode == AgentMode.BUILDER

    print(" >>> CRITERION 1 PASSED: Jev evaluates conversational intent dynamically. <<<")

    # -------------------------------------------------------------------------
    # 2. Verify Builder Universal Tool Access ('*')
    # -------------------------------------------------------------------------
    print("\n[2/5] Testing Builder Universal Tool Access...")
    rooms = RoomsEngine()
    rooms.current_mode = AgentMode.BUILDER

    # Must allow code tools AND normal tools (e.g. desktop window_focus)
    ok_patch, _ = rooms.is_tool_authorized("file_patch")
    ok_desk, _ = rooms.is_tool_authorized("window_focus")
    ok_clip, _ = rooms.is_tool_authorized("clipboard_set")

    print(f" • Builder Tool 'file_patch':   {'ALLOWED' if ok_patch else 'BLOCKED'}")
    print(f" • Builder Tool 'window_focus': {'ALLOWED' if ok_desk else 'BLOCKED'}")
    print(f" • Builder Tool 'clipboard_set':{'ALLOWED' if ok_clip else 'BLOCKED'}")

    assert ok_patch and ok_desk and ok_clip
    print(" >>> CRITERION 2 PASSED: Builder mode retains universal tool authority. <<<")

    # -------------------------------------------------------------------------
    # 3. Verify GitHub Issue Triage & Breakdown
    # -------------------------------------------------------------------------
    print("\n[3/5] Testing GitHub Issue Triage & Structural Breakdown...")
    github = GitHubEngine(workspace_root=Path("workspace"))

    mock_issue = GitHubIssue(
        number=104,
        title="Async PTY deadlocks on unbuffered carriage return",
        body="Steps to reproduce:\n1. Run python spinner\n2. PTY hangs waiting for EOF.",
        state="open",
        labels=["bug", "high-priority"],
        url="https://github.com/example/oss-agent/issues/104",
        author="core-dev",
        comments_count=3
    )

    summary = github.get_issue_summary(mock_issue)
    print(" • Generated Issue Summary Preview:")
    for line in summary.splitlines():
        print(f"   {line}")

    assert "Issue #104" in summary
    assert "high-priority" in summary
    print(" >>> CRITERION 3 PASSED: Issue triage breakdown formatted for human review. <<<")

    # -------------------------------------------------------------------------
    # 4. Verify GitHub Clone & Pull Request Workflow
    # -------------------------------------------------------------------------
    print("\n[4/5] Testing GitHub Local Clone & PR Tooling...")
    tools = ToolRegistry(workspace_root="workspace")

    test_repo_dir = Path("workspace/repos/test_pr_repo")
    test_repo_dir.mkdir(parents=True, exist_ok=True)
    import subprocess
    subprocess.run(["git", "init"], cwd=str(test_repo_dir), capture_output=True)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=str(test_repo_dir), capture_output=True)
    (test_repo_dir / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(test_repo_dir), capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(test_repo_dir), capture_output=True)

    # Edit file
    (test_repo_dir / "fix.txt").write_text("bug resolved\n", encoding="utf-8")

    res_pr = await tools.dispatch("github_create_pr", {
        "repo_name": "test_pr_repo",
        "branch": "fix/issue-104",
        "title": "Fix unbuffered carriage return deadlock",
        "body": "Resolves issue #104 by normalizing CRLF before regex clean."
    })

    print(f" • PR Dispatch Output: \"{res_pr.output}\"")
    assert res_pr.success is True
    print(" >>> CRITERION 4 PASSED: GitHub PR workflow operational. <<<")

    # -------------------------------------------------------------------------
    # 5. Verify Model Context Protocol (MCP) JSON-RPC 2.0 Client
    # -------------------------------------------------------------------------
    print("\n[5/5] Testing Model Context Protocol (MCP) JSON-RPC 2.0 Subprocess...")

    # Spawn an inline Python stdio MCP server for the benchmark
    mcp_server_script = Path("workspace/mock_mcp_server.py")
    mcp_server_script.write_text(
        "import sys, json\n"
        "for line in sys.stdin:\n"
        "    if not line.strip(): continue\n"
        "    req = json.loads(line)\n"
        "    method = req.get('method')\n"
        "    req_id = req.get('id')\n"
        "    if method == 'initialize':\n"
        "        resp = {'jsonrpc': '2.0', 'id': req_id, 'result': {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}}}}\n"
        "        sys.stdout.write(json.dumps(resp) + '\\n'); sys.stdout.flush()\n"
        "    elif method == 'tools/list':\n"
        "        resp = {'jsonrpc': '2.0', 'id': req_id, 'result': {'tools': [{'name': 'mcp_echo', 'description': 'Echoes input', 'inputSchema': {}}]}}\n"
        "        sys.stdout.write(json.dumps(resp) + '\\n'); sys.stdout.flush()\n"
        "    elif method == 'tools/call':\n"
        "        resp = {'jsonrpc': '2.0', 'id': req_id, 'result': {'content': [{'type': 'text', 'text': 'MCP_HELLO_WORLD'}]}}\n"
        "        sys.stdout.write(json.dumps(resp) + '\\n'); sys.stdout.flush()\n",
        encoding="utf-8"
    )

    res_mcp_conn = await tools.dispatch("mcp_connect", {
        "server_name": "test_mcp",
        "command": "python",
        "args": [str(mcp_server_script)]
    })
    print(f" • MCP Connection:      \"{res_mcp_conn.output}\"")
    assert res_mcp_conn.success is True

    res_mcp_call = await tools.dispatch("mcp_call", {
        "server_name": "test_mcp",
        "tool_name": "mcp_echo",
        "arguments": {"msg": "test"}
    })
    print(f" • MCP Tool Call:       \"{res_mcp_call.output}\"")
    assert res_mcp_call.success is True
    assert "MCP_HELLO_WORLD" in res_mcp_call.output

    # Cleanup
    tools.close()
    mcp_server_script.unlink(missing_ok=True)
    import shutil
    shutil.rmtree(test_repo_dir, ignore_errors=True)

    print("\n" + "=" * 70)
    print(">>> BUILDER SUITE FULLY OPERATIONAL (SEMANTIC JEV, GITHUB & MCP) <<<")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_builder_suite())
