from pathlib import Path

target = Path("agent/pa_scaffolder/cdp_bridge.py")
code = target.read_text(encoding="utf-8")

old_method_head = "    async def stream_browser_generation(\n        self,\n        prompt: str,\n        timeout: float = 30.0\n    ) -> AsyncGenerator[str, None]:"
new_method_head = "    async def stream_browser_generation(\n        self,\n        prompt: str,\n        timeout: float = 30.0,\n        image_path: Optional[str] = None\n    ) -> AsyncGenerator[str, None]:"

upload_injection_block = """            # 0. Upload Image via native CDP DOM.setFileInputFiles if provided
            if image_path and Path(image_path).exists():
                abs_img = str(Path(image_path).resolve())
                try:
                    await ws.call_method("DOM.enable")
                    doc = await ws.call_method("DOM.getDocument")
                    root_id = doc.get("result", {}).get("root", {}).get("nodeId", 0)
                    if root_id:
                        file_input = await ws.call_method("DOM.querySelector", {
                            "nodeId": root_id,
                            "selector": "input[type='file']"
                        })
                        input_node_id = file_input.get("result", {}).get("nodeId", 0)
                        if input_node_id:
                            await ws.call_method("DOM.setFileInputFiles", {
                                "files": [abs_img],
                                "nodeId": input_node_id
                            })
                            await asyncio.sleep(1.2)  # Give browser time to generate preview
                except Exception:
                    pass
"""

if old_method_head in code:
    code = code.replace(old_method_head, new_method_head)

if "DOM.setFileInputFiles" not in code:
    anchor = 'await ws.call_method("Runtime.enable")'
    code = code.replace(anchor, anchor + "\n\n" + upload_injection_block)
    target.write_text(code, encoding="utf-8")
    print("[✓] Added native DOM.setFileInputFiles file upload to cdp_bridge.py")
else:
    print("[i] File upload support already present in cdp_bridge.py")
