"""
Wallet Rotation — anti-detection with multiple keypairs.

Uses 5-10 pre-generated keypairs in round-robin rotation.
Never uses the same wallet twice in a row.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field

from solders.keypair import Keypair

logger = logging.getLogger(__name__)


@dataclass
class WalletPool:
    keypairs: list[Keypair] = field(default_factory=list)
    last_used_idx: int = -1

    @classmethod
    def generate(cls, count: int = 5) -> WalletPool:
        """Generate N fresh keypairs."""
        pool = cls(keypairs=[Keypair() for _ in range(count)])
        logger.info(
            "Generated %d wallets: %s",
            count, [str(kp.pubkey())[:12] for kp in pool.keypairs],
        )
        return pool

    @classmethod
    def from_private_key(cls, private_key_b58: str) -> WalletPool:
        """Create a pool with a single imported keypair."""
        import base58
        key_bytes = base58.b58decode(private_key_b58)
        kp = Keypair.from_bytes(key_bytes)
        return cls(keypairs=[kp])

    def next_wallet(self) -> Keypair:
        """Round-robin selection, never the same twice consecutively."""
        if not self.keypairs:
            raise RuntimeError("WalletPool is empty")
        if len(self.keypairs) == 1:
            self.last_used_idx = 0
            return self.keypairs[0]

        available = list(range(len(self.keypairs)))
        if self.last_used_idx in available:
            available.remove(self.last_used_idx)
        idx = random.choice(available)
        self.last_used_idx = idx
        return self.keypairs[idx]

    def public_keys(self) -> list[str]:
        return [str(kp.pubkey()) for kp in self.keypairs]
