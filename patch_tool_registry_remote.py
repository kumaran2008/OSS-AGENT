from pathlib import Path

target = Path("agent/pa_scaffolder/tool_registry.py")
code = target.read_text(encoding="utf-8")

# 1. Add RemoteComputeBridge import
if "from agent.pa_scaffolder.remote_compute_bridge import RemoteComputeBridge" not in code:
    code = "from agent.pa_scaffolder.remote_compute_bridge import RemoteComputeBridge\n" + code

# 2. Add remote_bridge to ToolRegistry.__init__
old_init = "self.model_switcher = UniversalModelSwitcher()"
new_init = old_init + "\n        self.remote_bridge = RemoteComputeBridge(self.workspace_root)"

if old_init in code and "self.remote_bridge =" not in code:
    code = code.replace(old_init, new_init)

# 3. Add dispatch handlers
old_dispatch = '            if tool_name == "literature_ingest_pdf":'
new_dispatch = """            if tool_name == "remote_cloud_sweep":
                script_path = args.get("script_path", "")
                metric = args.get("metric_key", "perplexity")
                seeds = args.get("seeds", [42, 1337, 2026])
                baseline = args.get("baseline_target")
                gpu = args.get("gpu_type", "A10G")

                target = self.workspace_root / script_path
                content = target.read_text(encoding="utf-8") if target.exists() else ""

                res = await self.remote_bridge.dispatch_remote_sweep(
                    script_content=content,
                    metric_key=metric,
                    seeds=seeds,
                    baseline_target=float(baseline) if baseline is not None else None,
                    gpu_type=gpu
                )

                out_str = (
                    f"Remote Sweep ({res.provider_used} on {res.gpu_allocated}): "
                    f"Mean {metric} = {res.stats_audit['mean']} across {len(res.seed_runs)} seeds. "
                    f"Verdict: {res.stats_audit['verdict']}"
                )
                return ToolResult(tool_name=tool_name, success=res.success, output=out_str)

            elif tool_name == "literature_ingest_pdf":"""

if "remote_cloud_sweep" not in code and old_dispatch in code:
    code = code.replace(old_dispatch, new_dispatch)

# 4. Add tool schema
old_schema = '            {"type": "function", "function": {"name": "literature_ingest_pdf",'
new_schema = """            {"type": "function", "function": {"name": "remote_cloud_sweep", "description": "Dispatches multi-seed experiment sweep to remote serverless cloud GPU (Modal/RunPod/SSH)", "parameters": {"type": "object", "properties": {"script_path": {"type": "string"}, "metric_key": {"type": "string"}, "seeds": {"type": "array", "items": {"type": "integer"}}, "baseline_target": {"type": "number"}, "gpu_type": {"type": "string"}}, "required": ["script_path"]}}},
            {"type": "function", "function": {"name": "literature_ingest_pdf","""

if "remote_cloud_sweep" not in code and old_schema in code:
    code = code.replace(old_schema, new_schema)

target.write_text(code, encoding="utf-8")
print("[✓] Registered remote_cloud_sweep tool in tool_registry.py.")
