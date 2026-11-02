from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any, Dict

from agent.kernel import (
    capability_registry,
    jev_ai_brain,
    model_broker,
    plugin_host,
    task_planner,
    universal_orchestrator,
)
from agent.memory_graph import VALID_MEMORY_NAMESPACES, unified_memory_service
from agent.suites.personal_assistant import proactive_assistant
from agent.suites.reliability_and_shadow import reliability_shadow_service


async def cmd_status() -> Dict[str, Any]:
    reg = capability_registry.refresh_registry()
    adapters = universal_orchestrator.inspect_connected_pa_scaffolder_adapters()
    plugins_health = [p.health_check() for p in getattr(plugin_host, "_plugins", {}).values()]
    status_report = {
        "os_name": "Friday Universal Personal AI Operating System",
        "system1_brain": jev_ai_brain.MODEL_VERSION,
        "system1_mode": jev_ai_brain.get_api_credentials()["source"],
        "registered_capabilities": reg["total_registered_capabilities"],
        "available_capabilities": reg["available_capabilities"],
        "bridged_pa_scaffolder_engines": adapters["total_adapters_bridged"],
        "enforced_memory_namespaces": len(VALID_MEMORY_NAMESPACES),
        "specialised_suites_count": 7,
        "plugins_health": plugins_health,
    }
    print(json.dumps(status_report, indent=2))
    return status_report


async def cmd_briefing() -> Dict[str, Any]:
    brief = proactive_assistant.generate_daily_briefing("morning workstation login")
    print(json.dumps(brief, indent=2))
    return brief


async def cmd_benchmark() -> Dict[str, Any]:
    bench = await reliability_shadow_service.evaluate_4_condition_benchmark(
        "Fix route_task_economically quality floor and verify callers across kernel"
    )
    print(json.dumps(bench, indent=2))
    return bench


async def cmd_run_goal(goal: str) -> Dict[str, Any]:
    res = await universal_orchestrator.execute_arbitrary_universal_goal(goal, user_approved_external_actions=True)
    print(json.dumps(res, indent=2, default=str))
    return res


async def main() -> None:
    parser = argparse.ArgumentParser(description="Friday Universal Personal AI Operating System CLI")
    parser.add_argument("--status", action="store_true", help="Show full OS architecture and plugin health status")
    parser.add_argument("--briefing", action="store_true", help="Generate proactive daily briefing")
    parser.add_argument("--benchmark", action="store_true", help="Run 4-Condition Cost per Verified Task benchmark")
    parser.add_argument("--run", type=str, help="Execute an arbitrary cross-suite or task-lifecycle goal")
    args = parser.parse_args()

    if args.status:
        await cmd_status()
    elif args.briefing:
        await cmd_briefing()
    elif args.benchmark:
        await cmd_benchmark()
    elif args.run:
        await cmd_run_goal(args.run)
    else:
        await cmd_status()


if __name__ == "__main__":
    asyncio.run(main())
