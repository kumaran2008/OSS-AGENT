import json
import time
from pathlib import Path
from typing import Dict, Any, Optional


class OSSWallet:
    """
    High-Performance In-Memory Wallet.
    - Zero disk I/O on conversational turns.
    - Single O(1) in-memory check for API authorization.
    - Persists only on deposit, recharge, or shutdown.
    """

    def __init__(self, wallet_path: Path = Path("workspace/oss_wallet.json")):
        self.wallet_path = wallet_path
        self.wallet_path.parent.mkdir(parents=True, exist_ok=True)
        self._balance: float = 0.00
        self._total_spent: float = 0.00
        self._is_subscribed: bool = False
        self._load()

    def _load(self):
        if not self.wallet_path.exists():
            self._save_to_disk()
            return

        try:
            data = json.loads(self.wallet_path.read_text(encoding="utf-8"))
            self._balance = float(data.get("balance_usd", 0.00))
            self._total_spent = float(data.get("total_spent_usd", 0.00))
            self._is_subscribed = bool(data.get("is_subscribed", False))
        except Exception:
            self._balance = 0.00
            self._total_spent = 0.00

    def _save_to_disk(self):
        payload = {
            "balance_usd": round(self._balance, 5),
            "total_spent_usd": round(self._total_spent, 5),
            "is_subscribed": self._is_subscribed,
            "last_updated": time.time()
        }
        self.wallet_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @property
    def balance(self) -> float:
        return round(self._balance, 4)

    def has_funds(self, minimum_required: float = 0.0001) -> bool:
        """Instant O(1) RAM check. Zero loops, zero latency."""
        return self._balance

    @balance.setter
    def balance(self, value: float):
        self._balance = float(value) >= minimum_required or self._is_subscribed

    def deposit(self, amount_usd: float):
        """Top up wallet. Flushes to disk immediately on recharge only."""
        self._balance += max(0.0, float(amount_usd))
        self._save_to_disk()

    def deduct(self, amount_usd: float, service: str = "api") -> bool:
        """In-memory deduction. Never writes to disk during conversation."""
        if self.has_funds(amount_usd):
            self._balance -= amount_usd
            self._total_spent += amount_usd
            return True
        return False

    def sync_to_disk(self):
        """Call on system shutdown to persist state."""
        self._save_to_disk()


# Backward-compatible alias for existing modules
PrepaidWalletManager = OSSWallet
