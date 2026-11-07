from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class ComputerAction:
    action_type: str  # click, type, scroll, key_press, execute_api, dom_eval
    target: str       # selector, coordinate, or API route
    value: Optional[str] = None
    coordinate_space: str = "NATIVE_PX" # NATIVE_PX, XGA, WXGA, GEMINI_1000

@dataclass
class ActionBatch:
    batch_id: str
    actions: List[ComputerAction] = field(default_factory=list)
    max_actions: int = 64

@dataclass
class ExecutionDriver:
    driver_name: str
    supported: bool = True
