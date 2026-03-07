"""
Simple in-memory counters and latency tracking.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Metrics:
    pools_seen: int = 0
    pools_passed: int = 0
    trades_executed: int = 0
    trades_failed: int = 0
    errors: int = 0
    ws_reconnects: int = 0
    _latencies: dict[str, list[float]] = field(default_factory=dict)

    def record_latency(self, label: str, ms: float) -> None:
        if label not in self._latencies:
            self._latencies[label] = []
        self._latencies[label].append(ms)
        # Keep last 1000 entries
        if len(self._latencies[label]) > 1000:
            self._latencies[label] = self._latencies[label][-500:]

    def avg_latency(self, label: str) -> float:
        values = self._latencies.get(label, [])
        return sum(values) / len(values) if values else 0.0

    def summary(self) -> dict:
        latency_summary = {
            k: f"{self.avg_latency(k):.0f}ms" for k in self._latencies
        }
        return {
            "pools_seen": self.pools_seen,
            "pools_passed": self.pools_passed,
            "trades_executed": self.trades_executed,
            "trades_failed": self.trades_failed,
            "errors": self.errors,
            "ws_reconnects": self.ws_reconnects,
            "avg_latency": latency_summary,
        }


metrics = Metrics()
