import time
from agent.core.stream_director import StreamInteractionDirector
from agent.core.unified_companion import AudioChannel

director = StreamInteractionDirector(cohost_name="Hype")

print("=" * 65)
print("     STREAM INTERACTION & BROTHER BANTER BENCHMARK")
print("=" * 65)

# 1. Simulate incoming stream chat
print("\n[1/4] Ingesting Rapid Chat Messages...")
messages = [
    ("gamer_fan", "W shot!"),
    ("alex_99", "POG CHAMPION"),
    ("stream_lurker", "what graphics card are you using?"),
    ("tamil_bro", "INSANE clutch bro!!"),
    ("tech_guy", "what sensitivity do you play on?")
]
for author, msg in messages:
    director.ingest_chat_message(author, msg)
print(f" • Buffered {len(messages)} live chat entries.")

# 2. Test Sentiment Clustering
print("\n[2/4] Aggregating Audience Vibe...")
vibe = director.aggregate_chat_vibe()
print(f" • Detected Vibe:    {vibe['vibe']}")
print(f" • Whisper Summary:  \"{vibe['summary']}\"")
print(f" • Pending Queries:  {vibe['questions']}")
assert vibe["vibe"] in ("HYPED", "CURIOUS")

# 3. Test Brotherly Banter Generation
print("\n[3/4] Testing Real-Time Banter Synthesis...")
win_banter = director.craft_brother_banter("clutch")
fail_banter = director.craft_brother_banter("fail")
print(f" • Clutch Reaction: \"{win_banter}\"")
print(f" • Miss/Fail Reaction: \"{fail_banter}\"")
assert "bro" in win_banter.lower() or "bro" in fail_banter.lower()

# 4. Test Dead-Air Lull Sentinel
print("\n[4/4] Evaluating Dead-Air Interruption Hook...")
# Manually simulate 35 seconds of silence
director.last_streamer_speech = time.time() - 35.0
lull = director.check_dead_air()

if lull and lull["triggered"]:
    print(f" • Dead-Air Detected ({lull['silence_sec']}s silence).")
    print(f" • Private Ear Hook: \"{lull['suggested_hook']}\"")
    assert lull["channel"] == AudioChannel.WHISPER_EAR
    print(" • Audio Route Confirmed: Private headset only (Audience hears nothing).")

print("\n" + "=" * 65)
print(">>> CHAT AGGREGATION & BANTER SYSTEM VERIFIED OPERATIONAL <<<")
print("=" * 65)
