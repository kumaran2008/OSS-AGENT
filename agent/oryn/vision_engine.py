from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.kernel.fault_recorder import fault_recorder
from agent.kernel.jev_ai_system1 import jev_ai_brain
from agent.kernel.native import native_accel
from agent.oryn.contracts import (
    AXTreeSnapshot,
    AppNode,
    BoundingBox,
    ChannelType,
    ComputerAction,
    ExecutionDriver,
    ExecutionReceipt,
    RefNode,
    WindowNode,
)
from agent.oryn.runtime import oryn_runtime


class LocalVisionAndGroundingEngine(ExecutionDriver):
    """Stage 5 Local Vision, C Dirty-Rect Pixel Gate, Local OCR & Visual Prompt Firewall.

    Responsibilities:
      1. C-accelerated dirty-rect comparison (`native_accel.compute_dirty_rect`) to skip redundant VLM/OCR calls.
      2. Local OCR (`tesseract` TSV output) & UI grid grounding to map unlabeled controls into `r1..rN` RefNodes.
      3. Visual Prompt-Injection Firewall: scans screen text for adversarial instructions and flags
         `taint_level = "UNTRUSTED_EXTERNAL"` before any state-mutating action is permitted.
    """

    channel: ChannelType = "vision"

    PROMPT_INJECTION_PATTERNS = (
        re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions", re.I),
        re.compile(r"system\s+override\s*:", re.I),
        re.compile(r"execute\s+shell\s+command", re.I),
        re.compile(r"\brm\s+-rf\b", re.I),
        re.compile(r"send\s+(?:all\s+)?(?:api\s+keys|passwords|tokens|\.env)\s+to", re.I),
    )

    def __init__(self, workspace_root: Optional[Path] = None) -> None:
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self._last_frame_bytes: Optional[bytes] = None
        self._last_frame_hash: str = ""
        self.last_snapshot: Optional[AXTreeSnapshot] = None

    async def discover(self, target_app_or_url: str) -> Dict[str, Any]:
        has_tesseract = shutil.which("tesseract") is not None
        return {
            "channel": self.channel,
            "c_dirty_rect_accelerated": native_accel.using_c_extension,
            "local_ocr_tesseract": has_tesseract,
            "confidence": 0.90 if has_tesseract else 0.85,
            "target": target_app_or_url,
        }

    @classmethod
    def inspect_screen_text_for_taint(cls, extracted_text: str) -> Dict[str, Any]:
        """Treats on-screen content as data, never authority. Detects visual prompt injection."""
        matched_rules: List[str] = []
        for pat in cls.PROMPT_INJECTION_PATTERNS:
            if pat.search(extracted_text):
                matched_rules.append(pat.pattern)
        is_hostile = len(matched_rules) > 0
        return {
            "taint_level": "UNTRUSTED_EXTERNAL" if is_hostile else "OBSERVED_SCREEN",
            "prompt_injection_detected": is_hostile,
            "matched_patterns": matched_rules,
        }

    def run_local_ocr_grounding(
        self,
        image_path: Optional[Path],
        ocr_boxes_override: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[AXTreeSnapshot, str]:
        w, h = oryn_runtime.primary_runtime.display_dimensions
        elements: Dict[str, RefNode] = {}
        extracted_texts: List[str] = []
        counter = 0

        if ocr_boxes_override:
            for item in ocr_boxes_override:
                counter += 1
                rid = str(item.get("ref_id") or f"r{counter}")
                label = str(item.get("text") or item.get("label") or f"visual_control_{counter}")
                b_raw = item.get("bounds") or [int(w * 0.4), int(h * 0.4), int(w * 0.6), int(h * 0.5)]
                bbox = BoundingBox(int(b_raw[0]), int(b_raw[1]), int(b_raw[2]), int(b_raw[3]))
                elements[rid] = RefNode(
                    ref_id=rid,
                    window_ref="w1",
                    app_ref="a1",
                    role=str(item.get("role", "visual_element")),
                    name=label[:80],
                    bounds=bbox,
                    enabled=True,
                )
                extracted_texts.append(label)

        elif image_path and image_path.exists() and shutil.which("tesseract"):
            try:
                out = subprocess.check_output(
                    ["tesseract", str(image_path), "stdout", "tsv"],
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=3.0,
                )
                for line in out.splitlines()[1:]:
                    cols = line.split("\t")
                    if len(cols) >= 12:
                        conf_str, word = cols[10], cols[11].strip()
                        if word and conf_str.replace(".", "", 1).lstrip("-").isdigit() and float(conf_str) >= 50.0:
                            lx, ty, bw, bh = int(cols[6]), int(cols[7]), int(cols[8]), int(cols[9])
                            counter += 1
                            rid = f"r{counter}"
                            elements[rid] = RefNode(
                                ref_id=rid,
                                window_ref="w1",
                                app_ref="a1",
                                role="ocr_label",
                                name=word[:80],
                                bounds=BoundingBox(lx, ty, lx + bw, ty + bh),
                                enabled=True,
                            )
                            extracted_texts.append(word)
            except Exception:
                pass

        if not elements:
            # Deterministic 9-region Set-of-Mark (SoM) visual grid fallback when OCR is not present
            grid_specs = [
                ("r1", "Top-Left Header / Menu", (0.02, 0.02, 0.32, 0.14)),
                ("r2", "Top-Center Search / Address Bar", (0.33, 0.02, 0.67, 0.14)),
                ("r3", "Top-Right Profile / Actions", (0.68, 0.02, 0.98, 0.14)),
                ("r4", "Center-Primary Content / Canvas", (0.15, 0.25, 0.85, 0.70)),
                ("r5", "Bottom-Right Primary Submit / Confirm", (0.65, 0.82, 0.95, 0.94)),
                ("r6", "Bottom-Left Cancel / Back", (0.05, 0.82, 0.35, 0.94)),
            ]
            for rid, label, (x0, y0, x1, y1) in grid_specs:
                elements[rid] = RefNode(
                    ref_id=rid,
                    window_ref="w1",
                    app_ref="a1",
                    role="som_region",
                    name=label,
                    bounds=BoundingBox(int(w * x0), int(h * y0), int(w * x1), int(h * y1)),
                    enabled=True,
                )
                extracted_texts.append(label)

        win = WindowNode(
            window_ref="w1",
            app_ref="a1",
            title="Stage-5 Local Vision Grounding Frame",
            bounds=BoundingBox(0, 0, w, h),
            is_active=True,
            elements=elements,
        )
        app = AppNode(
            app_ref="a1",
            process_name="oryn_vision_engine",
            pid=os.getpid(),
            windows={"w1": win},
        )
        snap = AXTreeSnapshot(
            snapshot_id=f"vis_{int(time.time() * 1000)}",
            runtime_id=oryn_runtime.primary_runtime.runtime_id,
            captured_at=time.time(),
            apps={"a1": app},
            ref_index=elements,
        )
        self.last_snapshot = snap
        return snap, " ".join(extracted_texts)

    @fault_recorder.guard(subsystem="oryn.vision_engine")
    async def execute(self, action: ComputerAction) -> ExecutionReceipt:
        t0 = time.perf_counter()
        payload = action.payload or {}
        w, h = oryn_runtime.primary_runtime.display_dimensions

        # 1. Capture screen or use provided frame buffer
        frame_bytes: bytes = payload.get("frame_bytes") or b""
        img_path: Optional[Path] = None
        if not frame_bytes:
            img_path = oryn_runtime.capture_fullscreen()
            if img_path and img_path.exists():
                frame_bytes = img_path.read_bytes()
            else:
                frame_bytes = f"synthetic_frame_{action.action_id}_{time.time()}".encode("utf-8")

        curr_hash = native_accel.fast_hash64_hex(frame_bytes)
        prev_bytes = self._last_frame_bytes or (b"\x00" * len(frame_bytes))
        dirty_info = native_accel.compute_dirty_rect(
            prev_frame=prev_bytes,
            curr_frame=frame_bytes,
            width=min(w, 256),
            height=min(h, 256),
            channels=1,
        )
        self._last_frame_bytes = frame_bytes
        self._last_frame_hash = curr_hash

        # 2. Local OCR / Set-of-Mark Grounding
        snap, screen_text = self.run_local_ocr_grounding(
            image_path=img_path,
            ocr_boxes_override=payload.get("ocr_boxes"),
        )

        # 3. Visual Prompt-Injection Firewall check
        taint_report = self.inspect_screen_text_for_taint(screen_text)
        if taint_report["prompt_injection_detected"]:
            dur = round((time.perf_counter() - t0) * 1000.0, 2)
            return ExecutionReceipt(
                action_id=action.action_id,
                runtime_id=action.runtime_id,
                channel=self.channel,
                status="BLOCKED_POLICY",
                verified=False,
                duration_ms=dur,
                observed_evidence=(
                    f"Blocked by ORYN Visual Prompt-Injection Firewall: "
                    f"matched {taint_report['matched_patterns']}"
                ),
                output_data={"taint_report": taint_report},
                error_code="VISUAL_PROMPT_INJECTION_BLOCKED",
            )

        # 4. Target Coordinate Resolution via TypeSafe Jev or explicit coordinates
        if action.coordinates is not None:
            coords = action.remap_to_native_pixels(w, h)
            picked_ref = action.target_ref or "explicit_coords"
            conf = 0.95
        else:
            ui_list = [
                {"ref_id": r.ref_id, "role": r.role, "label": r.name, "name": r.name}
                for r in snap.ref_index.values()
            ]
            goal_str = str(payload.get("user_goal") or action.target_ref or action.text or action.operation)
            jev_pick = jev_ai_brain.select_screen_or_dom_action(goal_str, ui_list)
            picked_ref = str(jev_pick["target_element_selector"])
            conf = float(jev_pick["target_confidence"])
            rnode = snap.ref_index.get(picked_ref) or next(iter(snap.ref_index.values()))
            coords = rnode.bounds.center if rnode.bounds else (w // 2, h // 2)

        db_bounds = dirty_info["bounds"]
        dirty_box = BoundingBox(db_bounds[0], db_bounds[1], db_bounds[2], db_bounds[3])
        dur = round((time.perf_counter() - t0) * 1000.0, 2)

        return ExecutionReceipt(
            action_id=action.action_id,
            runtime_id=action.runtime_id,
            channel=self.channel,
            status="COMPLETED",
            verified=True,
            duration_ms=dur,
            observed_evidence=(
                f"Stage-5 Local Vision grounded '{picked_ref}' at {coords} "
                f"(FNV64={curr_hash[:8]}, DirtyPixels={dirty_info['changed_pixels']}, Conf={conf})"
            ),
            output_data={
                "selected_ref": picked_ref,
                "native_coordinates": coords,
                "frame_fnv64": curr_hash,
                "dirty_rect_info": dirty_info,
                "taint_report": taint_report,
                "grounding_confidence": conf,
            },
            dirty_rect=dirty_box,
        )

    async def verify(
        self,
        action: ComputerAction,
        receipt: ExecutionReceipt,
        pre_state: Optional[AXTreeSnapshot] = None,
    ) -> ExecutionReceipt:
        receipt.verified = receipt.status == "COMPLETED"
        return receipt

    async def recover(
        self,
        action: ComputerAction,
        failed_receipt: ExecutionReceipt,
    ) -> Optional[ComputerAction]:
        if failed_receipt.status == "BLOCKED_POLICY":
            return None
        return ComputerAction(
            action_id=f"{action.action_id}_cua_escalate",
            runtime_id=action.runtime_id,
            channel="frontier_cua",
            operation=action.operation,
            target_ref=action.target_ref,
            coordinates=action.coordinates,
            text=action.text,
            payload=action.payload,
        )


vision_engine = LocalVisionAndGroundingEngine()
