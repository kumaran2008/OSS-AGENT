from pathlib import Path

target = Path("agent/pa_scaffolder/model_router.py")
code = target.read_text(encoding="utf-8")

# Replace resolve_optimal_endpoint to ensure zero local dependencies
old_resolve = """    def resolve_optimal_endpoint(self, profile: TaskProfile) -> Tuple[ModelEndpointConfig, bool]:
        \"\"\"Resolves task profile to its configured model endpoint with zero-balance fallback.\"\"\"
        wallet_balance = 1.00
        try:
            from agent.pa_scaffolder.rooms_engine import SystemTelemetryCache
            wallet_balance = SystemTelemetryCache.get_wallet_balance()
        except Exception:
            pass

        # Zero-balance fallback to free local model
        if wallet_balance <= 0.0:
            for ep in self.switcher.endpoints.values():
                if ep.cost_per_m_in == 0.0 or ep.provider in ["ollama", "cdp"]:
                    return ModelEndpointConfig(
                        backend_id=ep.backend_id,
                        provider=ep.provider,
                        model_name=ep.model_name,
                        context_window=ep.context_window,
                        cost_per_m_in=ep.cost_per_m_in,
                        cost_per_m_out=ep.cost_per_m_out,
                        api_base_url=ep.api_base_url,
                        api_key_env_var=ep.api_key_env_var
                    ), True
            return ModelEndpointConfig(
                backend_id="local_fallback",
                provider="ollama",
                model_name="llama3.2:3b",
                context_window=16384,
                cost_per_m_in=0.0,
                cost_per_m_out=0.0,
                api_base_url="http://127.0.0.1:11434/v1"
            ), True

        # Normal resolution via switcher
        ep = self.switcher.get_endpoint_for_task(profile)
        return ModelEndpointConfig(
            backend_id=ep.backend_id,
            provider=ep.provider,
            model_name=ep.model_name,
            context_window=ep.context_window,
            cost_per_m_in=ep.cost_per_m_in,
            cost_per_m_out=ep.cost_per_m_out,
            api_base_url=ep.api_base_url,
            api_key_env_var=ep.api_key_env_var
        ), False"""

new_resolve = """    def resolve_optimal_endpoint(self, profile: TaskProfile) -> Tuple[ModelEndpointConfig, bool]:
        \"\"\"100% Cloud-First Resolution: routes to optimal cloud endpoint via UniversalModelSwitcher.\"\"\"
        wallet_balance = 1.00
        try:
            from agent.pa_scaffolder.rooms_engine import SystemTelemetryCache
            wallet_balance = SystemTelemetryCache.get_wallet_balance()
        except Exception:
            pass

        # If wallet reaches 0.0, route to budget cloud tier (DeepSeek Flash / OpenRouter Gateway)
        if wallet_balance <= 0.0:
            budget_ep = self.switcher.endpoints.get("deepseek_flash") or self.switcher.endpoints.get("openrouter_gateway")
            if budget_ep:
                return ModelEndpointConfig(
                    backend_id=budget_ep.backend_id,
                    provider=budget_ep.provider,
                    model_name=budget_ep.model_name,
                    context_window=budget_ep.context_window,
                    cost_per_m_in=budget_ep.cost_per_m_in,
                    cost_per_m_out=budget_ep.cost_per_m_out,
                    api_base_url=budget_ep.api_base_url,
                    api_key_env_var=budget_ep.api_key_env_var
                ), True

        ep = self.switcher.get_endpoint_for_task(profile)
        return ModelEndpointConfig(
            backend_id=ep.backend_id,
            provider=ep.provider,
            model_name=ep.model_name,
            context_window=ep.context_window,
            cost_per_m_in=ep.cost_per_m_in,
            cost_per_m_out=ep.cost_per_m_out,
            api_base_url=ep.api_base_url,
            api_key_env_var=ep.api_key_env_var
        ), False"""

if old_resolve in code:
    code = code.replace(old_resolve, new_resolve)
    target.write_text(code, encoding="utf-8")
    print("[✓] Updated model_router.py with 100% Cloud-First endpoint resolution.")
else:
    print("[i] model_router.py already contains updated resolve_optimal_endpoint.")
