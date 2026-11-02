import time
import re
from typing import List, Dict, Any, Optional
from agent.core.unified_companion import AudioChannel


class StreamInteractionDirector:
    """
    Directs live stream audience engagement, dead-air prevention,
    and brotherly banter between streamer and AI co-host.
    """

    def __init__(self, cohost_name: str = "Hype"):
        self.cohost_name = cohost_name
        self.last_streamer_speech: float = time.time()
        self.chat_buffer: List[Dict[str, Any]] = []
        self.dead_air_threshold_sec: float = 30.0

    def register_streamer_voice_activity(self):
        """Resets dead-air tracking whenever the streamer speaks."""
        self.last_streamer_speech = time.time()

    def ingest_chat_message(self, author: str, message: str):
        """Buffers live incoming stream chat for semantic clustering."""
        self.chat_buffer.append({
            "author": author,
            "text": message.strip(),
            "time": time.time()
        })
        # Keep sliding window of latest 50 messages
        if len(self.chat_buffer) > 50:
            self.chat_buffer.pop(0)

    def aggregate_chat_vibe(self) -> Dict[str, Any]:
        """
        Summarizes audience sentiment and recurring questions
        so the streamer doesn't need to read raw chat lines.
        """
        if not self.chat_buffer:
            return {"vibe": "quiet", "summary": "Chat is currently quiet.", "questions": []}

        recent = self.chat_buffer[-20:]
        texts = [m["text"].lower() for m in recent]

        hype_count = sum(1 for t in texts if any(w in t for w in ["w", "pog", "insane", "crazy", "gg", "fire", "op"]))
        question_msgs = [m["text"] for m in recent if "?" in m["text"]]

        if hype_count >= 5:
            vibe = "HYPED"
            summary = "Chat is going crazy over that play!"
        elif len(question_msgs) >= 3:
            vibe = "CURIOUS"
            summary = f"Chat has questions. Most frequent: '{question_msgs[-1]}'"
        else:
            vibe = "CHILL"
            summary = "Chat is vibing and following along."

        return {
            "vibe": vibe,
            "summary": summary,
            "questions": question_msgs[-3:]
        }

    def check_dead_air(self) -> Optional[Dict[str, Any]]:
        """
        Detects awkward silence (>30s) and provides an organic conversation hook.
        """
        silence_duration = time.time() - self.last_streamer_speech
        if silence_duration >= self.dead_air_threshold_sec:
            vibe_data = self.aggregate_chat_vibe()
            if vibe_data["questions"]:
                prompt_line = f"Yo bro, chat is asking: '{vibe_data['questions'][0]}'—drop your take on that."
            else:
                prompt_line = "Room went a bit quiet bro. Want me to play some background hype music or check the next mission?"

            return {
                "triggered": True,
                "silence_sec": round(silence_duration, 1),
                "suggested_hook": prompt_line,
                "channel": AudioChannel.WHISPER_EAR
            }
        return None

    def craft_brother_banter(self, event_type: str, context: str = "") -> str:
        """
        Produces grounded, humorous brotherly responses rather than generic assistant lines.
        """
        evt = event_type.lower()
        if "clutch" in evt or "win" in evt:
            return "Clean shots bro! Finally hitting something today, let's go!"
        elif "fail" in evt or "miss" in evt or "death" in evt:
            return "Bro... we are definitely not clipping that one. Blame it on 200 ping."
        elif "ask_chat" in evt:
            vibe = self.aggregate_chat_vibe()
            return f"{vibe['summary']} They're loving the energy right now."
        elif "start_stream" in evt:
            return "Let's get it brother! Stream is live, audio is locked, and we're ready to roll."
        else:
            return f"Got you covered bro. {context}".strip()
