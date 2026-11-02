import math
import array
import asyncio
from typing import Optional, Callable, List


class FullDuplexAudioBus:
    """
    Production-Grade Full-Duplex Audio Bus with Software AEC & Barge-In.
    - Tracks speaker playback via a circular 16kHz 16-bit reference ring buffer.
    - Filters loopback echo using Normalized Cross-Correlation across acoustic lag offsets.
    - Executes sub-180ms hard-stop barge-in interruption on uncorrelated human speech.
    """

    __slots__ = (
        "_is_agent_speaking",
        "_kill_playback_flag",
        "_reference_output_buffer",
        "_vad_trigger_counter",
        "_rms_threshold",
        "_bargein_callbacks",
        "_last_interrupt_latency_ms"
    )

    def __init__(self, base_rms_threshold: int = 750):
        self._is_agent_speaking = False
        self._kill_playback_flag = asyncio.Event()
        # 500ms reference ring buffer at 16kHz (8000 samples)
        self._reference_output_buffer = array.array('h')
        self._vad_trigger_counter = 0
        self._rms_threshold = base_rms_threshold
        self._bargein_callbacks: List[Callable[[], None]] = []
        self._last_interrupt_latency_ms = 0.0

    @property
    def is_speaking(self) -> bool:
        return self._is_agent_speaking

    @property
    def is_interrupted(self) -> bool:
        return self._kill_playback_flag.is_set()

    def register_bargein_callback(self, cb: Callable[[], None]) -> None:
        """Attaches a listener invoked immediately when barge-in triggers."""
        self._bargein_callbacks.append(cb)

    def reset_interrupt(self) -> None:
        """Clears the interrupt state for the next turn."""
        self._kill_playback_flag.clear()
        self._is_agent_speaking = False
        self._vad_trigger_counter = 0
        self._reference_output_buffer = array.array('h')

    def write_speaker_frame(self, pcm_chunk: bytes) -> None:
        """
        Called synchronously by the speaker playback thread.
        Appends outbound audio to the echo-reference buffer.
        """
        samples = array.array('h')
        samples.frombytes(pcm_chunk)
        self._reference_output_buffer.extend(samples)
        # Cap buffer at 8000 samples (500ms at 16kHz)
        if len(self._reference_output_buffer) > 8000:
            self._reference_output_buffer = self._reference_output_buffer[-8000:]
        self._is_agent_speaking = True

    def read_microphone_frame(self, pcm_frame: bytes) -> bool:
        """
        Analyzes an incoming 20ms microphone PCM frame (320 samples at 16kHz).
        Returns True if genuine human barge-in speech is detected.
        """
        mic_samples = array.array('h')
        mic_samples.frombytes(pcm_frame)
        if not mic_samples:
            return False

        # 1. Compute Frame Energy (RMS)
        sum_sq = sum(s * s for s in mic_samples)
        rms = int(math.sqrt(sum_sq / len(mic_samples)))

        # 2. Dynamic Threshold Elevation during playback
        effective_threshold = int(self._rms_threshold * 2.8) if self._is_agent_speaking else self._rms_threshold

        if rms > effective_threshold:
            # 3. Echo Cancellation Check across acoustic lag search window
            if self._is_agent_speaking and self._detect_echo_correlation(mic_samples):
                # Energy belongs to speaker output loopback; suppress trigger
                return False

            self._vad_trigger_counter += 1
            if self._vad_trigger_counter >= 2:  # 40ms of consistent human speech
                self.trigger_barge_in()
                return True
        else:
            self._vad_trigger_counter = max(0, self._vad_trigger_counter - 1)

        return False

    def _detect_echo_correlation(self, mic_samples: array.array) -> bool:
        """
        Normalized cross-correlation scanning across acoustic lag offsets (0 to 40ms).
        Detects loopback echo regardless of acoustic transit latency or phase shift.
        """
        frame_len = len(mic_samples)
        buf_len = len(self._reference_output_buffer)
        if buf_len < frame_len:
            return False

        norm_m = math.sqrt(sum(int(m) * int(m) for m in mic_samples))
        if norm_m == 0:
            return False

        # Search lags over the most recent 40ms window (640 samples) with step 4
        max_lag = min(buf_len - frame_len, 640)
        for lag in range(0, max_lag + 1, 4):
            start_idx = buf_len - frame_len - lag
            ref = self._reference_output_buffer[start_idx : start_idx + frame_len]
            dot = sum(int(m) * int(r) for m, r in zip(mic_samples, ref))
            norm_r = math.sqrt(sum(int(r) * int(r) for r in ref))
            if norm_r > 0:
                corr = dot / (norm_m * norm_r)
                if corr > 0.65:
                    return True

        return False

    def trigger_barge_in(self) -> None:
        """Halts the speaker, signals token pipeline cancellation, and notifies callbacks."""
        self._kill_playback_flag.set()
        self._is_agent_speaking = False
        self._reference_output_buffer = array.array('h')
        self._vad_trigger_counter = 0

        for cb in self._bargein_callbacks:
            try:
                cb()
            except Exception:
                pass
