import sys
import shutil
import asyncio
import subprocess
from agent.pa_scaffolder.agent_config import AgentConfig
from agent.pa_scaffolder.vad_wakeword_engine import WakeWordGatingFilter
from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine


def print_banner(config: AgentConfig):
    print("=" * 65)
    print(f"     CONVERSATIONAL VOICE ENGINE (AGENT: '{config.agent_name.upper()}')")
    print("=" * 65)
    print(f" • Active Name:       {config.agent_name}")
    print(f" • Primary Wake Words: 'hey {config.agent_name.lower()}', '{config.agent_name.lower()}'")
    print(f" • Phonetic Aliases:  Active ({len(config.wake_words)} variants registered)")
    print(f" • To rename agent:   python test_vad_wakeword.py --name <NewName>")
    print("=" * 65)


async def capture_stt_phrase(timeout: int = 10) -> str:
    """Captures a single speech phrase via Termux:API without throwing."""
    try:
        res = await asyncio.to_thread(
            subprocess.run,
            ["termux-speech-to-text"],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if res.returncode == 0 and res.stdout:
            return res.stdout.strip()
    except subprocess.TimeoutExpired:
        pass
    except Exception as e:
        print(f"[STT Error]: {e}")
    return ""


async def main():
    config = AgentConfig()

    # CLI rename support: python test_vad_wakeword.py --name Jarvis
    if "--name" in sys.argv:
        idx = sys.argv.index("--name")
        if idx + 1 < len(sys.argv):
            new_name = sys.argv[idx + 1]
            config.set_agent_name(new_name)
            print(f"\n[Config] Agent renamed to '{new_name}'. Aliases compiled.")

    print_banner(config)

    gate = WakeWordGatingFilter(config=config)
    harness = UnifiedAsyncEngine()
    has_termux_mic = shutil.which("termux-speech-to-text") is not None

    if not has_termux_mic:
        print("\n[!] 'termux-speech-to-text' not found in path.")
        print("    Install Termux:API from F-Droid to enable live voice.\n")
        return

    is_in_active_dialogue = False

    while True:
        try:
            # -------------------------------------------------------------
            # STATE 1: DORMANT STANDBY (Requires Wake Word)
            # -------------------------------------------------------------
            if not is_in_active_dialogue:
                print(f"\n[Dormant Standby] Listening for 'Hey {config.agent_name}'...")
                raw_speech = await capture_stt_phrase(timeout=14)

                if not raw_speech or gate.is_stt_error(raw_speech):
                    continue

                print(f" • Heard: \"{raw_speech}\"")
                eval_res = gate.evaluate_transcript(raw_speech)

                if not eval_res["wake_detected"]:
                    # Speech was not addressed to the agent
                    continue

                # Case A: User said Wake Word + Command together (Single-shot)
                if eval_res["interaction_mode"] == "SINGLE_SHOT_COMMAND":
                    cmd = eval_res["command_payload"]
                    print(f" • [Single-Shot]: Executing '{cmd}'...")
                    turn_res = await harness.process_voice_turn(cmd)
                    print(f" • {config.agent_name}: \"{turn_res['spoken_response']}\"")
                    # Brief pause so speaker audio finishes
                    await asyncio.sleep(1.5)

                # Case B: User said Wake Word alone ("Hey Jarvis")
                elif eval_res["interaction_mode"] == "AWAKE_STANDBY":
                    ack = eval_res["standby_acknowledgment"]
                    print(f" • [Wake Detected] {config.agent_name}: \"{ack}\"")
                    await harness.voice_controller.synthesize_and_dispatch_async(ack)
                    # Let the acknowledgment finish playing before opening the mic
                    await asyncio.sleep(1.2)
                    is_in_active_dialogue = True

            # -------------------------------------------------------------
            # STATE 2: ACTIVE CONVERSATION (Wake Word NOT Required)
            # -------------------------------------------------------------
            else:
                print(f"\n[Active Window - {config.agent_name}] Listening for your request...")
                command_speech = await capture_stt_phrase(timeout=10)

                if not command_speech or gate.is_stt_error(command_speech):
                    print(f" • [Timeout] No command heard. Returning to standby.")
                    is_in_active_dialogue = False
                    continue

                print(f" • [Command Received]: \"{command_speech}\"")

                # Check if user told agent to cancel or sleep
                if command_speech.lower().strip() in ["stop", "cancel", "sleep", "nevermind", "exit"]:
                    sleep_msg = "Going back to standby."
                    print(f" • {config.agent_name}: \"{sleep_msg}\"")
                    await harness.voice_controller.synthesize_and_dispatch_async(sleep_msg)
                    is_in_active_dialogue = False
                    await asyncio.sleep(1.0)
                    continue

                # Execute conversational turn through Jev & Brain
                turn_res = await harness.process_voice_turn(command_speech)
                print(f" • {config.agent_name}: \"{turn_res['spoken_response']}\"")
                print(f" • [Backend]: {turn_res['execution_backend']} | Turn Cost: ${turn_res['turn_cost_usd']:.5f}")

                # Give playback time to finish, then stay awake for quick follow-up
                await asyncio.sleep(1.8)
                is_in_active_dialogue = False

        except (KeyboardInterrupt, EOFError):
            print("\nShutting down conversational listener.")
            break


if __name__ == "__main__":
    asyncio.run(main())
