"""On-demand fetch thread (no periodic polling).

Providers are fetched only when a refresh is requested: once at startup,
whenever the panel is shown, or via the manual refresh button / tray menu.
Panel-open refreshes are throttled per provider (``min_gap`` seconds) so
hover flapping does not hammer the rate-limited usage endpoints; forced
refreshes (the refresh button) bypass the throttle. There is no automatic
retry - a failed provider is simply retried on the next refresh request.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from .providers import Provider
from .state import AppState

logger = logging.getLogger("usagetray.poller")

MIN_GAP_SECONDS = 60


class Poller:
    def __init__(
        self,
        providers: list[Provider],
        state: AppState,
        min_gap: int = MIN_GAP_SECONDS,
    ) -> None:
        self._providers = providers
        self._state = state
        self._min_gap = max(0, int(min_gap))
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._pending: set[str] = set()
        # monotonic timestamp of the last fetch attempt per provider
        self._last_fetch: dict[str, float] = {p.id: -float("inf") for p in providers}

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

    def refresh_now(self, force: bool = False) -> None:
        """Request a fetch of every provider.

        ``force=False`` (panel shown) skips providers fetched within the last
        ``min_gap`` seconds; ``force=True`` (refresh button) fetches them all.
        """
        now = time.monotonic()
        queued = False
        with self._lock:
            for provider in self._providers:
                if force or now - self._last_fetch[provider.id] >= self._min_gap:
                    self._pending.add(provider.id)
                    queued = True
        if queued:
            self._wake.set()

    # ---- internals -----------------------------------------------------------

    def poll_provider(self, provider: Provider) -> None:
        """Fetch one provider and update state."""
        self._last_fetch[provider.id] = time.monotonic()
        snapshot = provider.fetch()
        if snapshot.fetched_at is None:
            snapshot.fetched_at = datetime.now(timezone.utc)
        self._state.update(snapshot)
        if not snapshot.ok:
            logger.warning("provider %s failed: %s", provider.id, snapshot.error)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait()
            if self._stop.is_set():
                return
            self._wake.clear()
            with self._lock:
                pending = set(self._pending)
                self._pending.clear()
            for provider in self._providers:
                if self._stop.is_set():
                    return
                if provider.id not in pending:
                    continue
                try:
                    self.poll_provider(provider)
                except Exception:  # top-level safety net
                    logger.exception("unexpected error polling %s", provider.id)
