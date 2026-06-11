"""pywebview panel: frameless window + JS bridge.

The Python ``Api`` is exposed to JS as ``pywebview.api``. On snapshot updates
Python pushes fresh data via ``evaluate_js``. The window is shown on tray-icon
hover (HoverController) and hides on blur or when the cursor leaves both the
tray icon and the panel. All hide paths go through ``Panel.hide()`` so the
visibility flag stays in sync.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Callable

import webview

from ..models import UsageSnapshot
from ..state import AppState

logger = logging.getLogger("usagetray.panel")

WINDOW_W = 360
WINDOW_H = 320


def _html_path() -> str:
    # When frozen by PyInstaller, data files live under sys._MEIPASS.
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidate = Path(base) / "usagetray" / "ui" / "panel.html"
        if candidate.exists():
            return str(candidate)
    return str(Path(__file__).with_name("panel.html"))


class Api:
    """Bridge object exposed to the panel JS.

    All non-method attributes MUST be underscore-prefixed: pywebview walks the
    js_api object's public attributes recursively to build the JS bridge, so a
    public reference back to Panel/Window creates a reference cycle that hangs
    window creation (generate_js_object recurses forever).
    """

    def __init__(self, state: AppState, on_refresh: Callable[[], None], on_quit: Callable[[], None]):
        self._state = state
        self._on_refresh = on_refresh
        self._on_quit = on_quit
        self._panel: "Panel | None" = None

    def get_snapshots(self) -> list[dict]:
        snaps = self._state.get_all()
        # stable order: claude then codex then others
        order = {"claude": 0, "codex": 1}
        items = sorted(snaps.values(), key=lambda s: order.get(s.provider_id, 99))
        return [s.to_dict() for s in items]

    def refresh(self) -> None:
        self._on_refresh()

    def quit(self) -> None:
        self._on_quit()

    def hide(self) -> None:
        # must go through Panel.hide() to keep the visibility flag in sync
        if self._panel:
            self._panel.hide(reason="js-blur")

    def set_mouse_inside(self, inside: bool) -> None:
        if self._panel:
            self._panel.mouse_inside = bool(inside)


class Panel:
    def __init__(self, state: AppState, on_refresh: Callable[[], None], on_quit: Callable[[], None]):
        self._state = state
        self.api = Api(state, on_refresh, on_quit)
        self.api._panel = self
        self.window: "webview.Window | None" = None
        self._visible = False
        self.mouse_inside = False

    def create_window(self) -> "webview.Window":
        self.window = webview.create_window(
            "UsageTray",
            url=_html_path(),
            js_api=self.api,
            width=WINDOW_W,
            height=WINDOW_H,
            frameless=True,
            easy_drag=False,
            on_top=True,
            hidden=True,
            resizable=False,
        )
        return self.window

    # ---- visibility ---------------------------------------------------------

    def _native_hwnd(self) -> int | None:
        """HWND of the WinForms form backing the pywebview window."""
        try:
            native = getattr(self.window, "native", None)
            if native is None:
                return None
            return int(native.Handle.ToInt64())
        except Exception:
            logger.debug("could not get native hwnd", exc_info=True)
            return None

    def _position_bottom_right(self, hwnd: int) -> None:
        """Position above the tray clock (and pin topmost) WITHOUT showing.

        Uses raw GetWindowRect/SPI_GETWORKAREA/SetWindowPos so every value is
        in the same coordinate space. pywebview's own move() expects logical
        pixels and rescales them, which double-applies the DPI factor and can
        push the panel off-screen on high-DPI displays.

        Showing must go through pywebview's window.show() (the WinForms path):
        making the form visible with bare SetWindowPos(SWP_SHOWWINDOW) leaves
        the WebView2 control uncomposited - the form appears blank white even
        though the page and JS are fully functional.
        """
        import ctypes
        from ctypes import wintypes

        SPI_GETWORKAREA = 0x0030
        HWND_TOPMOST = -1
        SWP_NOSIZE = 0x0001
        SWP_NOACTIVATE = 0x0010
        SWP_SHOWWINDOW = 0x0040

        user32 = ctypes.windll.user32
        # 64-bit HWND args are mangled without explicit prototypes (e.g.
        # HWND_TOPMOST=-1 is passed as a 32-bit int and the call fails)
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

        wa = wintypes.RECT()
        user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(wa), 0)
        wr = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(wr))
        w = wr.right - wr.left
        h = wr.bottom - wr.top
        x = wa.right - w - 12
        y = wa.bottom - h - 12
        ok = user32.SetWindowPos(
            hwnd, HWND_TOPMOST, x, y, 0, 0,
            SWP_NOSIZE | SWP_NOACTIVATE,
        )
        if not ok:
            logger.warning("SetWindowPos failed (err=%s)", ctypes.GetLastError())

    def show(self) -> None:
        if not self.window:
            logger.warning("show() called before window creation")
            return
        try:
            hwnd = self._native_hwnd()
            if hwnd:
                logger.debug("panel show: positioning hwnd=%s", hwnd)
                self._position_bottom_right(hwnd)
            self.window.show()
            self._visible = True
            self.push_update(self._state.get_all())
            self.window.evaluate_js("window.__refresh && window.__refresh()")
            if logger.isEnabledFor(logging.DEBUG):
                page = self.window.evaluate_js(
                    "document.readyState + ' | ' + location.href + ' | __render=' + (typeof window.__render)"
                )
                logger.debug("panel page state: %s", page)
            logger.debug("panel show: done")
        except Exception:
            logger.exception("failed to show panel")

    def hide(self, reason: str = "unspecified") -> None:
        if not self.window:
            return
        logger.debug("panel hide (%s)", reason)
        try:
            self.window.hide()
        except Exception:
            pass
        self._visible = False
        self.mouse_inside = False

    @property
    def is_visible(self) -> bool:
        return self._visible

    # ---- data push ----------------------------------------------------------

    def push_update(self, snapshots: dict[str, UsageSnapshot]) -> None:
        if not self.window:
            return
        order = {"claude": 0, "codex": 1}
        items = sorted(snapshots.values(), key=lambda s: order.get(s.provider_id, 99))
        payload = json.dumps([s.to_dict() for s in items], ensure_ascii=False)
        try:
            self.window.evaluate_js(f"window.__render && window.__render({payload})")
        except Exception:
            logger.debug("evaluate_js push failed", exc_info=True)

    def destroy(self) -> None:
        if self.window:
            try:
                self.window.destroy()
            except Exception:
                pass
