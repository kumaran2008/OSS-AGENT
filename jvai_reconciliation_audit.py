#!/usr/bin/env python3

import ast
import os
import json
import csv
import re
from pathlib import Path
from collections import defaultdict, deque
from datetime import datetime, timezone

ROOT = Path(".").resolve()
OUT = ROOT / "workspace" / "jvai_reconciliation_audit"
OUT.mkdir(parents=True, exist_ok=True)

OLD_ROUTER = "agent/pa_scaffolder/jev_router.py"
NEW_SYSTEM1 = "agent/kernel/jev_ai_system1.py"

SKIP = {
    ".git", ".venv", "venv", "env", "__pycache__",
    "node_modules", "dist", "build", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "site-packages"
}

SOURCE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
CONFIG_EXTENSIONS = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".md", ".txt"}

def safe_read(path):
    try:
        if path.stat().st_size > 1_500_000:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""

def scan_files():
    files = []
    for directory, dirs, filenames in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP]

        for filename in filenames:
            path = Path(directory) / filename

            if path.is_symlink():
                continue

            files.append(path)

    return sorted(files)

def relative(path):
    return path.relative_to(ROOT).as_posix()

def module_name(path):
    parts = list(path.relative_to(ROOT).with_suffix("").parts)

    if parts[-1] == "__init__":
        parts.pop()

    return ".".join(parts)

def parse_python(path):
    text = safe_read(path)

    result = {
        "imports": [],
        "dynamic_imports": [],
        "plugin_signals": [],
        "entrypoint_signals": [],
        "exec_eval_signals": [],
        "parse_error": None,
    }

    try:
        tree = ast.parse(text, filename=relative(path))
    except SyntaxError as error:
        result["parse_error"] = str(error)
        return result

    for node in ast.walk(tree):

        if isinstance(node, ast.Import):
            for alias in node.names:
                result["imports"].append(alias.name)

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                result["imports"].append(node.module)

        elif isinstance(node, ast.If):
            try:
                condition = ast.unparse(node.test)

                if condition == "__name__ == '__main__'":
                    result["entrypoint_signals"].append({
                        "line": node.lineno,
                        "type": "main_guard"
                    })
            except Exception:
                pass

        elif isinstance(node, ast.Call):

            if isinstance(node.func, ast.Name):
                function = node.func.id
            elif isinstance(node.func, ast.Attribute):
                function = node.func.attr
            else:
                function = ""

            if function in {"__import__", "import_module"}:
                literal = None

                if node.args and isinstance(node.args[0], ast.Constant):
                    if isinstance(node.args[0].value, str):
                        literal = node.args[0].value

                result["dynamic_imports"].append({
                    "line": node.lineno,
                    "function": function,
                    "literal_module": literal
                })

            if function in {
                "register",
                "register_plugin",
                "load_plugin",
                "entry_points"
            }:
                result["plugin_signals"].append({
                    "line": node.lineno,
                    "function": function
                })

            if function in {"exec", "eval"}:
                result["exec_eval_signals"].append({
                    "line": node.lineno,
                    "function": function
                })

    for line_number, line in enumerate(text.splitlines(), 1):

        if re.search(
            r"sys\.argv|argparse|typer\.run|click\.command",
            line
        ):
            result["entrypoint_signals"].append({
                "line": line_number,
                "type": "cli_signal"
            })

    return result

