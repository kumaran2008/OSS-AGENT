from __future__ import annotations
from tools.desktop import DesktopController

import ast
import inspect
import json
import os
import pty
import select
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from pydantic import BaseModel, ValidationError


@dataclass(frozen=True)
class ToolResult:
    """Universal execution contract returned by every internal tool."""

    tool_name: str
    success: bool
    output: Any
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "tool_name": self.tool_name,
                "success": self.success,
                "output": self.output,
                "error": self.error,
                "metadata": self.metadata,
            }
        )


class PTYManager:
    """Interactive Pseudo-Terminal (PTY) runner for Builder and Tester test suites."""

    def __init__(self, workspace_root: Path):
        self.workspace = workspace_root

    def execute_command(self, cmd: str, timeout_sec: float = 15.0) -> Tuple[int, str]:
        """Runs a command inside an isolated process group and captures stdout/stderr."""
        try:
            res = subprocess.run(
                cmd,
                shell=True,
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            out = res.stdout if res.returncode == 0 else f"{res.stdout}\n{res.stderr}".strip()
            return res.returncode, out
        except subprocess.TimeoutExpired:
            return 124, f"Command timed out after {timeout_sec}s."
        except Exception as e:
            return 1, f"Execution failed: {str(e)}"

    async def execute_and_collect(self, cmd: str, timeout: float = 30.0) -> Tuple[int, str]:
        """Asynchronous execution bridge for UnifiedAsyncEngine."""
        return self.execute_command(cmd, timeout_sec=timeout)


class SymbolMapper:
    """Parses Python AST across the workspace to construct symbol maps for Builder mode."""

    def __init__(self, workspace_root: Path):
        self.workspace = workspace_root

    def get_repo_map_summary(self, max_tokens: int = 600) -> str:
        summary_lines = []
        for py_file in self.workspace.glob("**/*.py"):
            if "venv" in str(py_file) or ".git" in str(py_file) or "__pycache__" in str(py_file):
                continue
            rel_path = py_file.relative_to(self.workspace)
            try:
                tree = ast.parse(py_file.read_text(encoding="utf-8", errors="ignore"))
                symbols = []
                for node in tree.body:
                    if isinstance(node, ast.FunctionDef):
                        symbols.append(f"def {node.name}()")
                    elif isinstance(node, ast.ClassDef):
                        symbols.append(f"class {node.name}")
                if symbols:
                    summary_lines.append(f"• {rel_path}: {', '.join(symbols[:5])}")
            except Exception:
                continue

        if not summary_lines:
            return "No Python symbols mapped in workspace."
        joined = "\n".join(summary_lines)
        return joined[: max_tokens * 4]



class DesktopBridge(DesktopController):
    """Production unified wrapper for desktop screen capture, coordinate clicks, and hotkeys."""
    def __init__(self, workspace_root=None, *args, **kwargs):
        super().__init__()
        self.workspace_root = workspace_root

    def capture_screen(self, filename: str = "desktop_screen.png", *args, **kwargs):
        return super().capture_screen(filename=filename, *args, **kwargs)


class ToolRegistry:
    """Master tool registry providing PTY, symbols, and schema-validated tool dispatch."""

    def __init__(self, workspace_root: str = "workspace"):
        self.workspace_root = Path(workspace_root).resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)

        self.desktop = DesktopController()
        self.pty = PTYManager(self.workspace_root)
        self.symbol_mapper = SymbolMapper(self.workspace_root)
        self.desktop = DesktopController()

        self._tools: Dict[str, Callable[..., Any]] = {}
        self._schemas: Dict[str, type[BaseModel]] = {}
        self._descriptions: Dict[str, str] = {}
        self._required_capabilities: Dict[str, str] = {}

    def register_tool(
        self,
        name: str,
        func: Callable[..., Any],
        schema: type[BaseModel],
        description: str,
        required_capability: str = "core.basic",
    ) -> None:
        self._tools[name] = func
        self._schemas[name] = schema
        self._descriptions[name] = description
        self._required_capabilities[name] = required_capability

    def get_openai_tool_specs(self, allowed_capabilities: set[str]) -> List[Dict[str, Any]]:
        specs = []
        for name, schema_cls in self._schemas.items():
            cap = self._required_capabilities[name]
            if "*" not in allowed_capabilities and cap not in allowed_capabilities:
                continue

            specs.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": self._descriptions.get(name, ""),
                        "parameters": schema_cls.model_json_schema(),
                    },
                }
            )
        return specs

    async def execute(self, tool_name: str, arguments: Dict[str, Any] | str) -> ToolResult:
        if tool_name not in self._tools:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                output=None,
                error=f"Tool '{tool_name}' is not registered.",
            )

        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError as e:
                return ToolResult(
                    tool_name=tool_name,
                    success=False,
                    output=None,
                    error=f"Malformed JSON arguments: {str(e)}",
                )

        schema_cls = self._schemas[tool_name]
        try:
            validated = schema_cls.model_validate(arguments)
        except ValidationError as val_err:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                output=None,
                error=f"Schema validation failure: {val_err.json()}",
            )

        handler = self._tools[tool_name]
        try:
            kwargs = validated.model_dump()
            if inspect.iscoroutinefunction(handler):
                raw_out = await handler(**kwargs)
            else:
                raw_out = handler(**kwargs)

            if isinstance(raw_out, ToolResult):
                return raw_out

            return ToolResult(tool_name=tool_name, success=True, output=raw_out)
        except Exception as exc:
            return ToolResult(
                tool_name=tool_name,
                success=False,
                output=None,
                error=f"Execution error ({type(exc).__name__}): {str(exc)}",
            )