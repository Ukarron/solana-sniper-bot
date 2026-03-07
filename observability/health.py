"""
Health Check System — self-diagnostics for all bot components.

States: HEALTHY → DEGRADED → UNHEALTHY
Alerts via Telegram when state changes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class HealthCheck:
    components: dict[str, dict] = field(default_factory=dict)
    last_heartbeat: float = 0
    start_time: float = field(default_factory=time.time)

    def update(self, component: str, healthy: bool, detail: str = "") -> None:
        self.components[component] = {
            "healthy": healthy,
            "detail": detail,
            "last_check": time.time(),
        }

    @property
    def overall_status(self) -> HealthStatus:
        if not self.components:
            return HealthStatus.UNHEALTHY
        unhealthy = [k for k, v in self.components.items() if not v["healthy"]]
        if len(unhealthy) == 0:
            return HealthStatus.HEALTHY
        elif len(unhealthy) <= 1:
            return HealthStatus.DEGRADED
        return HealthStatus.UNHEALTHY

    @property
    def uptime_hours(self) -> float:
        return (time.time() - self.start_time) / 3600

    def summary(self) -> dict:
        return {
            "status": self.overall_status.value,
            "uptime_h": round(self.uptime_hours, 1),
            "components": self.components,
        }


health = HealthCheck()


async def health_monitor_loop(
    notifier,
    rpc_check_fn=None,
    balance_check_fn=None,
    check_interval: int = 60,
) -> None:
    """Background task: periodically check components and alert on status change."""
    prev_status = HealthStatus.HEALTHY

    while True:
        try:
            if rpc_check_fn:
                rpc_ok = await rpc_check_fn()
                health.update("rpc", rpc_ok, "responsive" if rpc_ok else "timeout")

            if balance_check_fn:
                balance = await balance_check_fn()
                health.update("balance", balance > 0.1, f"{balance:.2f} SOL")

            health.last_heartbeat = time.time()

            current = health.overall_status
            if current != prev_status:
                summary = json.dumps(health.summary(), indent=2, default=str)
                if current == HealthStatus.UNHEALTHY:
                    notifier.alert(f"🚨 <b>BOT UNHEALTHY</b>\n<pre>{summary}</pre>")
                elif current == HealthStatus.DEGRADED:
                    notifier.alert(f"⚠️ <b>BOT DEGRADED</b>\n<pre>{summary}</pre>")
                elif prev_status != HealthStatus.HEALTHY:
                    notifier.alert("✅ <b>BOT RECOVERED</b> — all systems healthy")
                prev_status = current

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug("Health check error: %s", e)

        await asyncio.sleep(check_interval)
