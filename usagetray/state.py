"""Thread-safe snapshot cache with change callbacks.

UI reads from here; the poller writes here. Never touches the network.
"""
from __future__ import annotations

import threading
from typing import Callable

from .models import UsageSnapshot

Callback = Callable[[dict[str, UsageSnapshot]], None]


class AppState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshots: dict[str, UsageSnapshot] = {}
        self._callbacks: list[Callback] = []

    def update(self, snapshot: UsageSnapshot) -> None:
        """Store a snapshot. If the new one is an error but we have a prior
        successful snapshot, keep the prior metrics for display while still
        surfacing the error (handled by callers reading ``get_all``)."""
        with self._lock:
            self._snapshots[snapshot.provider_id] = snapshot
            callbacks = list(self._callbacks)
            snaps = dict(self._snapshots)
        for cb in callbacks:
            try:
                cb(snaps)
            except Exception:
                pass

    def get(self, provider_id: str) -> UsageSnapshot | None:
        with self._lock:
            return self._snapshots.get(provider_id)

    def get_all(self) -> dict[str, UsageSnapshot]:
        with self._lock:
            return dict(self._snapshots)

    def subscribe(self, callback: Callback) -> None:
        with self._lock:
            self._callbacks.append(callback)
