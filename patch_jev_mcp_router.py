from pathlib import Path

target = Path("agent/pa_scaffolder/jev_reflex_router.py")
code = target.read_text(encoding="utf-8")

# Helper to check if MCP keyword match is present in evaluate_async
mcp_eval_block = """        # -------------------------------------------------------------
        # DYNAMIC ON-DEMAND MCP INTERCEPTOR (Jev Instant Domain Match)
        # -------------------------------------------------------------
        mcp_keywords = {
            "postgres": ["postgres", "sql", "database query", "db table"],
            "brave_search": ["web search", "search internet", "browse web", "google search"],
            "github": ["pull request", "github issue", "repo issues", "merge pr"]
        }
        for server_id, kws in mcp_keywords.items():
            if any(kw in text for kw in kws):
                return {
                    "intent": "DYNAMIC_MCP_TASK",
                    "confidence": 0.96,
                    "urgency_tier": "REFLEX_LOCAL",
                    "execution_backend": "DYNAMIC_MCP_ON_DEMAND",
                    "target_server": server_id
                }
"""

anchor = "        # 2. Local OS / Reflex Execution"
if "DYNAMIC_MCP_TASK" not in code and anchor in code:
    code = code.replace(anchor, mcp_eval_block + "\n" + anchor)
    target.write_text(code, encoding="utf-8")
    print("[✓] Injected Dynamic MCP evaluation into Jev Reflex Router.")
else:
    print("[i] Dynamic MCP routing already configured.")
