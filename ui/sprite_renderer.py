import sys
import threading
import time
from config.settings import settings

STATES = {
    "idle": ["( •_• )", "( •o• )"],
    "thinking": ["( ⊙_⊙ )", "( 🔍_⊙ )"],
    "working": ["(٩◕‿◕｡)۶", "(ง'-'︠)ง"],
    "troubled": ["( ; ಠ_ಠ)"],
    "sad": ["( T_T )", "( x_x )"],
    "happy": ["(＾▽＾)", "☆*:.｡.o(≧▽≦)o.｡.:*☆"],
}


class SpriteRenderer:
    """
    Purely cosmetic terminal companion. Reflects orchestrator state via
    set_state() calls — no input handling, no threads reading stdin.
    Safe by design: any internal failure is swallowed so a rendering bug
    can never break an actual agent run. Disabled automatically when
    stdout isn't a real terminal (e.g. piped output, CI, non-interactive).
    """

    def __init__(self):
        self.enabled = settings.ENABLE_SPRITE_UI and sys.stdout.isatty()
        self._frame_index = 0
        self._lock = threading.Lock()
        self._current_state = "idle"

    def set_state(self, state: str) -> None:
        if not self.enabled:
            return
        try:
            with self._lock:
                self._current_state = state if state in STATES else "idle"
                self._frame_index = 0
                self._render()
        except Exception:
            pass  # never let sprite rendering break a real run

    def _render(self) -> None:
        frames = STATES[self._current_state]
        frame = frames[self._frame_index % len(frames)]
        self._frame_index += 1
        sys.stdout.write(f"\r  {frame}  [{self._current_state}]\033[K")
        sys.stdout.flush()

    def newline(self) -> None:
        """Call before printing normal orchestrator output, so the sprite
        line doesn't get overwritten mid-word by the next print()."""
        if self.enabled:
            sys.stdout.write("\n")


sprite = SpriteRenderer()
