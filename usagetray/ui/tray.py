"""pystray tray icon: dynamic two-bar usage glyph + menu.

Top bar = Claude (orange), bottom bar = Codex (grey/white). Each bar shows the
provider's most-utilized metric. >90% -> red. Error -> dimmed grey.
Tooltip = short summary. Left click -> toggle panel; right menu -> refresh /
autostart / quit.
"""
from __future__ import annotations

import logging
from typing import Callable

import pystray
from PIL import Image, ImageDraw

from ..config import is_autostart_enabled, set_autostart
from ..models import UsageSnapshot

logger = logging.getLogger("usagetray.tray")

ICON_SIZE = 64  # drawn large, pystray downscales -> crisper bars
BG = (40, 40, 44, 255)
CLAUDE_COLOR = (217, 119, 87, 255)   # #D97757
CODEX_COLOR = (220, 220, 224, 255)
RED = (224, 74, 74, 255)
DIM = (90, 90, 96, 255)
TRACK = (64, 64, 70, 255)


def _bar_color(snapshot: UsageSnapshot | None, base) -> tuple:
    if snapshot is None or not snapshot.ok:
        return DIM
    worst = snapshot.worst_metric
    if worst and worst.used_percent >= 90:
        return RED
    return base


def _bar_fraction(snapshot: UsageSnapshot | None) -> float:
    if snapshot is None or not snapshot.ok:
        return 0.0
    worst = snapshot.worst_metric
    return (worst.used_percent / 100.0) if worst else 0.0


def render_icon(claude: UsageSnapshot | None, codex: UsageSnapshot | None) -> Image.Image:
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), BG)
    d = ImageDraw.Draw(img)
    margin = 8
    bar_h = 18
    gap = 8
    x0, x1 = margin, ICON_SIZE - margin
    width = x1 - x0

    rows = [
        (margin, claude, CLAUDE_COLOR),
        (margin + bar_h + gap, codex, CODEX_COLOR),
    ]
    for y, snap, base in rows:
        # track
        d.rounded_rectangle([x0, y, x1, y + bar_h], radius=4, fill=TRACK)
        frac = _bar_fraction(snap)
        color = _bar_color(snap, base)
        if snap is not None and not snap.ok:
            # error: faint hatch over the track
            for hx in range(x0, x1, 6):
                d.line([(hx, y), (hx + bar_h, y + bar_h)], fill=DIM, width=1)
        elif frac > 0:
            fill_w = max(3, int(width * frac))
            d.rounded_rectangle([x0, y, x0 + fill_w, y + bar_h], radius=4, fill=color)
    return img


def _summary(snap: UsageSnapshot | None, name: str) -> str:
    if snap is None:
        return f"{name} —"
    if not snap.ok:
        return f"{name} 错误"
    worst = snap.worst_metric
    if not worst:
        return f"{name} —"
    return f"{name} {worst.used_percent:.0f}% ({worst.label})"


def build_tooltip(claude: UsageSnapshot | None, codex: UsageSnapshot | None) -> str:
    return f"{_summary(claude, 'Claude')} · {_summary(codex, 'Codex')}"


class TrayIcon:
    def __init__(
        self,
        on_toggle_panel: Callable[[], None],
        on_refresh: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_toggle = on_toggle_panel
        self._on_refresh = on_refresh
        self._on_quit = on_quit
        self._claude: UsageSnapshot | None = None
        self._codex: UsageSnapshot | None = None
        self.icon = pystray.Icon(
            "UsageTray",
            icon=render_icon(None, None),
            title="UsageTray",
            menu=self._build_menu(),
        )

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem("显示/隐藏面板", self._handle_toggle, default=True),
            pystray.MenuItem("立即刷新", self._handle_refresh),
            pystray.MenuItem(
                "开机自启",
                self._handle_autostart,
                checked=lambda item: is_autostart_enabled(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._handle_quit),
        )

    # menu handlers
    def _handle_toggle(self, icon, item):
        self._on_toggle()

    def _handle_refresh(self, icon, item):
        self._on_refresh()

    def _handle_autostart(self, icon, item):
        set_autostart(not is_autostart_enabled())
        icon.update_menu()

    def _handle_quit(self, icon, item):
        self._on_quit()

    # state update (called from state callback / any thread)
    def update(self, snapshots: dict[str, UsageSnapshot]) -> None:
        self._claude = snapshots.get("claude")
        self._codex = snapshots.get("codex")
        try:
            self.icon.icon = render_icon(self._claude, self._codex)
            self.icon.title = build_tooltip(self._claude, self._codex)
        except Exception:
            logger.exception("failed to update tray icon")

    def run_detached(self) -> None:
        self.icon.run_detached()

    def stop(self) -> None:
        try:
            self.icon.stop()
        except Exception:
            pass
