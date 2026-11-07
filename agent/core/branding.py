import os
from dataclasses import dataclass

@dataclass(frozen=True)
class BrandConfig:
    company_name: str = os.getenv('OSS_COMPANY_NAME', 'Orin')
    core_engine_name: str = os.getenv('OSS_CORE_ENGINE', 'orin-core')
    pa_product_name: str = os.getenv('OSS_PA_NAME', 'Orin AI OS')
    pa_default_companion_name: str = os.getenv('OSS_COMPANION_NAME', 'Orin')
    cli_command_core: str = os.getenv('OSS_CORE_CLI', 'orin')
    cli_command_pa: str = os.getenv('OSS_PA_CLI', 'orin')
    docs_url: str = os.getenv('OSS_DOCS_URL', 'https://github.com/orin-ai/orin-os')

    def get_banner(self) -> str:
        return f'{self.company_name.upper()} — {self.pa_product_name.upper()}'

BRAND = BrandConfig()
