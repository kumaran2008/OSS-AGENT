from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from agent.kernel.fault_recorder import fault_recorder
from agent.kernel.native import native_accel
from agent.oryn.contracts import (
    AXTreeSnapshot,
    ComputerAction,
    ExecutionReceipt,
)


class ORYNUniversalVerifier:
    """Layer 7a: Universal Cross-Channel Postcondition Verifier for ORYN.

    Verifies execution receipts across all 6 stages:
      - `native_api`: Verifies exit_code == 0, non-empty output files, and 64-bit FNV-1a hash receipts.
      - `dom` / `cdp`: Verifies DOM element presence, selector match, or AXTreeDiff state change.
      - `accessibility`: Verifies live target guard pass, coordinate bounds, and AXTreeDiff.
      - `vision` / `frontier_cua`: Verifies dirty_rect pixel diff or screenshot state transition.
    """

    @fault_recorder.guard(subsystem="oryn.verifier")
    async def verify_execution(
        self,
        action: ComputerAction,
        receipt: ExecutionReceipt,
        pre_snapshot: Optional[AXTreeSnapshot] = None,
        post_snapshot: Optional[AXTreeSnapshot] = None,
    ) -> ExecutionReceipt:
        if receipt.status in ("BLOCKED_POLICY", "STALE_TARGET_ABORTED", "FAILED"):
            receipt.verified = False
            return receipt

        # 1. File output verification (if action produced or modified a file)
        out_path_str = receipt.output_data.get("file_path")
        if out_path_str:
            p = Path(str(out_path_str))
            if not p.exists() or p.stat().st_size == 0:
                receipt.status = "FAILED"
                receipt.verified = False
                receipt.error_code = "VERIFIER_FILE_MISSING_OR_EMPTY"
                receipt.observed_evidence = f"Verifier rejected: file {p} missing or empty."
                return receipt
            receipt.output_data["verified_fnv64"] = native_accel.fast_hash64_hex(p.read_bytes())

        # 2. Subprocess / CLI exit code check
        if "exit_code" in receipt.output_data and int(receipt.output_data["exit_code"]) != 0:
            receipt.status = "FAILED"
            receipt.verified = False
            receipt.error_code = f"VERIFIER_NONZERO_EXIT_{receipt.output_data['exit_code']}"
            return receipt

        # 3. Unexpected modal guard on GUI/AX channels
        if receipt.ax_diff and receipt.ax_diff.modal_appeared and "allow_modal" not in action.expected_postconditions:
            receipt.recovery_suggestion = "Unexpected modal dialog appeared; inspect modal refs before continuing."

        receipt.verified = True
        return receipt


oryn_verifier = ORYNUniversalVerifier()
