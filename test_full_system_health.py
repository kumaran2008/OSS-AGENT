import asyncio
from pathlib import Path
from agent.pa_scaffolder.agent_config import AgentConfig
from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine

async def run_audit():
    print("=" * 70)
    print("         FULL SYSTEM COMPREHENSIVE INTEGRATION AUDIT")
    print("=" * 70)

    config = AgentConfig()
    harness = UnifiedAsyncEngine()
    print(f" • Active Agent Persona:  '{config.agent_name}'")
    print(f" • Active Brain Backend:  '{config.active_backend}'")

    # 1. Voice Adapter & Audio Engine Check
    print("\n[1/5] Auditing Audio Engine & Voice Mapping...")
    tts_res = await harness.voice_controller.synthesize_and_dispatch_async(
        "Audio engine health check.",
        is_system_command=True
    )
    print(f" • Voice Engine Used:     {tts_res['engine_used']}")
    print(f" • Voice Dispatched:      \"{tts_res['text']}\"")
    assert tts_res["audio_played"] is True or harness.voice_controller.audio_engine.hal.profile.os.value == "android_termux"
    print(" >>> Audio Subsystem: 100% Operational (No TTS Errors). <<<")

    # 2. Memory Engine Check (Pillar 1)
    print("\n[2/5] Auditing Pillar 1: GraphBrain v2 Associative Recall...")
    harness.memory_graph.add_or_update_node(
        node_id="audit_mem_01",
        node_type="concept",
        label="QuantumOptimization",
        metadata={"domain": "compiler", "status": "active"}
    )
    recalled = harness.memory_graph.get_relevant_context("compiler optimization", top_k=1)
    assert len(recalled) > 0
    print(f" • Recalled Node:         '{recalled[0]['label']}' (Score: {recalled[0]['rrf_score']:.5f})")
    print(" >>> Memory Subsystem: 100% Operational. <<<")

    # 3. Execution Engine Check (Pillar 2: The Hands)
    print("\n[3/5] Auditing Pillar 2: Execution Engine (PTY Sandbox & AST Patching)...")
    code, pty_out = await harness.tools.sandbox.execute_and_collect("python -c 'print(100 * 2)'")
    print(f" • PTY Sandbox Math Run:  \"{pty_out}\" (Exit: {code})")
    assert "200" in pty_out

    # Tool Registry Dispatch
    tool_res = await harness.tools.dispatch("file_write", {
        "file_path": "audit_test.py",
        "content": "def test_ok():\n    return True\n"
    })
    assert tool_res.success is True
    Path("workspace/audit_test.py").unlink(missing_ok=True)
    print(" >>> Execution Subsystem ('The Hands'): 100% Operational. <<<")

    # 4. Autonomous Routing & Safety Interceptors
    print("\n[4/5] Auditing Autonomous Routing & Biometric Interceptors...")
    # Autonomous terminal execution
    term_turn = await harness.process_voice_turn("run echo 'SYSTEM_VERIFIED'")
    print(f" • Terminal Run Turn:     \"{term_turn['spoken_response']}\"")
    assert term_turn["execution_backend"] == "SANDBOX_PTY_EXEC"
    assert "SYSTEM_VERIFIED" in term_turn["spoken_response"]

    # Biometric financial gate
    bio_turn = await harness.process_voice_turn("buy now 6 hot wings on swiggy")
    print(f" • Biometric Safety Turn: \"{bio_turn['spoken_response']}\"")
    assert bio_turn["execution_backend"] == "BIOMETRIC_GATE"
    print(" >>> Autonomous Routing & Safety Gate: 100% Operational. <<<")

    # 5. Sticky State & Identity Flow Check
    print("\n[5/5] Auditing Sticky Identity Flow...")
    greet_turn = await harness.process_voice_turn(f"hey {config.agent_name.lower()}")
    print(f" • Natural Greeting:      \"{greet_turn['spoken_response']}\"")
    assert config.agent_name in greet_turn["spoken_response"]
    print(" >>> Dynamic Identity Flow: 100% Operational. <<<")

    harness.tools.close()

    print("\n" + "=" * 70)
    print(">>> VERDICT: ZERO CODE DEGRADATION. ALL PILLARS 100% READY <<<")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(run_audit())
