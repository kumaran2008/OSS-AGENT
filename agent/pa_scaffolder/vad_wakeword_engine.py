import array
import math
import re
import random
from enum import Enum
from typing import List, Tuple, Optional, Dict, Any

from agent.pa_scaffolder.agent_config import AgentConfig


class VADState(str, Enum):
    SILENCE = "silence"
    SPEECH = "speech"


class PurePythonVAD:
    """Zero-Dependency Voice Activity Detector using array.array('h')."""

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_duration_ms: int = 30,
        energy_multiplier: float = 2.4,
        silence_timeout_sec: float = 1.0,
        pre_speech_padding_sec: float = 0.3
    ):
        self.sample_rate = sample_rate
        self.frame_size_samples = int(sample_rate * (frame_duration_ms / 1000.0))
        self.frame_size_bytes = self.frame_size_samples * 2
        self.energy_multiplier = energy_multiplier

        self.ambient_noise_floor = 180.0
        self.min_speech_threshold = 320.0

        self.state = VADState.SILENCE
        self.silence_timeout_frames = int(silence_timeout_sec / (frame_duration_ms / 1000.0))
        self.consecutive_silence_frames = 0
        self.consecutive_speech_frames = 0

        self.pre_speech_max_frames = max(1, int(pre_speech_padding_sec / (frame_duration_ms / 1000.0)))
        self._pre_speech_buffer: List[bytes] = []

    def calculate_frame_rms(self, frame_bytes: bytes) -> float:
        num_samples = len(frame_bytes) // 2
        if num_samples == 0:
            return 0.0
        samples = array.array("h")
        samples.frombytes(frame_bytes[:num_samples * 2])
        return math.sqrt(sum(s * s for s in samples) / num_samples)

    def process_frame(self, frame_bytes: bytes) -> Tuple[VADState, bool]:
        rms = self.calculate_frame_rms(frame_bytes)
        threshold = max(self.min_speech_threshold, self.ambient_noise_floor * self.energy_multiplier)
        utterance_finished = False

        if rms >= threshold:
            self.consecutive_speech_frames += 1
            self.consecutive_silence_frames = 0
            if self.state == VADState.SILENCE and self.consecutive_speech_frames >= 2:
                self.state = VADState.SPEECH
        else:
            self.consecutive_speech_frames = 0
            if self.state == VADState.SILENCE:
                self.ambient_noise_floor = (self.ambient_noise_floor * 0.96) + (rms * 0.04)
                self._pre_speech_buffer.append(frame_bytes)
                if len(self._pre_speech_buffer) > self.pre_speech_max_frames:
                    self._pre_speech_buffer.pop(0)
            elif self.state == VADState.SPEECH:
                self.consecutive_silence_frames += 1
                if self.consecutive_silence_frames >= self.silence_timeout_frames:
                    self.state = VADState.SILENCE
                    utterance_finished = True
                    self.consecutive_silence_frames = 0

        return self.state, utterance_finished

    def pop_pre_speech_lead(self) -> bytes:
        lead = b"".join(self._pre_speech_buffer)
        self._pre_speech_buffer.clear()
        return lead


class WakeWordGatingFilter:
    """
    Dynamic Wake-Word Filter.
    Adapts to user-configured agent name and filters platform STT error tokens.
    """

    # Common STT error strings from Android / Termux:API
    STT_ERROR_PATTERNS = re.compile(
        r"^(ERROR:\s*)?(ERROR_NO_MATCH|ERROR_SPEECH_TIMEOUT|ERROR_NETWORK|ERROR_AUDIO|ERROR_SERVER)",
        re.IGNORECASE
    )

    def __init__(self, config: Optional[AgentConfig] = None):
        self.config = config or AgentConfig()
        self._recompile()

    def _recompile(self):
        self.wake_pattern = self.config.build_wake_pattern() if hasattr(self.config, 'build_wake_pattern') else re.compile(r'\b(?:friday|jarvis|hey\s+friday)\b', re.IGNORECASE)

    def is_stt_error(self, text: str) -> bool:
        """Returns True if input is an engine failure token rather than user speech."""
        clean = text.strip()
        return bool(self.STT_ERROR_PATTERNS.search(clean))

    def evaluate_transcript(self, raw_transcript: str) -> Dict[str, Any]:
        clean = raw_transcript.strip()

        # 1. Discard hardware error strings immediately
        if not clean or self.is_stt_error(clean):
            return {
                "wake_detected": False,
                "command_payload": "",
                "interaction_mode": "IGNORE",
                "is_error": True
            }

        # 2. Check for configured wake words
        match = self.wake_pattern.search(clean)
        if not match:
            return {
                "wake_detected": False,
                "command_payload": "",
                "interaction_mode": "IGNORE",
                "is_error": False
            }

        wake_matched = match.group(0)
        after_wake = clean[match.end():].strip()
        before_wake = clean[:match.start()].strip()
        command = f"{before_wake} {after_wake}".strip()
        command = re.sub(r"^[,\.\?!:\s]+", "", command).strip()

        if len(command) > 0:
            mode = "SINGLE_SHOT_COMMAND"
            ack_reply = None
        else:
            mode = "AWAKE_STANDBY"
            ack_reply = random.choice(self.config.acknowledgments)

        return {
            "wake_detected": True,
            "matched_wake_word": wake_matched,
            "command_payload": command,
            "interaction_mode": mode,
            "standby_acknowledgment": ack_reply,
            "is_error": False
        }
