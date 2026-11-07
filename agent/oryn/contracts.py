from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

ChannelType = Literal[
    "native_api",
    "dom",
    "cdp",
    "accessibility",
    "vision",
    "frontier_cua",
]

CoordinateSpace = Literal[
    "NATIVE_DESKTOP_PX",
    "SCALED_XGA_1024x768",
    "SCALED_WXGA_1280x800",
    "SCALED_FWXGA_1366x768",
    "GEMINI_NORMALIZED_1000",
    "NORMALIZED_0_1",
]

OperationType = Literal[
    "click",
    "double_click",
    "triple_click",
    "right_click",
    "middle_click",
    "mouse_down",
    "mouse_up",
    "move",
    "drag",
    "type",
    "keypress",
    "hold_key",
    "scroll",
    "wait",
    "select_option",
    "navigate",
    "invoke_api",
    "execute_js",
    "screenshot",
]


@dataclass(frozen=True, slots=True)
class BoundingBox:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def center(self) -> Tuple[int, int]:
        return (self.left + self.right) // 2, (self.top + self.bottom) // 2

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x <= self.right and self.top <= y <= self.bottom

    def to_tuple(self) -> Tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)


@dataclass(slots=True)
class RefNode:
    """Compact HCU/UIA-compatible actionable element reference (`r1`..`rN`)."""

    ref_id: str
    window_ref: str
    app_ref: str
    role: str
    name: str
    value: str = ""
    bounds: Optional[BoundingBox] = None
    enabled: bool = True
    focused: bool = False
    checked: Optional[bool] = None
    dom_selector: str = ""
    backend_node_id: Optional[int] = None
    os_handle: Optional[int] = None

    def fingerprint(self) -> str:
        b_str = f"{self.bounds.to_tuple()}" if self.bounds else "none"
        raw = f"{self.app_ref}|{self.window_ref}|{self.role}|{self.name}|{self.dom_selector}|{b_str}"
        return hashlib.blake2b(raw.encode("utf-8"), digest_size=8).hexdigest()

    def to_compact_line(self) -> str:
        b = f" @{self.bounds.left},{self.bounds.top},{self.bounds.right},{self.bounds.bottom}" if self.bounds else ""
        val = f" val={self.value!r}" if self.value else ""
        state = " [focused]" if self.focused else ("" if self.enabled else " [disabled]")
        return f"[{self.ref_id}] {self.role} {self.name!r}{val}{state}{b}"


@dataclass(slots=True)
class WindowNode:
    """Window or Browser Tab reference (`w1`..`wN`) owned by an application (`aN`)."""

    window_ref: str
    app_ref: str
    title: str
    bounds: Optional[BoundingBox] = None
    is_active: bool = True
    is_modal: bool = False
    url: str = ""
    os_hwnd: Optional[int] = None
    cdp_target_id: str = ""
    elements: Dict[str, RefNode] = field(default_factory=dict)


@dataclass(slots=True)
class AppNode:
    """Running Application reference (`a1`..`aN`)."""

    app_ref: str
    process_name: str
    pid: int
    windows: Dict[str, WindowNode] = field(default_factory=dict)