def main():

    print("Starting JVAI Architecture Reconciliation Audit...")
    print("Repository:", ROOT)
    print("Source files will not be modified.\n")

    files = scan_files()

    source_files = [
        path for path in files
        if path.suffix.lower() in SOURCE_EXTENSIONS
    ]

    python_files = [
        path for path in source_files
        if path.suffix.lower() == ".py"
    ]

    config_files = [
        path for path in files
        if path.suffix.lower() in CONFIG_EXTENSIONS
    ]

    print("Total files:", len(files))
    print("Source files:", len(source_files))
    print("Python files:", len(python_files))
    print("Config/documentation files:", len(config_files))

    module_map = defaultdict(list)

    for path in python_files:
        module_map[module_name(path)].append(relative(path))

    parsed = {}
    dependency_edges = []
    reverse_dependencies = defaultdict(set)

    print("\nAnalyzing Python imports...")

    for path in python_files:

        source = relative(path)
        info = parse_python(path)
        parsed[source] = info

        for imported_module in info["imports"]:

            possible_modules = [imported_module]

            parts = imported_module.split(".")

            for i in range(len(parts) - 1, 0, -1):
                possible_modules.append(".".join(parts[:i]))

            targets = set()

            for module in possible_modules:

                targets.update(module_map.get(module, []))

                module_path = ROOT.joinpath(*module.split("."))

                candidates = [
                    module_path.with_suffix(".py"),
                    module_path / "__init__.py"
                ]

                for candidate in candidates:
                    if candidate.is_file():
                        targets.add(relative(candidate))

            for target in targets:

                if target == source:
                    continue

                dependency_edges.append({
                    "from": source,
                    "to": target,
                    "import": imported_module,
                    "type": "static"
                })

                reverse_dependencies[target].add(source)

    print("Dependency edges:", len(dependency_edges))

    # Search references in source, configuration and documentation.

    print("\nSearching for file references...")

    searchable = []

    for path in files:

        if path.suffix.lower() not in (
            SOURCE_EXTENSIONS | CONFIG_EXTENSIONS
        ):
            continue

        text = safe_read(path)

        if text:
            searchable.append((relative(path), text))

    text_references = defaultdict(list)

    for source_path in source_files:

        source = relative(source_path)
        stem = source_path.stem

        if len(stem) < 5:
            continue

        for search_path, text in searchable:

            if search_path == source:
                continue

            if stem in text or source in text:
                text_references[source].append(search_path)

    # Classify files.

    classifications = {}

    for source, info in parsed.items():

        importers = sorted(reverse_dependencies[source])
        references = sorted(set(text_references[source]))

        if info["entrypoint_signals"]:
            classification = "ENTRYPOINT_SIGNAL"

        elif importers:
            classification = "REFERENCED_STATICALLY"

        elif references:
            classification = "TEXT_OR_CONFIG_REFERENCED"

        elif info["dynamic_imports"] or info["plugin_signals"]:
            classification = "DYNAMIC_OR_PLUGIN_SIGNAL"

        else:
            classification = "POSSIBLE_ORPHAN_NEEDS_MANUAL_REVIEW"

        classifications[source] = {
            "classification": classification,
            "static_importers": importers,
            "text_config_references": references[:100],
            "dynamic_imports": info["dynamic_imports"],
            "plugin_signals": info["plugin_signals"],
            "entrypoint_signals": info["entrypoint_signals"],
            "exec_eval_signals": info["exec_eval_signals"],
            "parse_error": info["parse_error"],
        }

    # Find duplicate filename stems.

    stem_groups = defaultdict(list)

    for path in source_files:
        stem_groups[path.stem.lower()].append(relative(path))

    duplicate_stems = {
        stem: paths
        for stem, paths in stem_groups.items()
        if len(paths) > 1
    }

    # Build static dependency graph.

    graph = defaultdict(set)

    for edge in dependency_edges:
        graph[edge["from"]].add(edge["to"])

    def trace(start):

        if start not in parsed:
            return {
                "exists": False,
                "reachable_count": 0,
                "reachable": [],
                "unreachable_count": len(parsed),
                "unreachable": sorted(parsed)
            }

        visited = set()
        queue = deque([start])

        while queue:

            current = queue.popleft()

            if current in visited:
                continue

            visited.add(current)

            queue.extend(graph[current] - visited)

        unreachable = sorted(set(parsed) - visited)

        return {
            "exists": True,
            "reachable_count": len(visited),
            "reachable": sorted(visited),
            "unreachable_count": len(unreachable),
            "unreachable": unreachable
        }

    old_router_trace = trace(OLD_ROUTER)
    new_system1_trace = trace(NEW_SYSTEM1)

    possible_orphans = [
        path
        for path, info in classifications.items()
        if info["classification"]
        == "POSSIBLE_ORPHAN_NEEDS_MANUAL_REVIEW"
    ]

    report = {

        "metadata": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "repository": str(ROOT),
            "read_only": True,
            "warning": (
                "Heuristic report. No file is confirmed dead code. "
                "Dynamic imports, plugin systems, runtime loading, "
                "subprocesses and configuration may hide references."
            )
        },

        "summary": {
            "total_files": len(files),
            "source_files": len(source_files),
            "python_files": len(python_files),
            "config_files": len(config_files),
            "dependency_edges": len(dependency_edges),
            "python_parse_errors": sum(
                bool(info["parse_error"])
                for info in parsed.values()
            ),
            "possible_orphan_candidates": len(possible_orphans),
            "duplicate_filename_stem_groups": len(duplicate_stems),
        },

        "router_comparison": {
            "old_router": {
                "path": OLD_ROUTER,
                **old_router_trace
            },
            "new_system1": {
                "path": NEW_SYSTEM1,
                **new_system1_trace
            }
        },

        "file_classifications": classifications,

        "duplicate_filename_stems": duplicate_stems,

        "dependency_edges": dependency_edges,
    }

    # JSON report.

    json_path = OUT / "reconciliation_audit.json"

    json_path.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8"
    )

    # CSV report.

    csv_path = OUT / "file_classifications.csv"

    with csv_path.open("w", newline="", encoding="utf-8") as file:

        writer = csv.DictWriter(
            file,
            fieldnames=[
                "path",
                "classification",
                "static_importers_count",
                "text_config_references_count",
                "parse_error"
            ]
        )

        writer.writeheader()

        for path, info in sorted(classifications.items()):

            writer.writerow({
                "path": path,
                "classification": info["classification"],
                "static_importers_count": len(
                    info["static_importers"]
                ),
                "text_config_references_count": len(
                    info["text_config_references"]
                ),
                "parse_error": info["parse_error"] or ""
            })

    # Markdown report.

    md_path = OUT / "reconciliation_audit.md"

    lines = [
        "# JVAI Architecture Reconciliation Audit",
        "",
        f"Generated: {report['metadata']['generated_at_utc']}",
        "",
        "## Summary",
        "",
        f"- Total files: {len(files)}",
        f"- Source files: {len(source_files)}",
        f"- Python files: {len(python_files)}",
        f"- Dependency edges: {len(dependency_edges)}",
        f"- Parse errors: {report['summary']['python_parse_errors']}",
        f"- Possible orphan candidates: {len(possible_orphans)}",
        f"- Duplicate filename stems: {len(duplicate_stems)}",
        "",
        "## Old Router vs New System 1",
        "",
        f"- Old router: {old_router_trace['reachable_count']} reachable",
        f"- New System 1: {new_system1_trace['reachable_count']} reachable",
        "",
        "## Possible Orphan Candidates — Manual Review",
        ""
    ]

    lines.extend(
        f"- `{path}`"
        for path in possible_orphans[:200]
    )

    lines += [
        "",
        "## Duplicate Filename Stems",
        ""
    ]

    for stem, paths in sorted(duplicate_stems.items()):

        lines.append(
            f"- **{stem}**: "
            + ", ".join(f"`{path}`" for path in paths)
        )

    lines += [
        "",
        "## Important Warning",
        "",
        "Do not delete files based only on this report.",
        "",
        "Dynamic imports, plugins, configuration, subprocesses, "
        "tests and alternate entrypoints can make files appear unused.",
        ""
    ]

    md_path.write_text(
        "\n".join(lines),
        encoding="utf-8"
    )

    print("\nAUDIT COMPLETED")
    print("==============================")
    print("JSON:", json_path)
    print("Markdown:", md_path)
    print("CSV:", csv_path)
    print("Possible orphan candidates:", len(possible_orphans))
    print("\nNo source files were modified.")

if __name__ == "__main__":
    main()
