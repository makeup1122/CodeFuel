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

logger = logging.getLogger("codefuel.panel")

WINDOW_W = 400          # CSS px; physical size derives from per-window DPI
WINDOW_H = 320          # initial height only; show() auto-fits to content
MAX_CSS_HEIGHT = 900    # sanity cap before workarea clamping

# Natural content height in CSS px (body is locked to 100vh, so measure the
# parts) plus the current viewport size. The caller derives the CSS-to-window
# pixel ratio from viewport vs window rect - WebView2 zooms to the real
# monitor DPI even when our process is DPI-virtualized, so no fixed factor
# (GetDpiForWindow or devicePixelRatio alone) is reliable.
MEASURE_JS = (
    "(function(){"
    "var q=function(s){return document.querySelector(s)};"
    "var h=q('header'),m=q('main'),f=q('footer');"
    "if(!h||!m||!f){return null;}"
    "var fr=f.getBoundingClientRect();"
    "return {c: h.offsetHeight + m.scrollHeight + f.offsetHeight + 4,"
    "        vh: window.innerHeight, vw: window.innerWidth,"
    "        fb: fr.bottom, dpr: window.devicePixelRatio};"
    "})()"
)


def _html_path() -> str:
    # When frozen by PyInstaller, data files live under sys._MEIPASS.
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidate = Path(base) / "codefuel" / "ui" / "panel.html"
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
        order = {"claude": 0, "codex": 1, "deepseek": 2}
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
    def __init__(
        self,
        state: AppState,
        on_refresh: Callable[[], None],
        on_quit: Callable[[], None],
        on_shown: Callable[[], None] | None = None,
        width: int = WINDOW_W,
    ):
        self._state = state
        self._on_shown = on_shown
        self._width = int(width)
        self.api = Api(state, on_refresh, on_quit)
        self.api._panel = self
        self.window: "webview.Window | None" = None
        self._visible = False
        self._showing = False  # reentry guard for show() (see show() docstring)
        self.mouse_inside = False
        self._styles_applied = False

    def create_window(self) -> "webview.Window":
        self.window = webview.create_window(
            "CodeFuel",
            url=_html_path(),
            js_api=self.api,
            width=self._width,
            height=WINDOW_H,
            frameless=True,
            easy_drag=False,
            on_top=True,
            hidden=True,
            resizable=False,
            focus=False,  # pywebview sets WS_EX_NOACTIVATE for us
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

    def _apply_widget_styles(self, hwnd: int) -> None:
        """One-time window styles for hover-widget behaviour.

        WS_EX_NOACTIVATE: showing/clicking the panel never steals keyboard
        focus from whatever the user is typing in (mouse clicks on the panel's
        buttons still work; pywebview also sets this via focus=False, kept
        here as a belt-and-braces guarantee). WS_EX_TOOLWINDOW: keep the
        widget out of Alt-Tab.
        """
        if self._styles_applied:
            return
        import ctypes
        from ctypes import wintypes

        GWL_EXSTYLE = -20
        WS_EX_NOACTIVATE = 0x08000000
        WS_EX_TOOLWINDOW = 0x00000080

        user32 = ctypes.windll.user32
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_longlong
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
        user32.SetWindowLongPtrW.restype = ctypes.c_longlong

        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(
            hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        )
        self._styles_applied = True
        logger.debug("applied WS_EX_NOACTIVATE|WS_EX_TOOLWINDOW")

    def _show_no_activate(self) -> bool:
        """Show via the WinForms path but WITHOUT pywebview's Activate() call.

        pywebview's window.show() runs ``Show(); Activate()`` and Activate()
        explicitly steals foreground even from a WS_EX_NOACTIVATE window.
        Returns False if the .NET interop isn't available so the caller can
        fall back to window.show().
        """
        try:
            native = getattr(self.window, "native", None)
            if native is None:
                return False
            from System import Func, Type  # pythonnet, already loaded by pywebview

            def _show():
                native.Show()

            if native.InvokeRequired:
                native.Invoke(Func[Type](_show))
            else:
                _show()
            return True
        except Exception:
            logger.debug("no-activate show failed; falling back", exc_info=True)
            return False

    def _apply_bounds(self, hwnd: int, measure: dict | None) -> None:
        """Size to content and position above the tray clock WITHOUT showing.

        Uses raw GetWindowRect/SPI_GETWORKAREA/SetWindowPos so every value is
        in the same coordinate space. pywebview's own move()/resize() expect
        logical pixels and rescale them (double-applying the DPI factor on
        high-DPI displays), and resize() additionally passes SWP_SHOWWINDOW
        without SWP_NOACTIVATE, which would steal focus.

        Showing must go through the WinForms path (_show_no_activate):
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
        cur_w = wr.right - wr.left
        cur_h = wr.bottom - wr.top

        flags = SWP_NOACTIVATE
        w, h = cur_w, cur_h
        try:
            content = float(measure["c"])
            vh = float(measure["vh"])
            vw = float(measure["vw"])
            ratio = cur_h / vh  # window px per CSS px (zoom + chrome combined)
            if content > 0 and ratio > 0:
                # delta correction: chrome offset between outer rect and
                # viewport is constant, so adjust relative to current size
                target = min(content, MAX_CSS_HEIGHT)
                h = int(round(cur_h + (target - vh) * ratio))
                w = int(round(cur_w + (self._width - vw) * ratio))
                h = min(h, wa.bottom - wa.top - 24)  # never taller than workarea
            else:
                flags |= SWP_NOSIZE
        except (TypeError, KeyError, ValueError, ZeroDivisionError):
            flags |= SWP_NOSIZE  # measurement failed: keep current size
        x = wa.right - w - 12
        y = wa.bottom - h - 12
        ok = user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, w, h, flags)
        if not ok:
            logger.warning("SetWindowPos failed (err=%s)", ctypes.GetLastError())

    def show(self) -> None:
        """Show and size the panel above the tray clock.

        Reentrancy: ``evaluate_js`` below pumps the Win32 message loop, so the
        tray's WM_MOUSEMOVE stream re-enters ``show()`` (via the hover callback)
        before ``_visible`` flips at the end. Without the ``_showing`` guard each
        re-entry re-measures and resizes the already-visible window, producing a
        burst of resizes that looks like jitter as the panel pops up.
        """
        if not self.window:
            logger.warning("show() called before window creation")
            return
        if self._showing:
            return
        self._showing = True
        try:
            self._show_inner()
        finally:
            self._showing = False

    def _show_inner(self) -> None:
        if self._on_shown:
            try:
                # kick off an async (throttled) fetch; fresh data lands via
                # the state-change callback -> push_update once it arrives
                self._on_shown()
            except Exception:
                logger.debug("on_shown callback failed", exc_info=True)
        try:
            # render data first (window may still be hidden) so the content
            # height measured below is current
            self.push_update(self._state.get_all())
            self.window.evaluate_js("window.__refresh && window.__refresh()")
            hwnd = self._native_hwnd()
            if hwnd:
                self._apply_widget_styles(hwnd)
                # fit window to content iteratively: chrome offsets and the
                # WebView2 zoom factor make any single-pass conversion drift,
                # so re-measure after each adjustment until viewport == content
                for attempt in range(3):
                    try:
                        measure = self.window.evaluate_js(MEASURE_JS)
                    except Exception:
                        logger.debug("content measurement failed", exc_info=True)
                        measure = None
                    logger.debug(
                        "panel show: bounds pass %s hwnd=%s measure=%s",
                        attempt, hwnd, measure,
                    )
                    self._apply_bounds(hwnd, measure)
                    if not measure:
                        break
                    try:
                        if abs(float(measure["c"]) - float(measure["vh"])) <= 2:
                            break
                    except (TypeError, KeyError, ValueError):
                        break
            if not self._show_no_activate():
                self.window.show()
            self._visible = True
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
        order = {"claude": 0, "codex": 1, "deepseek": 2}
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
