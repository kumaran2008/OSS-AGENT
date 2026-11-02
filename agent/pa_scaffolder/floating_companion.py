import os
import sys
import time
import json
from dataclasses import dataclass
from typing import Optional, Dict, Any

# Reaction and Eye States
class FaceState:
    IDLE = "IDLE"             # Calm blink, natural gaze drift
    CURIOSITY = "CURIOSITY"   # Darting glance (file hover/typing)
    THINKING = "THINKING"     # Subtle pulse/glow, looking up
    CELEBRATE = "CELEBRATE"   # Joyful curved squint (tests passed)
    ALERT = "ALERT"           # Wide eyes, attention needed
    GHOST = "GHOST"           # Semi-transparent click-through

@dataclass
class UITheme:
    name: str = "CyberNeon"
    eye_color: str = "#00FFCC"
    pupil_color: str = "#003322"
    bubble_bg: str = "rgba(20, 20, 30, 0.85)"
    text_color: str = "#E0E0E0"
    accent_color: str = "#FF007F"


class FloatingCompanionBridge:
    """
    Cross-platform controller for the Always-on-Top Floating Face UI.
    Manages eye expressions, speech bubble streaming, and ghost mode.
    """
    def __init__(self, agent_name: str = "Hype", theme: Optional[UITheme] = None):
        self.agent_name = agent_name
        self.theme = theme or UITheme()
        self.state = FaceState.IDLE
        self.is_termux = "ANDROID_ROOT" in os.environ or "TERMUX_VERSION" in os.environ
        self.is_ghost_active = False

    def get_eye_matrix(self, state: Optional[str] = None) -> Dict[str, str]:
        """Returns ASCII/SVG eye representations for the active state."""
        st = state or self.state
        if st == FaceState.IDLE:
            return {"left": "●", "right": "●", "mouth": "_", "label": "Idle"}
        elif st == FaceState.CURIOSITY:
            return {"left": "◉", "right": "o", "mouth": "·", "label": "Observing"}
        elif st == FaceState.THINKING:
            return {"left": "◠", "right": "◠", "mouth": "—", "label": "Thinking"}
        elif st == FaceState.CELEBRATE:
            return {"left": "^", "right": "^", "mouth": "▿", "label": "Success!"}
        elif st == FaceState.ALERT:
            return {"left": "O", "right": "O", "mouth": "△", "label": "Attention Needed"}
        elif st == FaceState.GHOST:
            return {"left": "·", "right": "·", "mouth": " ", "label": "Ghost Mode"}
        return {"left": "●", "right": "●", "mouth": "_", "label": "Ready"}

    def set_state(self, state: str):
        """Updates internal emotional state."""
        self.state = state

    def render_widget_frame(self, message: Optional[str] = None) -> str:
        """
        Renders a compact, high-density widget frame.
        Can be piped to native window shells or terminal overlays.
        """
        eyes = self.get_eye_matrix()
        bubble = ""
        if message:
            bubble = f"┌────────────────────────────────┐\n│ {self.agent_name}: {message[:26]:<26} │\n└───────────┬────────────────────┘\n            ▼\n"
        
        face = (
            f"{bubble}"
            f" ╭───────────╮\n"
            f" │  {eyes['left']}     {eyes['right']}  │  [{eyes['label']}]\n"
            f" │     {eyes['mouth']}     │\n"
            f" ╰───────────╯"
        )
        return face

    def stream_speech(self, text: str, chunk_delay: float = 0.02):
        """Simulates typewriter streaming to the thought bubble."""
        for i in range(1, len(text) + 1):
            sys.stdout.write(f"\r[{self.agent_name} Bubble]: {text[:i]}")
            sys.stdout.flush()
            time.sleep(chunk_delay)
        print()

    def set_ghost_mode(self, enabled: bool):
        """Toggles click-through and transparency mode."""
        self.is_ghost_active = enabled
        if enabled:
            self.set_state(FaceState.GHOST)
        else:
            self.set_state(FaceState.IDLE)
