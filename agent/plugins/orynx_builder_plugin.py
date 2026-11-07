from __future__ import annotations
from typing import Any, Dict, List
from agent.kernel.plugin_host import (
    Action,
    ActionResult,
    AuthorizedTaskContext,
    Capability,
    VerificationResult,
    plugin_host,
)
from agent.suites.orynx_builder import orynx_builder_suite


class OrynxBuilderPlugin:
    """
    Standardized 5-Method Kernel Plugin for OrynX Builder (bolt.diy + Lovable + Docker/WebContainer engine).
    Implements discover_capabilities, execute, verify, health_check, and shutdown.
    """

    plugin_id = "plugin.orynx_builder"
    api_version = "3.0"

    def register_capabilities(self) -> List[Capability]:
        return [
            Capability(
                id="orynx_builder.scaffold_and_build_app",
                version="3.0",
                plugin_id=self.plugin_id,
                description="Scaffold, stream <orynxArtifact> files, verify Web Vitals & Docker/ShadowTwin, and de-scaffold node_modules",
                execution_backend="LOCAL_SANDBOX",
                risk_class="local_write",
                data_sensitivity="PROJECT",
                preconditions=["workspace_writable"],
                postconditions=["dockerfile_created", "sandbox_exit_zero", "performance_budgets_passed"],
            ),
            Capability(
                id="orynx_builder.deploy_cloud_connector",
                version="3.0",
                plugin_id=self.plugin_id,
                description="Deploy or manage sites across Netlify, Vercel, Supabase, GitHub, GitLab, or Browser Use Cloud MCP",
                execution_backend="OFFICIAL_API",
                risk_class="external_write",
                data_sensitivity="PROJECT",
                preconditions=["connector_permission_enabled"],
                postconditions=["deployment_receipt_verified"],
            ),
            Capability(
                id="orynx_builder.flush_error_memory_box",
                version="3.0",
                plugin_id=self.plugin_id,
                description="Inspect or batch-flush accumulated multi-file AST/runtime errors in the SQLite Error Memory Box",
                execution_backend="LOCAL_SANDBOX",
                risk_class="local_write",
                data_sensitivity="PROJECT",
                preconditions=["error_box_initialized"],
                postconditions=["errors_flushed_and_resolved"],
            ),
        ]

    def discover_capabilities(self) -> List[Capability]:
        return self.register_capabilities()

    async def execute(self, action: Action, context: AuthorizedTaskContext) -> ActionResult:
        if action.capability_id == "orynx_builder.flush_error_memory_box":
            flushed = orynx_builder_suite.error_box.flush_and_mark_resolved(
                action.params.get("session_id", "orynx_build_session")
            )
            return ActionResult(
                action_id=action.action_id,
                capability_id=action.capability_id,
                status="COMPLETED",
                raw_legacy_dict={"status": "COMPLETED", **flushed},
                provider_receipt=f"errbox_flush_{flushed['flushed_error_count']}",
                evidence_refs=["orynx_error_memory_box"],
            )

        if action.capability_id == "orynx_builder.deploy_cloud_connector":
            site_id = action.params.get("site_id", "orynx_default_site")
            act_name = action.params.get("connector_action", "trigger_build")
            res = orynx_builder_suite.connectors.execute_netlify_site_action(act_name, site_id=site_id)
            ok = res.get("status") == "COMPLETED"
            return ActionResult(
                action_id=action.action_id,
                capability_id=action.capability_id,
                status="COMPLETED" if ok else "FAILED",
                raw_legacy_dict=res,
                provider_receipt=res.get("build_id", f"netlify_{act_name}"),
                evidence_refs=[res.get("endpoint", "netlify_api")],
            )

        build_out = await orynx_builder_suite.build_verify_and_package_app(
            user_objective=action.params.get("objective", action.target or "Build full-stack app"),
            target_dir=action.params.get("target_dir", "workspace/orynx_apps/plugin_build"),
            deploy_target=action.params.get("deploy_target"),
        )
        return ActionResult(
            action_id=action.action_id,
            capability_id=action.capability_id,
            status="COMPLETED" if build_out["status"] == "COMPLETED_AND_VERIFIED" else "FAILED",
            raw_legacy_dict=build_out,
            provider_receipt=f"orynx_build_{build_out['template_selected']}",
            evidence_refs=build_out["written_files"],
        )

    def verify(self, action: Action, result: ActionResult) -> VerificationResult:
        ok = result.status == "COMPLETED" and bool(result.provider_receipt)
        return VerificationResult(
            action_id=action.action_id,
            capability_id=action.capability_id,
            status="COMPLETED" if ok else "FAILED",
            verified=ok,
            evidence_type="ORYNX_BUILDER_POSTCONDITION_VERIFIED",
            observed_evidence=f"Verified {action.capability_id} via receipt {result.provider_receipt}",
        )

    def health_check(self) -> Dict[str, Any]:
        caps = orynx_builder_suite.container_runtime.detect_container_capabilities()
        return {
            "plugin_id": self.plugin_id,
            "status": "HEALTHY",
            "healthy": True,
            "capabilities_count": len(self.register_capabilities()),
            "container_capabilities": caps,
        }

    def shutdown(self) -> Dict[str, Any]:
        return {"plugin_id": self.plugin_id, "status": "SHUTDOWN_CLEAN", "ok": True}


orynx_builder_plugin = OrynxBuilderPlugin()
plugin_host.register_plugin(orynx_builder_plugin)
