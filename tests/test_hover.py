"""HoverController: show on heartbeat, hide after grace, stay while inside."""
import time

from usagetray.ui.hover import HoverController


class FakePanel:
    def __init__(self):
        self.is_visible = False
        self.mouse_inside = False
        self.show_calls = 0
        self.hide_calls = 0

    def show(self):
        self.is_visible = True
        self.show_calls += 1

    def hide(self, reason="test"):
        self.is_visible = False
        self.hide_calls += 1


def make(grace=0.1, tick=0.02):
    panel = FakePanel()
    return panel, HoverController(panel, grace=grace, tick=tick)


def test_hover_shows_panel():
    panel, ctrl = make()
    ctrl.on_hover()
    assert panel.is_visible
    assert panel.show_calls == 1


def test_repeated_heartbeats_show_only_once():
    panel, ctrl = make()
    for _ in range(5):
        ctrl.on_hover()
    assert panel.show_calls == 1


def test_hides_after_grace_without_signals():
    panel, ctrl = make()
    ctrl.on_hover()
    time.sleep(0.4)
    assert not panel.is_visible
    assert panel.hide_calls == 1


def test_stays_visible_while_mouse_inside_panel_then_hides_on_leave():
    panel, ctrl = make()
    ctrl.on_hover()
    panel.mouse_inside = True
    time.sleep(0.4)
    assert panel.is_visible
    panel.mouse_inside = False
    time.sleep(0.4)
    assert not panel.is_visible


def test_continuous_heartbeats_keep_panel_visible():
    panel, ctrl = make()
    end = time.monotonic() + 0.3
    while time.monotonic() < end:
        ctrl.on_hover()
        time.sleep(0.02)
    assert panel.is_visible


def test_watchdog_exits_when_hidden_externally():
    panel, ctrl = make()
    ctrl.on_hover()
    panel.is_visible = False  # e.g. hidden by blur
    time.sleep(0.1)
    assert panel.hide_calls == 0  # watchdog returned without double-hiding
