import os
from dataclasses import dataclass

@dataclass(frozen=True)
class BrandConfig:
    # Set default or override dynamically via environment variables
    company_name: str = os.getenv("OSS_COMPANY_NAME", "Aegis")
    core_engine_name: str = os.getenv("OSS_CORE_ENGINE", "aegis-core")
    pa_product_name: str = os.getenv("OSS_PA_NAME", "Personal Agent")
    pa_default_companion_name: str = os.getenv("OSS_COMPANION_NAME", "Hype")
    cli_command_core: str = os.getenv("OSS_CORE_CLI", "aegis")
    cli_command_pa: str = os.getenv("OSS_PA_CLI", "pa")
    docs_url: str = os.getenv("OSS_DOCS_URL", "https://github.com/your-org/core-agent")
    
    def get_banner(self) -> str:
        return f"""
============================================================
       {self.company_name.upper()} :: {self.pa_product_name.upper()}
       Autonomous Multi-Platform Companion System
============================================================
"""

# Global immutable branding instance
BRAND = BrandConfig()
