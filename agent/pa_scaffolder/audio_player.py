from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Optional


class UniversalAudioPlayer:
    """Universal High-Fidelity Audio Player.
    Plays raw audio / WAV files via PulseAudio (paplay), termux-media-player,
    or PC desktop utilities without requiring python-sounddevice.
    """

    CACHE_DIR = Path("workspace/audio_cache")

    def __init__(self):
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    def play_wav_file(self, wav_path: Path | str) -> bool:
        """Plays a WAV file through the fastest available system audio sink."""
        p_str = str(Path(wav_path).resolve())

        # 1. PulseAudio daemon (Fastest, zero latency in Termux and Linux PC)
        if shutil.which("paplay"):
            try:
                subprocess.run(["paplay", p_str], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except Exception:
                pass

        # 2. Native Termux Media Player
        if shutil.which("termux-media-player"):
            try:
                subprocess.run(["termux-media-player", "play", p_str], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except Exception:
                pass

        # 3. Standard Linux / macOS sinks
        for player in ["aplay", "afplay", "mpv", "play"]:
            if shutil.which(player):
                try:
                    subprocess.run([player, p_str], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return True
                except Exception:
                    pass

        return False

    def play_raw_pcm(self, pcm_data: bytes, sample_rate: int = 24000, channels: int = 1, sampwidth: int = 2) -> bool:
        """Wraps raw PCM audio bytes (from Google Live or Kokoro) into a WAV container and plays it."""
        temp_wav = self.CACHE_DIR / "live_speech.wav"
        with wave.open(str(temp_wav), "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(sampwidth)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_data)

        return self.play_wav_file(temp_wav)


audio_player = UniversalAudioPlayer()
