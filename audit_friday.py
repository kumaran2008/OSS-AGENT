from __future__ import annotations

import ast
import json
import os
import sys
import time
import subprocess
import argparse
import traceback

from pathlib import Path
from collections import defaultdict, Counter


# ============================================================
# FRIDAY FULL-SYSTEM INTEGRITY AUDITOR
# Read-only static architecture audit
# ============================================================

ROOT = Path.cwd().resolve()

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".shadow_staging",
}

SOURCE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
}

REPORT_DIR = ROOT / "workspace" / "audit_reports"

REPORT_DIR.mkdir(parents=True, exist_ok=True)

timestamp = time.strftime("%Y%m%d_%H%M%S")

REPORT_JSON = REPORT_DIR / f"friday_audit_{timestamp}.json"
REPORT_MD = REPORT_DIR / f"friday_audit_{timestamp}.md"


# ============================================================
# DATA STRUCTURES
# ============================================================

issues = []

module_map = {}
module_to_path = {}

imports = defaultdict(set)
reverse_imports = defaultdict(set)

definitions = defaultdict(list)

parsed_files = {}

stats = Counter()


def add_issue(
    severity,
    category,
    file,
    line,
    message,
    evidence=None,
):
    issues.append({
        "severity": severity,
        "category": category,
        "file": str(file),
        "line": line,
        "message": message,
        "evidence": evidence,
    })


# ============================================================
# DISCOVER FILES
# ============================================================

def discover_files():

    files = []

    for current_root, dirs, filenames in os.walk(ROOT):

        dirs[:] = [
            d for d in dirs
            if d not in EXCLUDED_DIRS
        ]

        for filename in filenames:

            path = Path(current_root) / filename

            if path.suffix.lower() in SOURCE_EXTENSIONS:

                files.append(path.resolve())

    return sorted(files)


# ============================================================
# MODULE NAME RESOLUTION
# ============================================================

def module_name_from_path(path):

    relative = path.relative_to(ROOT)

    parts = list(relative.parts)

    if parts[-1] == "__init__.py":
        parts = parts[:-1]

    else:
        parts[-1] = Path(parts[-1]).stem

    return ".".join(parts)


def register_modules(files):

    for path in files:

        if path.suffix != ".py":
            continue

        module = module_name_from_path(path)

        module_map[path] = module

        module_to_path[module] = path

        stats["python_modules"] += 1


# ============================================================
# IMPORT RESOLUTION
# ============================================================

def resolve_import(import_name, current_module=None):

    if not import_name:
        return None

    candidates = []

    # Direct import.
    candidates.append(import_name)

    # Parent package resolution.
    parts = import_name.split(".")

    for i in range(len(parts) - 1, 0, -1):

        candidates.append(
            ".".join(parts[:i])
        )

    for candidate in candidates:

        if candidate in module_to_path:

            return candidate

    return None


def resolve_relative_import(node, current_module):

    if not current_module:
        return None

    parts = current_module.split(".")

    # Remove current module name for package resolution.
    package_parts = parts[:-1]

    if node.level > len(package_parts) + 1:
        return None

    base_parts = package_parts[:len(package_parts) - node.level + 1]

    if node.module:

        base_parts += node.module.split(".")

    return ".".join(base_parts)


# ============================================================
# AST ANALYSIS
# ============================================================

