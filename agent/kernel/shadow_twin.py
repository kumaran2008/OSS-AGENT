from __future__ import annotations

import ast
import hashlib
import py_compile
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple

from agent.kernel.native import native_accel
from agent.kernel.sandbox_isolation import SandboxedProcessResult, sandbox_executor


@dataclass
class SevenPointEvidenceReport:
    target_file_modified: bool
    stayed_within_authorized_scope: bool
    application_executed: bool
    test_suite_completed: bool
    tests_passed: bool
    unrelated_files_untouched: bool
    postconditions_verified: bool
    pre_assert_count: int
    post_assert_count: int
    asserts_preserved: bool
    toctou_state_clean: bool
    post_promotion_verified: bool
    pre_sha256: str
    post_sha256: str
    shadow_duration_ms: float
    evidence_summary: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_file_modified": self.target_file_modified,
            "stayed_within_authorized_scope": self.stayed_within_authorized_scope,
            "application_executed": self.application_executed,
            "test_suite_completed": self.test_suite_completed,
            "tests_passed": self.tests_passed,
            "unrelated_files_untouched": self.unrelated_files_untouched,
            "postconditions_verified": self.postconditions_verified,
            "pre_assert_count": self.pre_assert_count,
            "post_assert_count": self.post_assert_count,
            "asserts_preserved": self.asserts_preserved,
            "toctou_state_clean": self.toctou_state_clean,
            "post_promotion_verified": self.post_promotion_verified,
            "pre_sha256": self.pre_sha256,
            "post_sha256": self.post_sha256,
            "shadow_duration_ms": self.shadow_duration_ms,
            "evidence_summary": self.evidence_summary,
        }


