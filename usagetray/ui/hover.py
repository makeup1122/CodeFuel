"""Hover-to-show controller for the tray icon + panel.

While the cursor is over the tray icon, Windows delivers WM_MOUSEMOVE
repeatedly, so hover arrives as a stream of heartbeats. ``on_hover`` shows the
panel and records the heartbeat; a watchdog thread hides the panel once
neither signal is present for GRACE seconds:

- no hover heartbeat from the tray icon, and
- the cursor is not inside the panel (flag maintained by panel JS)

The grace period also bridges the cursor's travel across the gap between the
tray icon and the panel.
"""
from __future__ import annotations

import threading
import time

GRACE_SECONDS = 0.8
TICK_SECONDS = 0.15


class HoverController:
    def __init__(self, panel, grace: float = GRACE_SECONDS, tick: float = TICK_SECONDS):
        self._panel = panel
        self._grace = grace
        self._tick = tick
        self._last_signal = 0.0
        self._lock = threading.Lock()
        self._watcher: threading.Thread | None = None

    def on_hover(self) -> None:
        """Heartbeat from the tray icon (called from the pystray thread)."""
        self._last_signal = time.monotonic()
        if not self._panel.is_visible:
            self._panel.show()
        self._ensure_watcher()

    def _ensure_watcher(self) -> None:
        with self._lock:
            if self._watcher is not None and self._watcher.is_alive():
                return
            self._watcher = threading.Thread(
                target=self._watch, name="hover-watchdog", daemon=True
            )
            self._watcher.start()

    def _watch(self) -> None:
        while True:
            time.sleep(self._tick)
            if not self._panel.is_visible:
                return  # hidden by blur/quit; nothing left to watch
            if self._panel.mouse_inside:
                self._last_signal = time.monotonic()
                continue
            if time.monotonic() - self._last_signal > self._grace:
                self._panel.hide(reason="hover-watchdog")
                return
