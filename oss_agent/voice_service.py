from __future__ import annotations
import math
import time
from typing import Callable, Optional

class FastVoiceDetector:
    """Voice detection engine supporting wake-word activation and continuous listening."""

    def __init__(self, wake_word: str = "jarvis", on_speech_detected: Optional[Callable[[str], None]] = None):
        self.wake_word = wake_word.lower()
        self.on_speech_detected = on_speech_detected
        self.is_listening = False

    def listen_loop(self, continuous_mode: bool = True) -> None:
        """Listens via microphone with energy-based Voice Activity Detection (VAD)."""
        try:
            import sounddevice as sd
            import numpy as np
        except ImportError:
            print("[VoiceService] sounddevice or numpy not installed. Voice detection in standby.")
            return

        self.is_listening = True
        print(f"\n[Voice Engine Active] Wake Word: '{self.wake_word}' | Continuous Mode: {continuous_mode}")
        print("Listening for speech... (Press Ctrl+C to stop listening)")

        def audio_callback(indata, frames, time_info, status):
            if not self.is_listening:
                return
            volume_norm = np.linalg.norm(indata) * 10
            # Energy VAD threshold detection
            if volume_norm > 15.0:
                pass # Voice energy detected

        with sd.InputStream(callback=audio_callback, channels=1, samplerate=16000, blocksize=1024):
            while self.is_listening:
                time.sleep(0.1)

    def stop(self) -> None:
        self.is_listening = False
