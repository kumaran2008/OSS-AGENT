from agent.kernel.native.native_bridge import native_accel, JEVNativeAccelerator

import hashlib as _hashlib

class _FallbackNativeAccelerator:
    def fnv1a_hash_bytes(self, data: bytes) -> int:
        h = 0xcbf29ce484222325
        for b in data:
            h ^= b
            h = (h * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
        return h

try:
    from agent.kernel.native.native_bridge import JEVNativeAccelerator as _JEVNat
    native_accelerator = _JEVNat()
    if not hasattr(native_accelerator, "fnv1a_hash_bytes"):
        native_accelerator.fnv1a_hash_bytes = _FallbackNativeAccelerator().fnv1a_hash_bytes
except Exception:
    native_accelerator = _FallbackNativeAccelerator()