class FridayASTAnalyzer(ast.NodeVisitor):

    def __init__(self, path, module):

        self.path = path

        self.module = module

        self.current_class = None

    def visit_Import(self, node):

        for alias in node.names:

            imported = alias.name

            resolved = resolve_import(imported)

            if resolved:

                imports[self.module].add(resolved)

                reverse_imports[resolved].add(self.module)

            elif imported.startswith(
                ("agent.", "workspace.", "oss_agent.")
            ):

                add_issue(
                    "HIGH",
                    "UNRESOLVED_LOCAL_IMPORT",
                    self.path,
                    node.lineno,
                    f"Cannot resolve local import: {imported}",
                )

            stats["import_statements"] += 1

        self.generic_visit(node)

    def visit_ImportFrom(self, node):

        base = node.module or ""

        if node.level:

            base = resolve_relative_import(
                node,
                self.module,
            ) or ""

        resolved = resolve_import(base)

        if resolved:

            imports[self.module].add(resolved)

            reverse_imports[resolved].add(self.module)

        elif base.startswith(
            ("agent.", "workspace.", "oss_agent.")
        ):

            add_issue(
                "HIGH",
                "UNRESOLVED_LOCAL_IMPORT",
                self.path,
                node.lineno,
                f"Cannot resolve local import: {base}",
            )

        # Check imported symbols.
        if resolved:

            target_path = module_to_path.get(resolved)

            if target_path and target_path.exists():

                try:

                    target_tree = ast.parse(
                        target_path.read_text(
                            encoding="utf-8",
                            errors="replace",
                        )
                    )

                    target_names = {
                        n.name
                        for n in target_tree.body
                        if isinstance(
                            n,
                            (
                                ast.FunctionDef,
                                ast.AsyncFunctionDef,
                                ast.ClassDef,
                            ),
                        )
                    }

                    for alias in node.names:

                        if alias.name == "*":
                            continue

                        if (
                            alias.name not in target_names
                            and target_path.name != "__init__.py"
                        ):

                            add_issue(
                                "MEDIUM",
                                "POSSIBLE_MISSING_SYMBOL",
                                self.path,
                                node.lineno,
                                (
                                    f"Imported symbol '{alias.name}' "
                                    f"not found in {resolved}"
                                ),
                            )

                except Exception:
                    pass

        stats["from_import_statements"] += 1

        self.generic_visit(node)

    def visit_ClassDef(self, node):

        definitions[node.name].append({
            "type": "class",
            "file": str(self.path),
            "line": node.lineno,
            "module": self.module,
        })

        self.current_class = node.name

        self.generic_visit(node)

        self.current_class = None

    def visit_FunctionDef(self, node):

        definitions[node.name].append({
            "type": "function",
            "file": str(self.path),
            "line": node.lineno,
            "module": self.module,
        })

        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):

        definitions[node.name].append({
            "type": "async_function",
            "file": str(self.path),
            "line": node.lineno,
            "module": self.module,
        })

        self.generic_visit(node)


# ============================================================
# SYNTAX + AST SCAN
# ============================================================

def analyze_python_file(path):

    try:

        source = path.read_text(
            encoding="utf-8",
            errors="replace",
        )

        tree = ast.parse(
            source,
            filename=str(path),
        )

        module = module_map[path]

        parsed_files[path] = tree

        analyzer = FridayASTAnalyzer(
            path,
            module,
        )

        analyzer.visit(tree)

        stats["parsed_python_files"] += 1

        # Search suspicious unfinished implementations.
        for line_number, line in enumerate(
            source.splitlines(),
            start=1,
        ):

            stripped = line.strip()

            if stripped.startswith("#"):
                continue

            if "TODO" in stripped:

                add_issue(
                    "LOW",
                    "TODO",
                    path,
                    line_number,
                    stripped[:250],
                )

            if "FIXME" in stripped:

                add_issue(
                    "MEDIUM",
                    "FIXME",
                    path,
                    line_number,
                    stripped[:250],
                )

            if stripped in {
                "pass",
                "return None",
                "raise NotImplementedError",
                "NotImplementedError()",
            }:

                add_issue(
                    "LOW",
                    "POSSIBLE_PLACEHOLDER",
                    path,
                    line_number,
                    f"Potential incomplete implementation: {stripped}",
                )

    except SyntaxError as exc:

        add_issue(
            "CRITICAL",
            "SYNTAX_ERROR",
            path,
            exc.lineno or 0,
            exc.msg,
            evidence=exc.text,
        )

    except Exception as exc:

        add_issue(
            "HIGH",
            "AST_ANALYSIS_ERROR",
            path,
            0,
            repr(exc),
        )


# ============================================================
# DISCONNECTED MODULE ANALYSIS
# ============================================================

