"""Background polling thread with per-provider error backoff.

Each provider is polled on its own schedule. A provider that keeps failing
backs off (60 -> 120 -> 300s, capped) without affecting the others. A manual
refresh wakes the thread to poll everything immediately.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from .providers import Provider
from .state import AppState

logger = logging.getLogger("usagetray.poller")

BACKOFF_LADDER = [60, 120, 300]  # seconds; index by min(failures-1, last)


class Poller:
    def __init__(
        self,
        providers: list[Provider],
        state: AppState,
        interval: int = 60,
    ) -> None:
        self._providers = providers
        self._state = state
        self._interval = max(5, int(interval))
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # per-provider scheduling
        self._next_due: dict[str, float] = {p.id: 0.0 for p in providers}
        self._failures: dict[str, int] = {p.id: 0 for p in providers}

    # ---- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="usagetray-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def refresh_now(self) -> None:
        """Force every provider due immediately and wake the loop."""
        now = time.monotonic()
        for pid in self._next_due:
            self._next_due[pid] = now
        self._wake.set()

    # ---- internals -----------------------------------------------------------

    def _backoff_for(self, failures: int) -> int:
        if failures <= 0:
            return self._interval
        idx = min(failures - 1, len(BACKOFF_LADDER) - 1)
        return BACKOFF_LADDER[idx]

    def poll_provider(self, provider: Provider) -> None:
        """Fetch one provider, update state, and reschedule with backoff."""
        snapshot = provider.fetch()
        if snapshot.fetched_at is None:
            snapshot.fetched_at = datetime.now(timezone.utc)
        self._state.update(snapshot)

        if snapshot.ok:
            self._failures[provider.id] = 0
            delay = self._interval
        else:
            self._failures[provider.id] += 1
            delay = self._backoff_for(self._failures[provider.id])
            logger.warning("provider %s failed: %s (next in %ss)", provider.id, snapshot.error, delay)
        self._next_due[provider.id] = time.monotonic() + delay

    def _run(self) -> None:
        while not self._stop.is_set():
            now = time.monotonic()
            soonest = now + self._interval
            for provider in self._providers:
                if self._stop.is_set():
                    return
                if now >= self._next_due.get(provider.id, 0.0):
                    try:
                        self.poll_provider(provider)
                    except Exception:  # top-level safety net
                        logger.exception("unexpected error polling %s", provider.id)
                        self._failures[provider.id] += 1
                        self._next_due[provider.id] = time.monotonic() + self._backoff_for(
                            self._failures[provider.id]
                        )
                soonest = min(soonest, self._next_due.get(provider.id, soonest))

            wait = max(0.0, soonest - time.monotonic())
            woke = self._wake.wait(timeout=wait)
            if woke:
                self._wake.clear()
