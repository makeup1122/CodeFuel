"""pywebview panel: frameless window + JS bridge.

The Python ``Api`` is exposed to JS as ``pywebview.api``. On snapshot updates
Python pushes fresh data via ``evaluate_js``. The window hides on blur and is
re-shown when the tray icon is clicked.
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
    """Bridge object exposed to the panel JS."""

    def __init__(self, state: AppState, on_refresh: Callable[[], None], on_quit: Callable[[], None]):
        self._state = state
        self._on_refresh = on_refresh
        self._on_quit = on_quit
        self.window: "webview.Window | None" = None

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
        if self.window:
            try:
                self.window.hide()
            except Exception:
                pass


class Panel:
    def __init__(self, state: AppState, on_refresh: Callable[[], None], on_quit: Callable[[], None]):
        self._state = state
        self.api = Api(state, on_refresh, on_quit)
        self.window: "webview.Window | None" = None
        self._visible = False

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
        self.api.window = self.window
        return self.window

    # ---- visibility ---------------------------------------------------------

    def _position_bottom_right(self) -> None:
        if not self.window:
            return
        try:
            import ctypes
            from ctypes import wintypes

            SPI_GETWORKAREA = 0x0030
            rect = wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
            x = rect.right - WINDOW_W - 12
            y = rect.bottom - WINDOW_H - 12
            self.window.move(x, y)
        except Exception:
            logger.debug("could not position panel", exc_info=True)

    def show(self) -> None:
        if not self.window:
            return
        try:
            self._position_bottom_right()
            self.window.show()
            self.push_update(self._state.get_all())
            self.window.evaluate_js("window.__refresh && window.__refresh()")
            self._visible = True
        except Exception:
            logger.exception("failed to show panel")

    def hide(self) -> None:
        if not self.window:
            return
        try:
            self.window.hide()
            self._visible = False
        except Exception:
            pass

    def toggle(self) -> None:
        if self._visible:
            self.hide()
        else:
            self.show()

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
