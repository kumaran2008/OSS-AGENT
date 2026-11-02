"""
Facade exposing the decoupled standalone Sentinel-Personal agent.
Maintained autonomously by oss-agent.
"""
from templates.sentinel_personal.privacy_guard import StructuralPrivacyGuard
from templates.sentinel_personal.device_controller import EphemeralPersonalAgent

__all__ = ["StructuralPrivacyGuard", "EphemeralPersonalAgent"]
