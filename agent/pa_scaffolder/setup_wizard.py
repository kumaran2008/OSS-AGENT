from __future__ import annotations

import getpass
import json
import os
import sys
import urllib.request
from typing import Optional

from agent.pa_scaffolder.secure_vault import vault
from agent.pa_scaffolder.user_preferences import preferences


def test_openrouter_key(api_key: str) -> bool:
    """Validates OpenRouter API key and checks credit balance."""
    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode())
            data_info = data.get("data", {})
            label = data_info.get("label", "Key")
            usage = data_info.get("usage", 0.0)
            limit = data_info.get("limit", "unlimited")
            print(f"      • Key Verified: '{label}' | Usage: ${usage:.2f} | Limit: {limit}")
            return True
    except Exception as e:
        print(f"      [!] Verification failed: {e}")
        return False


def test_gemini_key(api_key: str) -> bool:
    """Validates Google Gemini API key."""
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"      [!] Verification failed: {e}")
        return False


def run_setup_wizard(force: bool = False) -> None:
    configured = vault.list_configured_providers()
    if configured and not force:
        return

    print("\n" + "=" * 65)
    print("   🤖 OSS-AGENT PRODUCTION SETUP & LLM ONBOARDING WIZARD")
    print("   Zero Code Editing • Encrypted Local Vault • Dynamic Routing")
    print("=" * 65)

    # 1. Google Gemini Key for Multimodal Real-Time Voice
    gemini_key = vault.get_key("gemini")
    if not gemini_key or force:
        print("\n[Step 1/3] Real-Time Voice & Vision Engine (Google Gemini Live)")
        print("  Get your key at: https://aistudio.google.com")
        entered_key = getpass.getpass("  Enter GEMINI_API_KEY (hidden): ").strip()
        if entered_key:
            print("  • Verifying key...")
            if test_gemini_key(entered_key):
                vault.store_key("gemini", entered_key)
                os.environ["GEMINI_API_KEY"] = entered_key
                print("  [✓] Gemini Key validated and encrypted in local vault.")
            else:
                print("  [!] Key could not be verified, storing anyway.")
                vault.store_key("gemini", entered_key)
                os.environ["GEMINI_API_KEY"] = entered_key

    # 2. OpenRouter or Frontier Inference Gateway
    or_key = vault.get_key("openrouter")
    if not or_key or force:
        print("\n[Step 2/3] Cognitive Reasoning Engine (OpenRouter / Unified Gateway)")
        print("  One key powers DeepSeek R1, Claude 3.7 Sonnet, GPT-4o, and o3-mini.")
        print("  Recharge & get key at: https://openrouter.ai/keys")
        entered_or = getpass.getpass("  Enter OPENROUTER_API_KEY (hidden): ").strip()
        if entered_or:
            print("  • Verifying key & checking wallet balance...")
            if test_openrouter_key(entered_or):
                vault.store_key("openrouter", entered_or)
                os.environ["OPENROUTER_API_KEY"] = entered_or
                print("  [✓] OpenRouter Key verified, balance loaded, and encrypted.")
            else:
                vault.store_key("openrouter", entered_or)
                os.environ["OPENROUTER_API_KEY"] = entered_or

    # 3. Model Preference Mapping by Activity
    print("\n[Step 3/3] Activity-to-LLM Allocation Preferences")
    print("  Configure which frontier models handle which tasks (Press Enter for recommended):")

    coding_choice = input(f"  • Coding & AST Bug Healing [{preferences.get_model_for_activity('coding_builder')}]: ").strip()
    if coding_choice:
        preferences.set_model_for_activity("coding_builder", coding_choice)

    math_choice = input(f"  • Deep Research & Math/Proofs [{preferences.get_model_for_activity('research_math')}]: ").strip()
    if math_choice:
        preferences.set_model_for_activity("research_math", math_choice)

    cooking_choice = input(f"  • Cooking & Nutrition Reasoning [{preferences.get_model_for_activity('cooking_health')}]: ").strip()
    if cooking_choice:
        preferences.set_model_for_activity("cooking_health", cooking_choice)

    budget_alert = input(f"  • Wallet Low-Balance Warning Alert (${preferences.prefs['token_budget_alert_threshold']:.2f}): ").strip()
    if budget_alert:
        try:
            preferences.prefs["token_budget_alert_threshold"] = float(budget_alert)
            preferences.save()
        except ValueError:
            pass

    print("\n" + "=" * 65)
    print("  [✓] CONFIGURATION COMPLETE! ALL SECRETS ENCRYPTED IN VAULT.DB")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    run_setup_wizard(force=True)
