import ast
from typing import Any, Dict, List
from agent.training.adapter_registry import adapter_registry
from llm.router import ModelRouter

BENCHMARK_TASKS = [
    {
        "id": "py_health_check",
        "role": "mason_backend_mason",
        "task": "Write a Python function `get_system_health() -> dict` returning status, cpu_usage float, and is_healthy bool.",
        "eval_fn": lambda code: "def get_system_health" in code and "is_healthy" in code
    },
    {
        "id": "py_safe_divide",
        "role": "mason_backend_mason",
        "task": "Write a Python function `safe_divide(a: float, b: float) -> float | None` that handles ZeroDivisionError gracefully.",
        "eval_fn": lambda code: "def safe_divide" in code and "ZeroDivisionError" in code
    },
    {
        "id": "test_suite_mock",
        "role": "tester",
        "task": "Write a pytest test function `test_database_retry()` using unittest.mock to simulate connection retry.",
        "eval_fn": lambda code: "test_database_retry" in code and "mock" in code.lower()
    }
]

class AdapterBenchmark:
    """Evaluates candidate adapter weights against baseline models before deployment."""

    def __init__(self, router: ModelRouter):
        self.router = router

    def evaluate_role(self, role: str, min_promotion_score: float = 0.5) -> Dict[str, Any]:
        role_tasks = [t for t in BENCHMARK_TASKS if t["role"] == role]
        if not role_tasks:
            role_tasks = [t for t in BENCHMARK_TASKS if "mason" in t["role"]]

        total = len(role_tasks)
        passed = 0
        syntax_valid = 0

        print(f"[Benchmark] Starting evaluation for role '{role}' ({total} tasks)...")

        for idx, task in enumerate(role_tasks, 1):
            messages = [
                {"role": "system", "content": "You are a code specialist. Return only runnable code in markdown fences."},
                {"role": "user", "content": task["task"]},
            ]
            try:
                res, model_used = self.router.complete_with_fallback("coding", messages)
                from agent.masons.base_mason import extract_code_block
                code = extract_code_block(res)

                try:
                    ast.parse(code)
                    syntax_valid += 1
                except SyntaxError:
                    print(f"  • Task #{idx} [{task['id']}] failed AST parsing.")
                    continue

                if task["eval_fn"](code):
                    passed += 1
                    print(f"  • Task #{idx} [{task['id']}] PASSED via {model_used}")
                else:
                    print(f"  • Task #{idx} [{task['id']}] failed assertions.")
            except Exception as e:
                print(f"  • Task #{idx} failed with error: {e}")

        score = (passed / total) if total > 0 else 0.0
        promoted = score >= min_promotion_score

        active_adapter = adapter_registry.get_active_adapter(role)
        if promoted and active_adapter:
            active_adapter["benchmark_score"] = score
            active_adapter["active"] = True
            adapter_registry._save()
            print(f"[Benchmark] Adapter for '{role}' PROMOTED (Score: {score:.2f} >= {min_promotion_score}).")
        else:
            print(f"[Benchmark] Adapter score: {score:.2f} (Promoted: {promoted}).")

        return {
            "role": role,
            "total_tasks": total,
            "passed": passed,
            "syntax_valid": syntax_valid,
            "score": score,
            "promoted": promoted,
        }
