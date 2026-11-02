from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
import wave
from pathlib import Path
from typing import AsyncGenerator, Optional


class AdaptiveAudioHAL:
    """Production Hardware Abstraction Layer for Full-Duplex Audio I/O.
    - Manages zero-latency 24kHz PulseAudio streaming playback.
    - Manages continuous 16kHz microphone capture stream.
    - Hardware Acoustic Echo Cancellation (AEC) gate.
    """

    CACHE_DIR = Path("workspace/audio_cache")

    def __init__(self):
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.is_speaking = False
        self._playback_proc: Optional[subprocess.Popen] = None
        self._last_speech_time = 0.0

    # -------------------------------------------------------------------------
    # Output: Low-Latency PCM Playback Pipe (Mouth)
    # -------------------------------------------------------------------------
    def _ensure_playback_pipe(self, sample_rate: int = 24000) -> Optional[subprocess.Popen]:
        if self._playback_proc and self._playback_proc.poll() is None:
            return self._playback_proc

        if shutil.which("pacat"):
            try:
                self._playback_proc = subprocess.Popen(
                    ["pacat", "--playback", f"--rate={sample_rate}", "--channels=1", "--format=s16le"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return self._playback_proc
            except Exception:
                self._playback_proc = None

        return None

    def play_pcm_chunk(self, pcm_bytes: bytes, sample_rate: int = 24000) -> bool:
        """Writes raw PCM audio directly to the audio driver pipe."""
        if not pcm_bytes:
            return False

        self.is_speaking = True
        self._last_speech_time = time.time()

        proc = self._ensure_playback_pipe(sample_rate)
        if proc and proc.stdin:
            try:
                proc.stdin.write(pcm_bytes)
                proc.stdin.flush()
                return True
            except Exception:
                self._playback_proc = None

        # Fallback to standard WAV playback if pipe is unavailable
        return self.play_pcm(pcm_bytes, sample_rate=sample_rate)

    def enable_os_echo_cancellation(self) -> bool:
        """Loads PulseAudio/PipeWire WebRTC Acoustic Echo Cancellation module on workstation hosts."""
        if shutil.which("pactl"):
            try:
                out = subprocess.check_output(["pactl", "list", "modules", "short"], stderr=subprocess.DEVNULL, timeout=2.0).decode("utf-8", errors="ignore")
                if "module-echo-cancel" not in out:
                    subprocess.run(
                        ["pactl", "load-module", "module-echo-cancel", "aec_method=webrtc"],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=2.0,
                    )
                return True
            except Exception:
                pass
        return False

    def check_rms_barge_in(self, pcm_chunk: bytes, threshold: float = 450.0) -> bool:
        """Computes 16-bit PCM Root Mean Square (RMS) energy via NumPy (Python 3.13 compatible).
        If speech energy exceeds threshold while Friday is speaking, triggers immediate Barge-In (<5ms).
        """
        if not self.is_speaking or not pcm_chunk or len(pcm_chunk) < 2:
            return False

        try:
            import numpy as np
            usable_len = (len(pcm_chunk) // 2) * 2
            samples = np.frombuffer(pcm_chunk[:usable_len], dtype=np.int16).astype(np.float32)
            rms = float(np.sqrt(np.mean(samples * samples))) if samples.size > 0 else 0.0
            if rms > threshold:
                self.interrupt_playback()
                return True
        except Exception:
            pass
        return False

    def interrupt_playback(self) -> bool:
        """Immediate Barge-In: Kills active audio output pipe and unlocks microphone stream in <5ms."""
        was_speaking = self.is_speaking
        self.is_speaking = False
        self._last_speech_time = 0.0
        if self._playback_proc:
            try:
                self._playback_proc.kill()
            except Exception:
                pass
            self._playback_proc = None
        return was_speaking

    def close_playback_pipe(self) -> None:
        """Flushes and closes the playback pipe."""
        if self._playback_proc:
            try:
                if self._playback_proc.stdin:
                    self._playback_proc.stdin.close()
                self._playback_proc.wait(timeout=0.5)
            except Exception:
                pass
            self._playback_proc = None
        self.is_speaking = False

    def play_pcm(self, pcm_bytes: bytes, sample_rate: int = 24000, channels: int = 1) -> bool:
        """Writes PCM to WAV container and outputs via system audio sink."""
        out_wav = self.CACHE_DIR / "stream_chunk.wav"
        with wave.open(str(out_wav), "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
        return self.play_wav(out_wav)

    def play_wav(self, wav_path: Path | str) -> bool:
        p = Path(wav_path).resolve()
        if not p.exists():
            return False

        self.is_speaking = True
        self._last_speech_time = time.time()
        try:
            if shutil.which("paplay"):
                subprocess.run(["paplay", str(p)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            if shutil.which("termux-media-player"):
                subprocess.run(["termux-media-player", "play", str(p)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            for player in ["aplay", "afplay", "mpv", "play"]:
                if shutil.which(player):
                    subprocess.run([player, str(p)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return True
        except Exception:
            pass
        finally:
            self.is_speaking = False

        return False

    # -------------------------------------------------------------------------
    # Input: Continuous 16kHz Microphone Capture Stream (Ears)
    # -------------------------------------------------------------------------
    async def stream_mic_pcm(self, chunk_duration_sec: float = 0.1) -> AsyncGenerator[bytes, None]:
        """Continuously yields 16kHz 16-bit Mono PCM chunks.
        Applies echo-gate cancellation whenever Friday's speaker is active.
        """
        sample_rate = 16000
        bytes_per_sample = 2
        chunk_size = int(sample_rate * bytes_per_sample * chunk_duration_sec)  # 3200 bytes per 100ms
        silent_chunk = b"\x00" * chunk_size

        # 1. PulseAudio Stream Capture (Fastest on Linux / Termux)
        if shutil.which("parec"):
            proc = await asyncio.create_subprocess_exec(
                "parec",
                f"--rate={sample_rate}",
                "--channels=1",
                "--format=s16le",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                while proc.returncode is None:
                    # Echo-gate check
                    if self.is_speaking or (time.time() - self._last_speech_time < 0.4):
                        # Consume and drop audio frames while speaking to prevent self-looping
                        await proc.stdout.read(chunk_size)
                        yield silent_chunk
                        await asyncio.sleep(chunk_duration_sec)
                        continue

                    chunk = await proc.stdout.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
            finally:
                try:
                    proc.terminate()
                    await proc.wait()
                except Exception:
                    pass
            return

        # 2. FFmpeg ALSA/Pulse Input Stream
        if shutil.which("ffmpeg"):
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-f", "pulse",
                "-i", "default",
                "-f", "s16le",
                "-ar", str(sample_rate),
                "-ac", "1",
                "-",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                while proc.returncode is None:
                    if self.is_speaking or (time.time() - self._last_speech_time < 0.4):
                        await proc.stdout.read(chunk_size)
                        yield silent_chunk
                        await asyncio.sleep(chunk_duration_sec)
                        continue

                    chunk = await proc.stdout.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
            finally:
                try:
                    proc.terminate()
                    await proc.wait()
                except Exception:
                    pass
            return

        # 3. Non-blocking fallback
        while True:
            await asyncio.sleep(chunk_duration_sec)
            yield silent_chunk


audio_hal = AdaptiveAudioHAL()
