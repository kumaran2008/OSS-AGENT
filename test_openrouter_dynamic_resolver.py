import asyncio
import shutil
import json
from pathlib import Path

from agent.pa_scaffolder.rooms_engine import RoomsEngine, AgentMode, SystemTelemetryCache
from agent.pa_scaffolder.universal_model_switcher import UniversalModelSwitcher
from agent.pa_scaffolder.model_router import ModelAgnosticRouter, TaskProfile
from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine


async def test_openrouter_dynamic_resolver():
    print("=" * 70)
    print("     GAP 2 VERIFICATION: OPENROUTER DYNAMIC MODEL RESOLVER")
    print("=" * 70)

    test_ws = Path("workspace/test_openrouter_sandbox").resolve()
    shutil.rmtree(test_ws, ignore_errors=True)
    test_ws.mkdir(parents=True, exist_ok=True)

    test_reg_path = test_ws / "model_registry.json"
    shutil.copy("agent/pa_scaffolder/model_registry.json", test_reg_path)

    switcher = UniversalModelSwitcher(registry_path=test_reg_path)

    # -------------------------------------------------------------------------
    # 1. Verify 100% Cloud-First Architecture (No Local SLMs)
    # -------------------------------------------------------------------------
    print("\n[1/6] Verifying 100% Cloud-First Endpoints (Purged Local Models)...")
    for b_id, ep in switcher.endpoints.items():
        print(f" • Endpoint: {b_id:<22} | Provider: {ep.provider:<12} | URL: {ep.api_base_url}")
        assert ep.provider not in ["ollama", "local"], f"Local provider detected: {ep.provider}"
    print(" >>> CRITERION 1 PASSED: Zero local models; 100% cloud-first endpoints active. <<<")

    # -------------------------------------------------------------------------
    # 2. Dynamic Auto-Discovery of New Frontier Model (e.g. Qwen 2.5 Coder 32B)
    # -------------------------------------------------------------------------
    print("\n[2/6] Testing Dynamic OpenRouter Auto-Discovery (Qwen 2.5 Coder 32B)...")
    target_query = "qwen 2.5 coder 32b"
    ok_res, res_msg, auto_id = switcher.resolve_and_register_openrouter(target_query)

    print(f" • Discovery Status:     {'SUCCESS' if ok_res else 'FAILED'}")
    print(f" • Resolved Backend ID:  {auto_id}")
    print(f" • Resolver Message:     \"{res_msg}\"")
    assert ok_res is True
    assert auto_id is not None
    assert auto_id in switcher.endpoints

    ep_qwen = switcher.endpoints[auto_id]
    print(f" • Context Window:       {ep_qwen.context_window:,} tokens")
    print(f" • In/Out Pricing:       ${ep_qwen.cost_per_m_in} / ${ep_qwen.cost_per_m_out} per 1M")
    assert ep_qwen.context_window >= 32000
    assert ep_qwen.provider == "openrouter"
    print(" >>> CRITERION 2 PASSED: Model metadata, pricing, and context auto-registered. <<<")

    # -------------------------------------------------------------------------
    # 3. Dynamic Auto-Discovery of Unreleased Model Query (GPT-4.5)
    # -------------------------------------------------------------------------
    print("\n[3/6] Testing Dynamic Auto-Discovery (GPT-4.5)...")
    ok_gpt, msg_gpt, gpt_id = switcher.resolve_and_register_openrouter("gpt 4.5 preview")
    print(f" • Discovery Status:     {'SUCCESS' if ok_gpt else 'FAILED'}")
    print(f" • Resolved Backend ID:  {gpt_id}")
    assert ok_gpt is True
    assert gpt_id in switcher.endpoints
    print(" >>> CRITERION 3 PASSED: Frontier model discovered and added to registry. <<<")

    # -------------------------------------------------------------------------
    # 4. Auto-Switching Room to Newly Discovered OpenRouter Model
    # -------------------------------------------------------------------------
    print("\n[4/6] Testing Room Hot-Switch with Auto-Resolved Model...")
    engine = RoomsEngine(workspace_root=str(test_ws))
    engine.model_switcher = switcher

    # Switch Researcher Room directly to newly registered Qwen endpoint
    ok_sw, sw_msg = engine.switch_model_backend("researcher", auto_id)
    print(f" • Room Switch Result:   \"{sw_msg}\"")
    assert ok_sw is True
    assert engine.REGISTRY[AgentMode.RESEARCHER].preferred_backend == auto_id
    print(" >>> CRITERION 4 PASSED: Researcher room hot-swapped to OpenRouter endpoint. <<<")

    # -------------------------------------------------------------------------
    # 5. Conversational Voice Command Auto-Discovery
    # -------------------------------------------------------------------------
    print("\n[5/6] Testing Conversational Voice Command Auto-Discovery...")
    harness = UnifiedAsyncEngine()
    harness.rooms.workspace = test_ws
    harness.rooms.model_switcher = switcher

    # User speaks: "switch builder to gpt 4.5" (unconfigured ID)
    voice_input = "switch builder to gpt 4.5"
    turn_res = await harness.process_voice_turn(voice_input)

    print(f" • Voice Utterance:      \"{voice_input}\"")
    print(f" • Turn Result Type:     {turn_res.get('type')}")
    print(f" • Spoken Response:      \"{turn_res.get('spoken_response')}\"")
    assert turn_res.get("type") == "MODEL_SWITCH_SUCCESS"
    assert "BUILDER" in turn_res.get("spoken_response")
    print(" >>> CRITERION 5 PASSED: Natural language voice turn auto-resolved model. <<<")

    # -------------------------------------------------------------------------
    # 6. Cloud-First Low-Balance Fallback (No Local Dependencies)
    # -------------------------------------------------------------------------
    print("\n[6/6] Testing Cloud-First Low-Balance Fallback...")
    SystemTelemetryCache.set_wallet_balance(0.00)

    router = ModelAgnosticRouter(switcher=switcher)
    ep_fb, is_fb = router.resolve_optimal_endpoint(TaskProfile.SKIM_EXTRACTION)

    print(f" • Low-Balance Endpoint: {ep_fb.backend_id} ({ep_fb.model_name})")
    print(f" • Provider:             {ep_fb.provider}")
    print(f" • Fallback Flag:        {is_fb}")
    assert is_fb is True
    assert ep_fb.provider in ["deepseek", "openrouter"]
    assert ep_fb.provider != "ollama"

    SystemTelemetryCache.set_wallet_balance(5.00)
    print(" >>> CRITERION 6 PASSED: 100% Cloud-First fallback validated. <<<")

    harness.tools.close()
    shutil.rmtree(test_ws, ignore_errors=True)

    print("\n" + "=" * 70)
    print(">>> GAP 2 (OPENROUTER DYNAMIC MODEL RESOLVER) 100% OPERATIONAL <<<")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_openrouter_dynamic_resolver())
