import os
from agent.core.branding import BRAND, BrandConfig

print("--- Default Engine Branding ---")
print(BRAND.get_banner())
print(f"Company: {BRAND.company_name}")
print(f"Core CLI: {BRAND.cli_command_core}")
print(f"PA CLI: {BRAND.cli_command_pa}")

# Simulating future company name change
os.environ["OSS_COMPANY_NAME"] = "NexusAI"
os.environ["OSS_CORE_CLI"] = "nexus"
custom_brand = BrandConfig()

print("\n--- Dynamically Rebranded ---")
print(custom_brand.get_banner())
print(f"Company: {custom_brand.company_name}")
print(f"Core CLI: {custom_brand.cli_command_core}")
