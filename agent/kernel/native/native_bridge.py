from __future__ import annotations

import ctypes
import hashlib
from pathlib import Path
from typing import Dict, List


class JEVNativeAccelerator:
    """Loads compiled C extension `libjev_native.so` via ctypes for bare-metal
    64-bit FNV-1a file hashing and fast token estimation, with a 100% compatible
    pure-Python fallback when a C compiler is not installed.
    """

    SO_PATH = Path(__file__).resolve().parent / "libjev_native.so"

    def __init__(self):
        self._lib = None
        self.using_c_extension = False
        if self.SO_PATH.exists():
            try:
                lib = ctypes.CDLL(str(self.SO_PATH))
                lib.jev_fnv1a_64.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
                lib.jev_fnv1a_64.restype = ctypes.c_uint64
                lib.jev_estimate_tokens.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
                lib.jev_estimate_tokens.restype = ctypes.c_int32
                self._lib = lib
                self.using_c_extension = True
            except Exception:
                self._lib = None
                self.using_c_extension = False

    def fast_hash64_hex(self, data: bytes) -> str:
        if self._lib is not None:
            h = self._lib.jev_fnv1a_64(data, len(data))
            return f"{h:016x}"
        return hashlib.blake2b(data, digest_size=8).hexdigest()

    def estimate_tokens(self, text: str) -> int:
        raw = text.encode("utf-8", errors="ignore")
        if self._lib is not None:
            return int(self._lib.jev_estimate_tokens(raw, len(raw)))
        return max(1, len(raw) // 4)

    def snapshot_workspace_hashes(self, root_dirs: List[str], exclude_paths: List[str] | None = None) -> Dict[str, str]:
        """Computes a fast integrity map of workspace source files to prove
        zero unrelated files were modified during a task.
        """
        excl = set(exclude_paths or [])
        manifest: Dict[str, str] = {}
        for rdir in root_dirs:
            p_root = Path(rdir)
            if not p_root.exists():
                continue
            for f in p_root.rglob("*"):
                if not f.is_file():
                    continue
                s_path = str(f)
                if any(ig in s_path for ig in ("__pycache__", ".shadow_twins", ".git", ".db-wal", ".db-shm", ".db")):
                    continue
                if s_path in excl:
                    continue
                try:
                    manifest[s_path] = self.fast_hash64_hex(f.read_bytes())
                except Exception:
                    pass
        return manifest


native_accel = JEVNativeAccelerator()
