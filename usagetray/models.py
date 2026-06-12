"""Core data models shared across providers, poller, state and UI.

Platform-independent. No I/O here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Metric:
    """A single limit window for a provider.

    ``used_percent`` is 0-100. ``resets_at`` is UTC (tz-aware) or None.
    ``kind`` is "percent" (progress bar) or "amount" (text like a balance);
    amount metrics carry their display string in ``text`` and ignore
    ``used_percent``.
    """

    label: str
    used_percent: float
    resets_at: datetime | None = None
    kind: str = "percent"
    text: str | None = None

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "used_percent": round(self.used_percent, 1),
            "resets_at": self.resets_at.isoformat() if self.resets_at else None,
            "kind": self.kind,
            "text": self.text,
        }


@dataclass
class UsageSnapshot:
    """Result of one ``Provider.fetch()`` call.

    On failure ``metrics`` is empty and ``error`` carries a human-readable
    message (with a fix hint). On success ``error`` is None.
    """

    provider_id: str
    display_name: str
    metrics: list[Metric] = field(default_factory=list)
    fetched_at: datetime | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def worst_metric(self) -> Metric | None:
        """The percent metric with the highest utilization (most urgent limit).

        Amount metrics (balances) have no utilization and are excluded so they
        never drive the tray red-threshold logic.
        """
        percent_metrics = [m for m in self.metrics if m.kind == "percent"]
        if not percent_metrics:
            return None
        return max(percent_metrics, key=lambda m: m.used_percent)

    def to_dict(self) -> dict:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "metrics": [m.to_dict() for m in self.metrics],
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "error": self.error,
        }
