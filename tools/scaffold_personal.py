import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parent.parent


class PersonalAgentScaffolder:
    """
    Scaffolds and validates an air-gapped, zero-retention Personal Agent
    for either mobile or PC into a standalone directory.
    """

    def __init__(self, tier: str = "mobile"):
        self.tier = tier
        if tier == "pc":
            self.template_dir = REPO_ROOT / "templates" / "sentinel_pc"
        else:
            self.template_dir = REPO_ROOT / "templates" / "sentinel_personal"

        if not self.template_dir.exists():
            raise FileNotFoundError(f"Template directory not found at: {self.template_dir}")

    def scaffold(self, target_dir: Path, overwrite: bool = False) -> Dict[str, Any]:
        target_dir = target_dir.resolve()
        if target_dir.exists() and not overwrite:
            raise FileExistsError(f"Target directory '{target_dir}' already exists. Use --force to overwrite.")

        target_dir.mkdir(parents=True, exist_ok=True)

        copied_files = []
        for src_file in self.template_dir.iterdir():
            if src_file.name.startswith("__") or src_file.suffix == ".pyc":
                continue
            dest_file = target_dir / src_file.name
            if src_file.is_file():
                shutil.copy2(src_file, dest_file)
                copied_files.append(src_file.name)

        audit_results = self.audit_isolated_build(target_dir)

        return {
            "status": "SUCCESS" if audit_results["passed"] else "AUDIT_FAILED",
            "destination": str(target_dir),
            "files_copied": copied_files,
            "audit": audit_results,
        }

    def audit_isolated_build(self, target_dir: Path) -> Dict[str, Any]:
        """
        Invariants check:
        1. NO reference to .experience or distillation buffers
        2. NO external API keys or cloud endpoints hardcoded
        3. NO dependency on oss-agent internal modules
        """
        violations = []
        for py_file in target_dir.glob("*.py"):
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            if "agent.masons" in content or "agent.orchestrator" in content:
                violations.append(f"{py_file.name}: Coupled to oss-agent core modules.")
            if ".experience" in content or "experience_buffer" in content:
                violations.append(f"{py_file.name}: References persistent training buffer.")
            if "api.openrouter.ai" in content or "api.anthropic.com" in content:
                violations.append(f"{py_file.name}: Hardcoded external cloud API.")

        return {
            "passed": len(violations) == 0,
            "violations": violations,
            "files_checked": [p.name for p in target_dir.glob("*.py")],
        }


def main():
    parser = argparse.ArgumentParser(description="Scaffold a standalone, zero-retention Personal Agent.")
    parser.add_argument(
        "--tier",
        choices=["mobile", "pc"],
        default="mobile",
        help="Target device tier (mobile or pc)",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="Target installation folder (defaults to ~/sentinel-personal or ~/sentinel-pc)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite target folder if it exists",
    )
    args = parser.parse_args()

    if args.target:
        dest = Path(args.target).expanduser().resolve()
    else:
        default_folder = "~/sentinel-pc" if args.tier == "pc" else "~/sentinel-personal"
        dest = Path(default_folder).expanduser().resolve()

    scaffolder = PersonalAgentScaffolder(tier=args.tier)

    print(f"[*] Scaffolding standalone Personal Agent ({args.tier}) to: {dest}")
    res = scaffolder.scaffold(dest, overwrite=args.force)

    if res["status"] == "SUCCESS":
        print("[+] Scaffolding complete and security audit passed!")
        print(f"    • Files created: {', '.join(res['files_copied'])}")
        print("\nTo launch your standalone personal agent:")
        print(f"    cd {dest}")
        print("    ./run.sh")
    else:
        print("[-] Scaffolding security audit failed:")
        for v in res["audit"]["violations"]:
            print(f"    • {v}")
        sys.exit(1)


if __name__ == "__main__":
    main()
