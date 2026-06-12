"""Hover-to-show controller for the tray icon + panel.

WM_MOUSEMOVE only arrives while the cursor MOVES, so heartbeats alone cannot
tell "cursor resting on the icon" from "cursor left": hiding on stale
heartbeats makes Windows re-evaluate the hover and immediately re-deliver
WM_MOUSEMOVE, flickering the panel. The watchdog therefore polls the actual
cursor position: the panel stays up while the cursor is inside the tray icon
rect or the panel rect, and hides LINGER_SECONDS after it leaves both.

``on_hover`` (the WM_MOUSEMOVE heartbeat) is only the show trigger plus a
fallback inside-signal for when the icon rect cannot be resolved.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

LINGER_SECONDS = 2.0
TICK_SECONDS = 0.15
HEARTBEAT_FRESH_SECONDS = 0.35


class HoverController:
    def __init__(
        self,
        panel,
        inside_check: Callable[[], bool] | None = None,
        linger: float = LINGER_SECONDS,
        tick: float = TICK_SECONDS,
    ):
        self._panel = panel
        self._inside_check = inside_check
        self._linger = linger
        self._tick = tick
        self._last_signal = 0.0
        self._last_inside = 0.0
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

    def _is_inside(self) -> bool:
        if self._panel.mouse_inside:
            return True
        if time.monotonic() - self._last_signal < HEARTBEAT_FRESH_SECONDS:
            return True
        if self._inside_check is not None:
            try:
                return self._inside_check()
            except Exception:
                return False
        return False

    def _watch(self) -> None:
        self._last_inside = time.monotonic()
        while True:
            time.sleep(self._tick)
            if not self._panel.is_visible:
                return  # hidden by blur/quit; nothing left to watch
            if self._is_inside():
                self._last_inside = time.monotonic()
                continue
            if time.monotonic() - self._last_inside > self._linger:
                self._panel.hide(reason="hover-watchdog")
                return


# ---- win32 helpers for the production inside_check ---------------------------


def cursor_in_tray_or_panel(tray_hwnd_provider, panel_hwnd_provider, margin: int = 6) -> bool:
    """True if the cursor is inside the tray icon rect or the panel rect.

    Providers are callables returning an HWND (or None) so the values can be
    resolved lazily - pystray only has its hwnd after run_detached().
    All coordinates come from the same process so DPI handling is consistent.
    """
    import ctypes
    from ctypes import wintypes

    pt = wintypes.POINT()
    if not ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
        return False

    def _contains(r: wintypes.RECT) -> bool:
        return (
            r.left - margin <= pt.x <= r.right + margin
            and r.top - margin <= pt.y <= r.bottom + margin
        )

    tray_hwnd = tray_hwnd_provider()
    if tray_hwnd:
        rect = _tray_icon_rect(int(tray_hwnd))
        if rect is not None and _contains(rect):
            return True

    panel_hwnd = panel_hwnd_provider()
    if panel_hwnd:
        rect = wintypes.RECT()
        if ctypes.windll.user32.GetWindowRect(int(panel_hwnd), ctypes.byref(rect)):
            if _contains(rect):
                return True
    return False


def _tray_icon_rect(hwnd: int):
    """Screen rect of our notification icon via Shell_NotifyIconGetRect.

    pystray registers its icon with uID=0 (its ``hID=id(self)`` kwarg is not a
    NOTIFYICONDATAW field, so ctypes leaves uID at 0). Returns None if the
    icon rect cannot be resolved (e.g. API failure).
    """
    import ctypes
    from ctypes import wintypes

    class NOTIFYICONIDENTIFIER(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("hWnd", wintypes.HWND),
            ("uID", wintypes.UINT),
            ("guidItem", ctypes.c_byte * 16),
        ]

    nii = NOTIFYICONIDENTIFIER()
    nii.cbSize = ctypes.sizeof(NOTIFYICONIDENTIFIER)
    nii.hWnd = hwnd
    nii.uID = 0
    rect = wintypes.RECT()
    res = ctypes.windll.shell32.Shell_NotifyIconGetRect(
        ctypes.byref(nii), ctypes.byref(rect)
    )
    if res != 0:  # S_OK
        return None
    return rect
