"""GUI assembly + thread model (spec 6.3).

Main thread:    create hidden pywebview window -> webview.start(func=bootstrap)
bootstrap:      start poller thread + pystray run_detached
quit:           icon.stop() then window.destroy()
"""
from __future__ import annotations

import logging
import sys
import threading

import webview

from .config import load_config
from .log import setup_logging
from .poller import Poller
from .providers import build_providers
from .single_instance import SingleInstance
from .state import AppState
from .ui.hover import HoverController, cursor_in_tray_or_panel
from .ui.panel import Panel
from .ui.tray import TrayIcon

logger = logging.getLogger("usagetray.app")


class UsageTrayApp:
    def __init__(self) -> None:
        self.config = load_config()
        self.state = AppState()
        providers = build_providers(
            self.config.get("providers"),
            self.config.get("deepseek_api_key", ""),
        )
        self.poller = Poller(providers, self.state, self.config.get("min_fetch_gap_seconds", 60))
        self.panel = Panel(
            self.state,
            on_refresh=self._on_refresh,
            on_quit=self._on_quit,
            on_shown=self._on_panel_shown,
        )
        self.hover = HoverController(self.panel, inside_check=self._hover_inside_check)
        self.tray = TrayIcon(
            on_show_panel=self.panel.show,
            on_refresh=self._on_refresh,
            on_quit=self._on_quit,
            on_hover=self.hover.on_hover,
        )
        self._quitting = False
        # state changes -> update tray icon + push to panel
        self.state.subscribe(self._on_state_change)

    # ---- callbacks ----------------------------------------------------------

    def _on_state_change(self, snapshots) -> None:
        self.tray.update(snapshots)
        self.panel.push_update(snapshots)

    def _hover_inside_check(self) -> bool:
        return cursor_in_tray_or_panel(
            lambda: getattr(self.tray.icon, "_hwnd", None),
            lambda: self.panel._native_hwnd(),
        )

    def _on_refresh(self) -> None:
        # manual refresh (button / tray menu): bypass the throttle
        self.poller.refresh_now(force=True)

    def _on_panel_shown(self) -> None:
        # hover-open: throttled so flapping over the icon doesn't spam the API
        self.poller.refresh_now()

    def _on_quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        logger.info("quitting")
        try:
            self.poller.stop()
        except Exception:
            pass
        try:
            self.tray.stop()
        except Exception:
            pass
        try:
            self.panel.destroy()
        except Exception:
            pass

    # ---- thread model -------------------------------------------------------

    def _bootstrap(self) -> None:
        # runs after the webview loop is up; start background workers here
        try:
            self.poller.start()
            self.poller.refresh_now()
            self.tray.run_detached()
        except Exception:
            logger.exception("bootstrap failed")

    def run(self) -> int:
        self.panel.create_window()
        # webview.start blocks on the main thread (WebView2 message loop)
        webview.start(self._bootstrap, gui="edgechromium", private_mode=False)
        # returns after window.destroy() -> ensure workers are down
        self._on_quit()
        return 0


def main() -> int:
    setup_logging()
    logger.info(
        "starting (debug=%s)", logging.getLogger("usagetray").level == logging.DEBUG
    )
    instance = SingleInstance()
    if instance.already_running():
        logger.info("another instance is running; exiting")
        print("UsageTray is already running.")
        return 0
    try:
        return UsageTrayApp().run()
    except Exception:
        logger.exception("fatal error")
        return 1
    finally:
        instance.release()


if __name__ == "__main__":
    sys.exit(main())