def analyze_disconnected_modules():

    all_modules = set(module_to_path.keys())

    referenced_modules = set()

    for source_module, targets in imports.items():

        referenced_modules.update(targets)

    entrypoint_candidates = {
        module
        for module in all_modules
        if (
            module.endswith("main")
            or module.endswith("cli")
            or module.endswith("__main__")
            or module.endswith("server")
        )
    }

    for module in all_modules:

        path = module_to_path[module]

        if path.name == "__init__.py":
            continue

        if module in entrypoint_candidates:
            continue

        if module not in referenced_modules:

            add_issue(
                "MEDIUM",
                "POSSIBLE_ORPHAN_MODULE",
                path,
                0,
                (
                    "No incoming static Python import found. "
                    "May be an entrypoint, plugin, dynamically imported "
                    "module, or genuinely disconnected file."
                ),
            )


# ============================================================
# CIRCULAR DEPENDENCY DETECTION
# ============================================================

def detect_cycles():

    visited = set()

    stack = []

    active = set()

    reported = set()

    def dfs(module):

        visited.add(module)

        active.add(module)

        stack.append(module)

        for dependency in imports.get(module, []):

            if dependency not in module_to_path:
                continue

            if dependency not in visited:

                dfs(dependency)

            elif dependency in active:

                try:

                    start = stack.index(dependency)

                    cycle = stack[start:] + [dependency]

                    cycle_key = tuple(sorted(set(cycle)))

                    if cycle_key not in reported:

                        reported.add(cycle_key)

                        add_issue(
                            "HIGH",
                            "CIRCULAR_DEPENDENCY",
                            module_to_path[module],
                            0,
                            " -> ".join(cycle),
                        )

                except ValueError:
                    pass

        stack.pop()

        active.remove(module)

    for module in module_to_path:

        if module not in visited:

            dfs(module)


# ============================================================
# DUPLICATE DEFINITIONS
# ============================================================

def detect_duplicates():

    for name, occurrences in definitions.items():

        distinct_files = {
            item["file"]
            for item in occurrences
        }

        if len(distinct_files) > 1:

            # Ignore common names that are naturally repeated.
            if name.startswith("__"):
                continue

            add_issue(
                "LOW",
                "DUPLICATE_DEFINITION_NAME",
                occurrences[0]["file"],
                occurrences[0]["line"],
                (
                    f"'{name}' defined in "
                    f"{len(distinct_files)} different files."
                ),
                evidence=occurrences,
            )


# ============================================================
# TEST DISCOVERY
# ============================================================

def analyze_test_coverage_structure():

    test_files = []

    for path in ROOT.rglob("*.py"):

        if any(
            part in EXCLUDED_DIRS
            for part in path.parts
        ):
            continue

        if (
            path.name.startswith("test_")
            or path.name.startswith("verify_")
            or "tests" in path.parts
        ):

            test_files.append(path)

    stats["test_files"] = len(test_files)

    if not test_files:

        add_issue(
            "CRITICAL",
            "NO_TEST_FILES",
            ROOT,
            0,
            "No test or verification files discovered.",
        )

    for path in test_files:

        try:

            source = path.read_text(
                encoding="utf-8",
                errors="replace",
            )

            if "assert " not in source:

                add_issue(
                    "MEDIUM",
                    "TEST_WITHOUT_ASSERTIONS",
                    path,
                    0,
                    "Test file contains no visible assert statements.",
                )

        except Exception:
            pass


# ============================================================
# ARCHITECTURE SUMMARY
# ============================================================

def build_architecture_summary():

    module_count = len(module_to_path)

    edge_count = sum(
        len(targets)
        for targets in imports.values()
    )

    degree = Counter()

    for source, targets in imports.items():

        degree[source] += len(targets)

    most_connected = degree.most_common(20)

    return {
        "root": str(ROOT),
        "python_modules": module_count,
        "static_import_edges": edge_count,
        "test_files": stats["test_files"],
        "parsed_python_files": stats["parsed_python_files"],
        "syntax_errors": sum(
            1
            for i in issues
            if i["category"] == "SYNTAX_ERROR"
        ),
        "most_connected_modules": [
            {
                "module": module,
                "outgoing_imports": count,
                "path": str(module_to_path.get(module)),
            }
            for module, count in most_connected
        ],
        "imports": {
            module: sorted(targets)
            for module, targets in imports.items()
        },
        "reverse_imports": {
            module: sorted(targets)
            for module, targets in reverse_imports.items()
        },
    }


