import os
import sys
from pathlib import Path
from agent.training.hf_hub_bridge import HuggingFaceHubBridge
from agent.core.dynamic_auth import auth_manager

print("=" * 60)
print("     HUGGING FACE COLLECTIVE HUB AUTO-PROVISIONER")
print("=" * 60)
print("This will link your account and create:")
print("  1. Dataset Repo: <your-user>/oss-agent-collective-data")
print("  2. Model Repo:   <your-user>/pa-adapters")
print("=" * 60 + "\n")

token = input("Paste your Hugging Face Token (write-access from hf.co/settings/tokens): ").strip()
if not token:
    print("[!] No token provided. OSS-Agent will continue running in 100% offline local mode.")
    sys.exit(0)

bridge = HuggingFaceHubBridge(token=token)
user = bridge.get_authenticated_user()

if not user:
    print("[ERROR] Could not authenticate with Hugging Face. Check that your token has write permissions.")
    sys.exit(1)

print(f"\n[✓] Authenticated as Hugging Face user: @{user}")

# 1. Provision Dataset Repo
print("\n[*] Provisioning Dataset Repository...")
ok_data, msg_data = bridge.ensure_repository("oss-agent-collective-data", repo_type="dataset", private=False)
print(f"    • {msg_data}")

# 2. Provision Model Repo
print("\n[*] Provisioning LoRA Adapters Repository...")
ok_model, msg_model = bridge.ensure_repository("pa-adapters", repo_type="model", private=False)
print(f"    • {msg_model}")

# 3. Save Token to .env
auth_manager.update_key("HUGGINGFACE_TOKEN", token)
print("\n[✓] Token hot-reloaded and saved to .env")
print("\nYour OSS-Agent and Personal Agents are now connected to the collective repository.")
