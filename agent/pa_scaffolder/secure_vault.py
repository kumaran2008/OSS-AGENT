from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, Optional


class SecureVault:
    """Production Key-Value Credential & Preference Vault."""

    VAULT_DIR = Path("workspace")
    DB_PATH = VAULT_DIR / "vault.db"

    def __init__(self):
        self.VAULT_DIR.mkdir(parents=True, exist_ok=True)
        self._salt = b"oss_agent_vault_salt_v1"
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.DB_PATH) as conn:
            cursor = conn.execute("PRAGMA table_info(secrets)")
            cols = {row[1] for row in cursor.fetchall()}
            if cols and "key_name" not in cols:
                conn.execute("DROP TABLE secrets")

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS secrets (
                    key_name TEXT PRIMARY KEY,
                    encrypted_val TEXT NOT NULL,
                    provider TEXT,
                    updated_at REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS config (
                    param TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _get_machine_key(self) -> bytes:
        seed = f"{os.uname().nodename}-{os.getlogin() if hasattr(os, 'getlogin') else 'user'}-oss-friday"
        return hashlib.sha256(seed.encode("utf-8") + self._salt).digest()

    def _encrypt(self, plain_text: str) -> str:
        key = self._get_machine_key()
        pt_bytes = plain_text.encode("utf-8")
        ct_bytes = bytearray(b ^ key[i % len(key)] for i, b in enumerate(pt_bytes))
        return base64.b64encode(ct_bytes).decode("utf-8")

    def _decrypt(self, cipher_b64: str) -> str:
        key = self._get_machine_key()
        try:
            raw = base64.b64decode(cipher_b64.encode("utf-8"))
            pt_bytes = bytearray(b ^ key[i % len(key)] for i, b in enumerate(raw))
            return pt_bytes.decode("utf-8", errors="ignore")
        except Exception:
            return ""

    def store_key(self, key_name: str, value: str, provider: Optional[str] = None) -> bool:
        clean_name = key_name.lower().strip()
        if not value or not value.strip():
            self.delete_key(clean_name)
            return False

        enc = self._encrypt(value.strip())
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO secrets (key_name, encrypted_val, provider, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key_name) DO UPDATE SET
                    encrypted_val=excluded.encrypted_val,
                    provider=excluded.provider,
                    updated_at=excluded.updated_at
                """,
                (clean_name, enc, provider or clean_name, time.time()),
            )
            conn.commit()
        return True

    def delete_key(self, key_name: str) -> bool:
        clean_name = key_name.lower().strip()
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute("DELETE FROM secrets WHERE key_name = ?", (clean_name,))
            conn.commit()
        return True

    def get_key(self, key_name: str) -> Optional[str]:
        clean_name = key_name.lower().strip()
        env_map = {
            "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
            "openrouter": ["OPENROUTER_API_KEY"],
            "deepseek": ["DEEPSEEK_API_KEY"],
            "anthropic": ["ANTHROPIC_API_KEY"],
            "openai": ["OPENAI_API_KEY"],
            "groq": ["GROQ_API_KEY"],
        }
        for env_var in env_map.get(clean_name, [clean_name.upper()]):
            val = os.getenv(env_var)
            if val and val.strip():
                return val.strip()

        with sqlite3.connect(self.DB_PATH) as conn:
            cursor = conn.execute("SELECT encrypted_val FROM secrets WHERE key_name = ?", (clean_name,))
            row = cursor.fetchone()
            if row:
                dec = self._decrypt(row[0]).strip()
                return dec if dec else None
        return None

    def list_keys(self) -> Dict[str, str]:
        result = {}
        with sqlite3.connect(self.DB_PATH) as conn:
            cursor = conn.execute("SELECT key_name, encrypted_val FROM secrets")
            for name, enc in cursor.fetchall():
                dec = self._decrypt(enc)
                if not dec:
                    continue
                result[name] = f"{dec[:4]}••••{dec[-4:]}" if len(dec) > 8 else "••••••••"
        return result

    def set_config(self, param: str, value: str) -> None:
        with sqlite3.connect(self.DB_PATH) as conn:
            conn.execute(
                "INSERT INTO config (param, value) VALUES (?, ?) ON CONFLICT(param) DO UPDATE SET value=excluded.value",
                (param.lower().strip(), value.strip()),
            )
            conn.commit()

    def get_config(self, param: str, default: str = "") -> str:
        with sqlite3.connect(self.DB_PATH) as conn:
            cursor = conn.execute("SELECT value FROM config WHERE param = ?", (param.lower().strip(),))
            row = cursor.fetchone()
            return row[0] if row else default


vault = SecureVault()
