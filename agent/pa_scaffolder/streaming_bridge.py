from agent.pa_scaffolder.full_duplex_bus import FullDuplexAudioBus
import re
import time
import asyncio
from pathlib import Path
from typing import AsyncGenerator, Optional, List, Dict, Any

from agent.pa_scaffolder.agent_config import AgentConfig
from agent.pa_scaffolder.audio_hardware import AdaptiveAudioHAL


class SentenceStreamChunker:
    """
    Intelligent Token-to-Sentence Stream Chunker.
    - Chunk 1: Cuts early on clause boundaries (3-5 words or punctuation) for sub-300ms TTFA.
    - Subsequent Chunks: Cuts on natural sentence punctuation for prosody.
    """

    EARLY_PUNCTUATION = re.compile(r"[,;:\.!\?\n]")
    SENTENCE_TERMINATORS = re.compile(r"[\.!\?\n]")

    def __init__(self, mode: str = "adaptive", min_first_words: int = 3):
        self.mode = mode  # "adaptive", "clause", "sentence"
        self.min_first_words = min_first_words
        self.is_first_chunk = True

    async def chunk_stream(self, token_stream: AsyncGenerator[str, None]) -> AsyncGenerator[str, None]:
        buffer = ""

        async for token in token_stream:
            buffer += token

            # Split logic based on user's streaming mode preference
            if self.mode == "adaptive" and self.is_first_chunk:
                words = buffer.strip().split()
                # If we have minimum words and hit ANY clause punctuation
                if len(words) >= self.min_first_words and self.EARLY_PUNCTUATION.search(buffer):
                    cut_idx = self._find_split_point(buffer, self.EARLY_PUNCTUATION)
                    if cut_idx > 0:
                        chunk = buffer[:cut_idx].strip()
                        buffer = buffer[cut_idx:].strip()
                        if chunk:
                            self.is_first_chunk = False
                            yield chunk

            elif self.mode == "clause":
                words = buffer.strip().split()
                if len(words) >= 3 and self.EARLY_PUNCTUATION.search(buffer):
                    cut_idx = self._find_split_point(buffer, self.EARLY_PUNCTUATION)
                    if cut_idx > 0:
                        chunk = buffer[:cut_idx].strip()
                        buffer = buffer[cut_idx:].strip()
                        if chunk:
                            yield chunk

            else:  # Standard sentence mode or subsequent adaptive chunks
                if self.SENTENCE_TERMINATORS.search(buffer):
                    cut_idx = self._find_split_point(buffer, self.SENTENCE_TERMINATORS)
                    if cut_idx > 0:
                        chunk = buffer[:cut_idx].strip()
                        buffer = buffer[cut_idx:].strip()
                        if chunk:
                            self.is_first_chunk = False
                            yield chunk

        # Yield any remaining text in the buffer
        tail = buffer.strip()
        if tail:
            yield tail

    def _find_split_point(self, text: str, regex: re.Pattern) -> int:
        match = regex.search(text)
        return match.end() if match else -1


class StreamingAudioPipeline:
    """
    Asynchronous Concurrent Synthesis & Playback Queue.
    Pipes sentence chunks directly to Kokoro / Edge-TTS while playing preceding audio.
    """

    SPECULATIVE_FILLERS = [
        "On it.",
        "Let's see.",
        "Checking that.",
        "Gotcha."
    ]

    def __init__(self, hal: Optional[AdaptiveAudioHAL] = None, config: Optional[AgentConfig] = None, duplex_bus: Optional[FullDuplexAudioBus] = None):
        self.hal = hal or AdaptiveAudioHAL()
        self.config = config or AgentConfig()
        self.duplex_bus = duplex_bus or FullDuplexAudioBus()
        self.text_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        self.audio_queue: asyncio.Queue[Optional[Path]] = asyncio.Queue()
        self.is_interrupted = False

    async def run_pipeline(
        self,
        token_stream: AsyncGenerator[str, None],
        on_first_audio_cb: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Executes parallel streaming:
        1. Producer: Tokens -> Chunks -> text_queue
        2. Worker 1: text_queue -> Audio Synthesis -> audio_queue
        3. Worker 2: audio_queue -> Sequential Speaker Playback
        """
        self.is_interrupted = False
        t_start = time.perf_counter()
        first_audio_played = False
        ttfa_ms = 0.0
        spoken_chunks: List[str] = []

        mode = getattr(self.config, "streaming_mode", "adaptive")
        min_words = 3
        if hasattr(self.config, "data") and isinstance(self.config.data, dict):
            min_words = self.config.data.get("first_chunk_min_words", 3)
        chunker = SentenceStreamChunker(mode=mode, min_first_words=min_words)

        # Worker 1: Parallel Audio Synthesizer
        async def synthesis_worker():
            while not self.is_interrupted:
                chunk_text = await self.text_queue.get()
                if chunk_text is None:
                    await self.audio_queue.put(None)
                    break
                
                # Synthesize chunk with user preferences (voice & speed)
                audio_file = await self.hal.synthesize_speech_async(
                    chunk_text,
                    voice=self.config.voice_name
                )
                await self.audio_queue.put(audio_file)
                self.text_queue.task_done()

        # Worker 2: Sequential Speaker Playback
        async def playback_worker():
            nonlocal first_audio_played, ttfa_ms
            while not self.is_interrupted:
                audio_path = await self.audio_queue.get()
                if audio_path is None:
                    break

                if not first_audio_played:
                    first_audio_played = True
                    ttfa_ms = (time.perf_counter() - t_start) * 1000.0
                    if on_first_audio_cb:
                        on_first_audio_cb(ttfa_ms)

                # Play audio chunk (Kokoro / Edge-TTS / System)
                await asyncio.to_thread(self.hal.play_audio, audio_path)
                self.audio_queue.task_done()

        # Launch background workers
        synth_task = asyncio.create_task(synthesis_worker())
        play_task = asyncio.create_task(playback_worker())

        # Producer: Feed chunks into text_queue
        async for chunk in chunker.chunk_stream(token_stream):
            if self.is_interrupted:
                break
            spoken_chunks.append(chunk)
            await self.text_queue.put(chunk)

        # Signal end of text
        await self.text_queue.put(None)

        # Await completion of synthesis and playback
        await synth_task
        await play_task

        total_duration_ms = (time.perf_counter() - t_start) * 1000.0

        return {
            "spoken_text": " ".join(spoken_chunks),
            "chunks_count": len(spoken_chunks),
            "ttfa_ms": round(ttfa_ms, 2),
            "total_ms": round(total_duration_ms, 2),
            "voice_used": self.config.voice_name,
            "speed": self.config.voice_speed
        }

    def interrupt(self):
        """Immediately stops all queued synthesis and playback."""
        self.is_interrupted = True
