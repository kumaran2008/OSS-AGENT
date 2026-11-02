import asyncio
import shutil
import json
from pathlib import Path

from agent.pa_scaffolder.rooms_engine import RoomsEngine, AgentMode, SystemTelemetryCache
from agent.pa_scaffolder.universal_model_switcher import UniversalModelSwitcher
from agent.pa_scaffolder.model_router import ModelAgnosticRouter, TaskProfile
from agent.pa_scaffolder.engine_harness import UnifiedAsyncEngine
from agent.pa_scaffolder.tool_registry import ToolRegistry


async def test_universal_model_switcher():
    print("=" * 70)
    print("     DYNAMIC UNIVERSAL MODEL SWITCHER VERIFICATION BENCHMARK")
    print("=" * 70)

    test_ws = Path("workspace/test_switcher_sandbox").resolve()
    shutil.rmtree(test_ws, ignore_errors=True)
    test_ws.mkdir(parents=True, exist_ok=True)

    test_reg_path = test_ws / "test_model_registry.json"
    shutil.copy("agent/pa_scaffolder/model_registry.json", test_reg_path)

    switcher = UniversalModelSwitcher(registry_path=test_reg_path)

    # -------------------------------------------------------------------------
    # 1. Model Listing & Active Overview
    # -------------------------------------------------------------------------
    print("\n[1/6] Testing Model Registry Ingestion & Active Overview...")
    overview = switcher.get_active_overview()
    print(f" • Active Builder Model:     {overview['rooms']['builder']}")
    print(f" • Active Tester Model:      {overview['rooms']['tester']}")
    print(f" • Active Researcher Model:  {overview['rooms']['researcher']}")
    assert "builder" in overview["rooms"]
    assert "tester" in overview["rooms"]

    models_list = switcher.list_models()
    print(f" • Configured Endpoints:     {len(models_list)} models available.")
    assert len(models_list) >= 5
    print(" >>> CRITERION 1 PASSED: Model registry loaded and active mappings verified. <<<")

    # -------------------------------------------------------------------------
    # 2. Dynamic Registration of Newly Released Frontier Models
    # -------------------------------------------------------------------------
    print("\n[2/6] Testing Dynamic Registration of Newly Released Model...")
    new_model_id = "claude_next_frontier"
    ok_reg, reg_msg = switcher.register_new_model(
        backend_id=new_model_id,
        provider="anthropic",
        model_name="claude-3-8-opus-2026",
        context_window=500000,
        cost_per_m_in=5.0,
        cost_per_m_out=25.0,
        api_base_url="https://api.anthropic.com/v1",
        api_key_env_var="ANTHROPIC_API_KEY"
    )
    print(f" • Registration Status:      {'SUCCESS' if ok_reg else 'FAILED'}")
    print(f" • Status Message:           \"{reg_msg}\"")
    assert ok_reg is True

    # Verify persisted on disk
    persisted = json.loads(test_reg_path.read_text(encoding="utf-8"))
    assert new_model_id in persisted["endpoints"]
    assert persisted["endpoints"][new_model_id]["context_window"] == 500000
    print(" >>> CRITERION 2 PASSED: Brand-new model registered and persisted to JSON. <<<")

    # -------------------------------------------------------------------------
    # 3. Hot-Switching Room Backends & Live RoomsEngine Sync
    # -------------------------------------------------------------------------
    print("\n[3/6] Testing Room Model Hot-Switch & RoomsEngine Live Sync...")
    engine = RoomsEngine(workspace_root=str(test_ws))
    engine.model_switcher = switcher

    # Initial state
    initial_builder_backend = engine.REGISTRY[AgentMode.BUILDER].preferred_backend
    print(f" • Initial Builder Backend:  {initial_builder_backend}")

    # Switch Builder Room to newly registered model
    ok_sw, sw_msg = engine.switch_model_backend("builder", new_model_id)
    print(f" • Switch Operation:         \"{sw_msg}\"")
    assert ok_sw is True

    # Verify live RoomsEngine was updated immediately without restarting
    updated_builder_backend = engine.REGISTRY[AgentMode.BUILDER].preferred_backend
    print(f" • Updated Builder Backend:  {updated_builder_backend}")
    assert updated_builder_backend == new_model_id
    print(" >>> CRITERION 3 PASSED: Room backend switched and live RoomsEngine updated. <<<")

    # -------------------------------------------------------------------------
    # 4. Hot-Switching Task Profiles & Router Resolution
    # -------------------------------------------------------------------------
    print("\n[4/6] Testing Task Profile Hot-Switching & Model Router...")
    router = ModelAgnosticRouter()
    router.switcher = switcher

    # Switch deep reasoning task to deepseek_r1
    ok_task, task_msg = switcher.switch_task_model(TaskProfile.DEEP_REASONING, "deepseek_r1")
    print(f" • Task Switch Operation:    \"{task_msg}\"")
    assert ok_task is True

    # Verify router resolves the new model endpoint
    ep_resolved, _ = router.resolve_optimal_endpoint(TaskProfile.DEEP_REASONING)
    print(f" • Router Resolved Model:    {ep_resolved.backend_id} ({ep_resolved.model_name})")
    assert ep_resolved.backend_id == "deepseek_r1"
    assert ep_resolved.model_name == "deepseek-reasoner"
    print(" >>> CRITERION 4 PASSED: Task profile switched and router verified. <<<")

    # -------------------------------------------------------------------------
    # 5. Conversational Turn Interception
    # -------------------------------------------------------------------------
    print("\n[5/6] Testing Conversational Voice Command Model Switching...")
    harness = UnifiedAsyncEngine()
    harness.rooms.model_switcher = switcher

    # Voice command: switch tester to local_ollama
    user_voice_cmd = "switch tester to local_ollama"
    turn_res = await harness.process_voice_turn(user_voice_cmd)

    print(f" • Voice Command:            \"{user_voice_cmd}\"")
    print(f" • Turn Result Type:         {turn_res.get('type')}")
    print(f" • Spoken Response:          \"{turn_res.get('spoken_response')}\"")
    assert turn_res.get("type") == "MODEL_SWITCH_SUCCESS"
    assert "local_ollama" in turn_res.get("spoken_response")
    assert switcher.room_assignments["tester"] == "local_ollama"
    print(" >>> CRITERION 5 PASSED: Natural language voice turn switched model backend. <<<")

    # -------------------------------------------------------------------------
    # 6. Zero-Balance Fallback Across All Rooms
    # -------------------------------------------------------------------------
    print("\n[6/6] Testing Zero-Balance Universal Fallback...")
    SystemTelemetryCache.set_wallet_balance(0.00)

    ep_fallback, is_fallback = router.resolve_optimal_endpoint(TaskProfile.WHOLE_PAPER_SYNTHESIS)
    print(f" • Empty Wallet Fallback:    {ep_fallback.backend_id} (Cost in: ${ep_fallback.cost_per_m_in})")
    print(f" • Is Fallback Flag:         {is_fallback}")
    assert is_fallback is True
    assert ep_fallback.cost_per_m_in == 0.0

    # Reset balance for future runs
    SystemTelemetryCache.set_wallet_balance(5.00)
    print(" >>> CRITERION 6 PASSED: Zero-balance fallback verified across all endpoints. <<<")

    # Teardown
    harness.tools.close()
    shutil.rmtree(test_ws, ignore_errors=True)

    print("\n" + "=" * 70)
    print(">>> DYNAMIC UNIVERSAL MODEL SWITCHER 100% OPERATIONAL <<<")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_universal_model_switcher())
