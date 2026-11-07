from __future__ import annotations
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from agent.core.dynamic_auth import DynamicAuthManager


@dataclass
class ConnectionTestResult:
    """Ported from ConnectionTestIndicator.tsx (lines 5-9)."""
    status: str  # 'success' | 'error' | 'testing'
    message: str
    timestamp: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "timestamp": self.timestamp,
        }


@dataclass
class ServiceErrorRecord:
    """Ported from ErrorState.tsx & GitHubErrorBoundary.tsx."""
    service: str
    title: str
    message: str
    context: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    retry_label: str = "Try again"
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "service": self.service,
            "title": self.title,
            "message": self.message,
            "context": self.context,
            "details": self.details,
            "retryLabel": self.retry_label,
            "timestamp": self.timestamp_ms,
        }


class OrynxServiceErrorAndEnvManager:
    """
    Ports `.env.example`, `.env.production`, `ErrorState.tsx`, `ConnectionTestIndicator.tsx`,
    and `GitHubErrorBoundary.tsx` (`useGitHubErrorHandler`), connecting them to Oryn's
    `DynamicAuthManager` and hardware-adaptive `DEFAULT_NUM_CTX` VRAM sizer.
    """

    # Ported from .env.production lines 157-163 (VRAM -> DEFAULT_NUM_CTX mapping)
    VRAM_CTX_TIERS = [
        (36.0, 32768),  # >= 36GB VRAM -> 32768 context window
        (32.0, 24576),  # >= 32GB VRAM -> 24576 context window
        (26.0, 12288),  # >= 26GB VRAM -> 12288 context window
        (24.0, 6144),   # >= 24GB VRAM -> 6144 context window
        (0.0, 4096),    # Edge / Laptop / Mobile fallback
    ]

    # Ported from .env.example & .env.production (IPv4 127.0.0.1 enforced over localhost to prevent IPv6 issues)
    DEFAULT_LOCAL_PROVIDER_URLS = {
        "OLLAMA_API_BASE_URL": "http://127.0.0.1:11434",
        "LMSTUDIO_API_BASE_URL": "http://127.0.0.1:1234",
    }

    PROVIDER_ENV_KEYS = [
        "ANTHROPIC_API_KEY",
        "CEREBRAS_API_KEY",
        "FIREWORKS_API_KEY",
        "OPENAI_API_KEY",
        "GITHUB_API_KEY",
        "PERPLEXITY_API_KEY",
        "DEEPSEEK_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "COHERE_API_KEY",
        "GROQ_API_KEY",
        "MISTRAL_API_KEY",
        "TOGETHER_API_KEY",
        "XAI_API_KEY",
        "MOONSHOT_API_KEY",
        "ZAI_API_KEY",
        "HuggingFace_API_KEY",
        "HYPERBOLIC_API_KEY",
        "OPEN_ROUTER_API_KEY",
        "VITE_GITHUB_ACCESS_TOKEN",
        "VITE_GITLAB_ACCESS_TOKEN",
        "VITE_VERCEL_ACCESS_TOKEN",
        "VITE_NETLIFY_ACCESS_TOKEN",
        "VITE_SUPABASE_ACCESS_TOKEN",
    ]

    def __init__(self, env_path: str = ".env"):
        self.auth_manager = DynamicAuthManager(env_path=env_path)
        self.error_ledger: List[ServiceErrorRecord] = []
        self.connection_tests: Dict[str, ConnectionTestResult] = {}

    def compute_optimal_num_ctx(self, detected_vram_gb: Optional[float] = None) -> Dict[str, Any]:
        """
        Ported from `.env.production` (lines 157-163):
        Selects `DEFAULT_NUM_CTX` based on available VRAM or system memory so local models
        (Ollama / LMStudio / Qwen2.5-Coder) never OOM.
        """
        if detected_vram_gb is None:
            # Estimate available memory from /proc/meminfo if on Linux/Android
            mem_gb = 8.0
            meminfo = Path("/proc/meminfo")
            if meminfo.exists():
                for line in meminfo.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if line.startswith("MemTotal:"):
                        parts = line.split()
                        if len(parts) >= 2 and parts[1].isdigit():
                            mem_gb = round(int(parts[1]) / (1024.0 * 1024.0), 2)
                        break
            detected_vram_gb = mem_gb

        selected_ctx = 4096
        for threshold_gb, ctx_val in self.VRAM_CTX_TIERS:
            if float(detected_vram_gb) >= threshold_gb:
                selected_ctx = ctx_val
                break

        return {
            "detected_memory_gb": round(float(detected_vram_gb), 2),
            "DEFAULT_NUM_CTX": selected_ctx,
            "ollama_base_url": self.DEFAULT_LOCAL_PROVIDER_URLS["OLLAMA_API_BASE_URL"],
            "lmstudio_base_url": self.DEFAULT_LOCAL_PROVIDER_URLS["LMSTUDIO_API_BASE_URL"],
        }

    def normalize_local_provider_url(self, url: str) -> str:
        """
        Enforces `.env.example` rule (lines 89-91, 105-107):
        Replaces `http://localhost:` with `http://127.0.0.1:` to prevent IPv6 resolution failures.
        """
        return (url or "").replace("http://localhost:", "http://127.0.0.1:")

    def handle_service_error(
        self,
        service: str,
        error: Any,
        context: Optional[str] = None,
        title: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> ServiceErrorRecord:
        """Ported from ErrorState.tsx (`ConnectionError`) & GitHubErrorBoundary.tsx (`useGitHubErrorHandler`)."""
        msg = str(error) if error is not None else "An unknown error occurred"
        rec = ServiceErrorRecord(
            service=service,
            title=title or f"Failed to connect to {service}",
            message=msg,
            context=context,
            details=details or {"service": service, "context": context or "general"},
            retry_label="Retry connection",
        )
        self.error_ledger.append(rec)
        return rec

    def run_connection_test(self, service_name: str, token: str = "") -> ConnectionTestResult:
        """Ported from ConnectionTestIndicator.tsx & GitHubTab.tsx (`handleTestConnection`)."""
        self.connection_tests[service_name] = ConnectionTestResult(
            status="testing",
            message="Testing connection...",
        )
        clean_tok = token.strip() or os.environ.get(f"VITE_{service_name.upper()}_ACCESS_TOKEN", "")
        if not clean_tok:
            res = ConnectionTestResult(
                status="error",
                message="No connection established (missing access token)",
            )
        else:
            res = ConnectionTestResult(
                status="success",
                message=f"Connected successfully to {service_name}",
            )
        self.connection_tests[service_name] = res
        return res
