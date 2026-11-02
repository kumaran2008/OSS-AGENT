import asyncio
from agent.pa_scaffolder.advanced_companion import (
    AdvancedStreamCompanion,
    StreamType,
    AudioRoute
)

async def main():
    print("=" * 65)
    print("     ADVANCED SCAFFOLDER COMPANION TEST")
    print("=" * 65)

    dispatched_audio = []
    def mock_audio_sink(text: str, route: AudioRoute):
        dispatched_audio.append((route.value, text))

    companion = AdvancedStreamCompanion(
        stream_type=StreamType.GAMING,
        audio_sink=mock_audio_sink
    )

    print("\n[1/4] Testing Intelligent Chat Moderation...")
    # Good messages
    companion.ingest_chat("alex_pro", "Insane movement bro!")
    companion.ingest_chat("dev_guy", "What keyboard are you using?")
    # Caps flood
    res_caps = companion.ingest_chat("spammer_caps", "WTFFFFFFFFFFFFFFFFFFFFFFFFFFFFF!!!!!!!!!")
    # Link spam
    res_link = companion.ingest_chat("bot_net", "Join my discord.gg/free_skins right now")

    print(f" • Caps Defense: {res_caps['action']} -> {res_caps['reason']}")
    print(f" • Link Defense: {res_link['action']} -> {res_link['reason']}")
    assert res_caps["action"] == "AUTO_WARN"
    assert res_link["action"] == "AUTO_TIMEOUT"
    assert "bot_net" in companion.banned_users

    print("\n[2/4] Testing Sentiment Pulse & Ear Dispatch...")
    pulse = companion.get_chat_pulse()
    print(f" • Vibe: {pulse['vibe']} | Summary: \"{pulse['summary']}\"")
    companion.dispatch_voice(pulse["summary"], AudioRoute.EAR_ONLY)
    assert len(dispatched_audio) == 1
    assert dispatched_audio[0][0] == "ear_only"
    print(f" • Ear Route Verified: \"{dispatched_audio[0][1]}\"")

    print("\n[3/4] Testing Highlight Bookmarking & Disk Persistence...")
    bm = companion.mark_stream_moment("Insane 1v4 A-Site Retake")
    print(f" • Highlight Logged: [{bm['time']}] \"{bm['note']}\"")
    assert companion.session_file.exists()
    print(f" • Verified Session JSON on disk: {companion.session_file.resolve()}")

    print("\n[4/4] Testing OBS Replay Buffer Trigger...")
    ok_obs, obs_msg = await companion.obs.save_replay_buffer()
    print(f" • OBS Status: {obs_msg}")
    assert ok_obs is True

    print("\n" + "=" * 65)
    print(">>> ADVANCED SCAFFOLDER COMPANION FULLY VERIFIED <<<")
    print("=" * 65)

if __name__ == "__main__":
    asyncio.run(main())