class ShadowTwinEngine:
    """Double-Sandboxed Shadow Twin Pre-Execution Engine with TOCTOU Stale-State Guard
    and Post-Promotion Verification.
    """

    SHADOW_ROOT = Path("workspace/.shadow_twins")

    def __init__(self):
        self.SHADOW_ROOT.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def count_ast_asserts(py_source: str) -> int:
        try:
            tree = ast.parse(py_source)
            return sum(1 for n in ast.walk(tree) if isinstance(n, ast.Assert))
        except SyntaxError:
            return -1

    async def evaluate_and_promote_patch(
        self,
        target_path: Path,
        candidate_source: str,
        run_test_cmd: bool = True,
        auto_promote_on_pass: bool = True,
        timeout_sec: float = 5.0,
        simulate_concurrent_user_edit: Optional[str] = None,
    ) -> Tuple[bool, SevenPointEvidenceReport, SandboxedProcessResult]:
        from agent.pa_scaffolder.blackboard_kernel import undo_ledger

        t0 = time.perf_counter()
        resolved_target = target_path.resolve()
        allowed_roots = [str(Path("workspace").resolve()), str(Path("agent").resolve())]
        in_scope = any(str(resolved_target).startswith(r) for r in allowed_roots)

        orig_source = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
        pre_sha = hashlib.sha256(orig_source.encode("utf-8")).hexdigest()[:16]
        post_sha = hashlib.sha256(candidate_source.encode("utf-8")).hexdigest()[:16]
        pre_asserts = self.count_ast_asserts(orig_source)
        post_asserts = self.count_ast_asserts(candidate_source)
        asserts_ok = (post_asserts >= 0) and (post_asserts >= pre_asserts)

        rel_target_str = str(target_path)
        pre_manifest = native_accel.snapshot_workspace_hashes(
            ["workspace", "agent"],
            exclude_paths=[rel_target_str, str(resolved_target)],
        )

        twin_id = f"twin_{int(time.time() * 1000)}_{post_sha[:6]}"
        twin_dir = self.SHADOW_ROOT / twin_id
        twin_dir.mkdir(parents=True, exist_ok=True)
        shadow_file = twin_dir / target_path.name

        try:
            shadow_file.write_text(candidate_source, encoding="utf-8")

            syntax_ok = True
            if shadow_file.suffix == ".py":
                try:
                    py_compile.compile(str(shadow_file), doraise=True)
                except Exception as e:
                    syntax_ok = False
                    proc_res = SandboxedProcessResult(
                        exit_code=1,
                        stdout="",
                        stderr=f"SyntaxError in Shadow Twin: {e}",
                        duration_ms=(time.perf_counter() - t0) * 1000.0,
                        timed_out=False,
                        truncated_output=False,
                        isolated_pid=-1,
                        sanitized_env_confirmed=True,
                    )

            if syntax_ok:
                if run_test_cmd and shadow_file.suffix == ".py":
                    proc_res = await sandbox_executor.run_warm_python_script(
                        shadow_file,
                        candidate_source,
                        timeout_sec=timeout_sec,
                    )
                else:
                    proc_res = SandboxedProcessResult(
                        exit_code=0,
                        stdout="Syntax verified in Shadow Twin.",
                        stderr="",
                        duration_ms=(time.perf_counter() - t0) * 1000.0,
                        timed_out=False,
                        truncated_output=False,
                        isolated_pid=0,
                        sanitized_env_confirmed=True,
                    )
        finally:
            shutil.rmtree(twin_dir, ignore_errors=True)

        # Optional test hook: simulate user editing the real file while Shadow Twin was running
        if simulate_concurrent_user_edit is not None and target_path.exists():
            target_path.write_text(simulate_concurrent_user_edit, encoding="utf-8")

        tests_passed = syntax_ok and (proc_res.exit_code == 0) and not proc_res.timed_out and asserts_ok and in_scope

        # TOCTOU Check: Verify real file on disk was NOT modified since pre_sha snapshot
        current_disk_sha = (
            hashlib.sha256(target_path.read_bytes()).hexdigest()[:16]
            if target_path.exists()
            else pre_sha
        )
        toctou_clean = current_disk_sha == pre_sha

        promoted = False
        post_promo_ok = False
        if tests_passed and auto_promote_on_pass and toctou_clean:
            undo_ledger.execute_reversible_file_edit(
                target_path,
                candidate_source,
                description=f"Shadow-Twin verified patch on {target_path.name}",
            )
            promoted = True
            # Post-Promotion Verification on the real promoted file
            try:
                if target_path.suffix == ".py":
                    py_compile.compile(str(target_path), doraise=True)
                promoted_sha = hashlib.sha256(target_path.read_bytes()).hexdigest()[:16]
                post_promo_ok = promoted_sha == post_sha
            except Exception:
                post_promo_ok = False

        post_manifest = native_accel.snapshot_workspace_hashes(
            ["workspace", "agent"],
            exclude_paths=[rel_target_str, str(resolved_target)],
        )
        unrelated_untouched = (pre_manifest == post_manifest) and toctou_clean

        dur_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        all_verified = promoted and post_promo_ok and tests_passed and unrelated_untouched and in_scope

        if all_verified:
            summary = (
                f"Shadow Twin Verified & Promoted {target_path.name} in {dur_ms}ms: "
                f"ExitCode=0, Asserts={pre_asserts}->{post_asserts} (preserved), "
                f"SHA256={pre_sha[:8]}->{post_sha[:8]}, UnrelatedFilesModified=0 (checked {len(post_manifest)} files)."
            )
        else:
            reason = (
                "TOCTOU Stale-State Detected: Real file changed during Shadow Twin run" if not toctou_clean
                else ("Out of authorized scope" if not in_scope
                      else ("Test assertions deleted/weakened" if not asserts_ok
                            else f"Shadow test failed (exit_code={proc_res.exit_code})"))
            )
            summary = (
                f"Shadow Twin Rejected Patch on {target_path.name} ({reason}). "
                f"Real file {target_path.name} remained safe."
            )

        report = SevenPointEvidenceReport(
            target_file_modified=promoted,
            stayed_within_authorized_scope=in_scope,
            application_executed=syntax_ok,
            test_suite_completed=not proc_res.timed_out,
            tests_passed=tests_passed,
            unrelated_files_untouched=unrelated_untouched,
            postconditions_verified=all_verified,
            pre_assert_count=pre_asserts,
            post_assert_count=post_asserts,
            asserts_preserved=asserts_ok,
            toctou_state_clean=toctou_clean,
            post_promotion_verified=post_promo_ok,
            pre_sha256=pre_sha,
            post_sha256=post_sha if promoted else current_disk_sha,
            shadow_duration_ms=dur_ms,
            evidence_summary=summary,
        )
        return all_verified, report, proc_res


shadow_twin = ShadowTwinEngine()