@dataclass(slots=True)
class AXTreeSnapshot:
    """Unified semantic snapshot across Desktop AX/UIA, Android uiautomator, and Browser CDP."""

    snapshot_id: str
    runtime_id: str
    captured_at: float
    apps: Dict[str, AppNode] = field(default_factory=dict)
    ref_index: Dict[str, RefNode] = field(default_factory=dict)

    def render_compact_tree(self, max_elements: int = 250) -> str:
        lines: List[str] = []
        count = 0
        for app in self.apps.values():
            lines.append(f"[{app.app_ref}] App: {app.process_name} (pid={app.pid})")
            for win in app.windows.values():
                active_tag = " *ACTIVE*" if win.is_active else ""
                url_tag = f" url={win.url}" if win.url else ""
                lines.append(f"  └── [{win.window_ref}] Window: {win.title!r}{active_tag}{url_tag}")
                for ref in win.elements.values():
                    if count >= max_elements:
                        lines.append(f"      ... ({len(self.ref_index) - count} more elements truncated)")
                        return "\n".join(lines)
                    lines.append(f"      ├── {ref.to_compact_line()}")
                    count += 1
        return "\n".join(lines)

    def layout_hash(self) -> str:
        sigs = [f"{rid}:{r.fingerprint()}" for rid, r in sorted(self.ref_index.items())]
        return hashlib.sha256("|".join(sigs).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class AXTreeDiff:
    pre_snapshot_id: str
    post_snapshot_id: str
    added_refs: List[str]
    removed_refs: List[str]
    value_changed_refs: List[str]
    focus_changed_to: Optional[str]
    active_window_changed: bool
    modal_appeared: bool

    @property
    def has_meaningful_change(self) -> bool:
        return bool(
            self.added_refs
            or self.removed_refs
            or self.value_changed_refs
            or self.focus_changed_to
            or self.active_window_changed
            or self.modal_appeared
        )


@dataclass(frozen=True, slots=True)
class ComputerAction:
    """Immutable Universal Action Contract shared by all 6 ORYN execution channels."""

    action_id: str
    runtime_id: str
    channel: ChannelType
    operation: OperationType
    target_ref: Optional[str] = None
    coordinates: Optional[Tuple[int, int]] = None
    drag_to_coordinates: Optional[Tuple[int, int]] = None
    coordinate_space: CoordinateSpace = "NATIVE_DESKTOP_PX"
    source_image_size: Optional[Tuple[int, int]] = None
    text: Optional[str] = None
    keys: Tuple[str, ...] = ()
    scroll_delta: Tuple[int, int] = (0, 0)
    wait_ms: int = 0
    settle_ui: bool = True
    payload: Dict[str, Any] = field(default_factory=dict)
    expected_window_ref: Optional[str] = None
    expected_ref_fingerprint: Optional[str] = None
    expected_postconditions: Tuple[str, ...] = ("state_or_dom_changed",)
    risk_class: str = "read"
    idempotency_key: str = ""
    timeout_ms: int = 10000
    requires_verification: bool = True

    def remap_to_native_pixels(self, native_width: int, native_height: int) -> Tuple[int, int]:
        if self.coordinates is None:
            raise ValueError(f"Action {self.action_id} has no coordinates to remap.")
        x_raw, y_raw = self.coordinates

        if self.coordinate_space == "NATIVE_DESKTOP_PX":
            nx, ny = x_raw, y_raw
        elif self.coordinate_space == "GEMINI_NORMALIZED_1000":
            nx = round((x_raw / 1000.0) * native_width)
            ny = round((y_raw / 1000.0) * native_height)
        elif self.coordinate_space == "NORMALIZED_0_1":
            nx = round(float(x_raw) * native_width)
            ny = round(float(y_raw) * native_height)
        elif self.coordinate_space == "SCALED_XGA_1024x768":
            nx = round(x_raw * (native_width / 1024.0))
            ny = round(y_raw * (native_height / 768.0))
        elif self.coordinate_space == "SCALED_WXGA_1280x800":
            nx = round(x_raw * (native_width / 1280.0))
            ny = round(y_raw * (native_height / 800.0))
        elif self.coordinate_space == "SCALED_FWXGA_1366x768":
            nx = round(x_raw * (native_width / 1366.0))
            ny = round(y_raw * (native_height / 768.0))
        elif self.source_image_size and self.source_image_size[0] > 0 and self.source_image_size[1] > 0:
            nx = round(x_raw * (native_width / float(self.source_image_size[0])))
            ny = round(y_raw * (native_height / float(self.source_image_size[1])))
        else:
            nx, ny = x_raw, y_raw

        clamped_x = max(0, min(native_width - 1, int(nx)))
        clamped_y = max(0, min(native_height - 1, int(ny)))
        return clamped_x, clamped_y


@dataclass(slots=True)
class ActionBatch:
    """Ref-bound speculative batch of up to 64 actions with mid-flight drift abort."""

    batch_id: str
    runtime_id: str
    actions: List[ComputerAction]
    pre_snapshot_hash: str = ""
    halt_on_unexpected_modal: bool = True
    max_batch_size: int = 64

    def __post_init__(self) -> None:
        if len(self.actions) > self.max_batch_size:
            raise ValueError(
                f"ActionBatch {self.batch_id} has {len(self.actions)} actions; maximum allowed is {self.max_batch_size}."
            )


@dataclass(slots=True)
class ExecutionReceipt:
    action_id: str
    runtime_id: str
    channel: ChannelType
    status: Literal["COMPLETED", "FAILED", "STALE_TARGET_ABORTED", "BLOCKED_POLICY"]
    verified: bool
    duration_ms: float
    observed_evidence: str
    output_data: Dict[str, Any] = field(default_factory=dict)
    ax_diff: Optional[AXTreeDiff] = None
    dirty_rect: Optional[BoundingBox] = None
    error_code: str = ""
    recovery_suggestion: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ExecutionDriver(ABC):
    """Universal Driver Contract that all 6 ORYN execution stages implement."""

    channel: ChannelType

    @abstractmethod
    async def discover(self, target_app_or_url: str) -> Dict[str, Any]:
        """Probes whether the target application or webpage is controllable via this channel."""

    @abstractmethod
    async def execute(self, action: ComputerAction) -> ExecutionReceipt:
        """Executes a single validated ComputerAction and returns its raw receipt."""

    @abstractmethod
    async def verify(
        self,
        action: ComputerAction,
        receipt: ExecutionReceipt,
        pre_state: Optional[AXTreeSnapshot] = None,
    ) -> ExecutionReceipt:
        """Verifies postconditions (API return, DOM/AX diff, or pixel change) and updates receipt."""

    @abstractmethod
    async def recover(
        self,
        action: ComputerAction,
        failed_receipt: ExecutionReceipt,
    ) -> Optional[ComputerAction]:
        """Attempts local channel recovery (e.g., refreshing stale ref) or returns None to escalate."""