# ============================================================
# REPORT GENERATION
# ============================================================

def generate_reports():

    severity_order = {
        "CRITICAL": 0,
        "HIGH": 1,
        "MEDIUM": 2,
        "LOW": 3,
    }

    issues.sort(
        key=lambda item: (
            severity_order.get(
                item["severity"],
                99,
            ),
            item["file"],
            item["line"],
        )
    )

    severity_counts = Counter(
        item["severity"]
        for item in issues
    )

    category_counts = Counter(
        item["category"]
        for item in issues
    )

    report = {
        "audit_name": "Friday Full-System Integrity Auditor",
        "timestamp": timestamp,
        "root": str(ROOT),
        "summary": build_architecture_summary(),
        "severity_counts": dict(severity_counts),
        "category_counts": dict(category_counts),
        "issues": issues,
        "statistics": dict(stats),
    }

    REPORT_JSON.write_text(
        json.dumps(
            report,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    md = []

    md.append("# Friday Full-System Integrity Audit")

    md.append(f"\nRoot: `{ROOT}`")

    md.append(f"\nTimestamp: `{timestamp}`")

    md.append("\n## Summary")

    md.append(
        f"\nPython modules: "
        f"{report['summary']['python_modules']}"
    )

    md.append(
        f"\nParsed Python files: "
        f"{report['summary']['parsed_python_files']}"
    )

    md.append(
        f"\nStatic import edges: "
        f"{report['summary']['static_import_edges']}"
    )

    md.append(
        f"\nTest files: "
        f"{report['summary']['test_files']}"
    )

    md.append("\n## Severity Counts")

    for severity, count in severity_counts.items():

        md.append(
            f"\n- {severity}: {count}"
        )

    md.append("\n## Issues")

    if not issues:

        md.append(
            "\nNo static issues were discovered. "
            "This does not prove runtime correctness or security."
        )

    for item in issues:

        md.append(
            "\n### "
            f"[{item['severity']}] "
            f"{item['category']}"
        )

        md.append(
            f"\nFile: `{item['file']}`"
        )

        md.append(
            f"\nLine: {item['line']}"
        )

        md.append(
            f"\n{item['message']}"
        )

        if item.get("evidence"):

            md.append(
                "\n```text\n"
                + str(item["evidence"])
                + "\n```"
            )

    REPORT_MD.write_text(
        "\n".join(md),
        encoding="utf-8",
    )

    print("\n" + "=" * 72)

    print("FRIDAY FULL-SYSTEM AUDIT COMPLETED")

    print("=" * 72)

    print(f"Python modules : {stats['python_modules']}")

    print(f"Parsed files   : {stats['parsed_python_files']}")

    print(f"Test files     : {stats['test_files']}")

    print(f"Total issues   : {len(issues)}")

    for severity in (
        "CRITICAL",
        "HIGH",
        "MEDIUM",
        "LOW",
    ):

        print(
            f"{severity:10}: "
            f"{severity_counts.get(severity, 0)}"
        )

    print("\nReports generated:")

    print(REPORT_JSON)

    print(REPORT_MD)

    print("=" * 72)


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--root",
        default=".",
        help="Friday repository root",
    )

    args = parser.parse_args()

    global ROOT

    ROOT = Path(args.root).resolve()

    print("\n[1/7] Discovering source files...")

    files = discover_files()

    print(
        f"Discovered {len(files)} source files."
    )

    print("\n[2/7] Registering Python modules...")

    register_modules(files)

    print("\n[3/7] Running AST analysis...")

    for path in files:

        if path.suffix == ".py":

            analyze_python_file(path)

    print("\n[4/7] Detecting disconnected modules...")

    analyze_disconnected_modules()

    print("\n[5/7] Detecting circular dependencies...")

    detect_cycles()

    print("\n[6/7] Detecting duplicate definitions...")

    detect_duplicates()

    print("\n[7/7] Inspecting test structure...")

    analyze_test_coverage_structure()

    generate_reports()


if __name__ == "__main__":

    main()

