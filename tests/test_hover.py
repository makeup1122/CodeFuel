"""HoverController: show on heartbeat, stay while cursor inside, linger then hide."""
import time

from codefuel.ui.hover import HoverController


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


class FakeRegion:
    """Stands in for the win32 cursor-in-tray-or-panel check."""

    def __init__(self, inside=False):
        self.inside = inside

    def __call__(self):
        return self.inside


def make(inside=False, linger=0.15, tick=0.02):
    panel = FakePanel()
    region = FakeRegion(inside)
    ctrl = HoverController(panel, inside_check=region, linger=linger, tick=tick)
    # heartbeats must not mask the region signal in these tests
    ctrl._last_signal = time.monotonic() - 10
    return panel, region, ctrl


def hover(ctrl):
    ctrl.on_hover()
    ctrl._last_signal = time.monotonic() - 10  # age the heartbeat immediately


def test_hover_shows_panel():
    panel, _, ctrl = make()
    ctrl.on_hover()
    assert panel.is_visible
    assert panel.show_calls == 1


def test_repeated_heartbeats_show_only_once():
    panel, _, ctrl = make()
    for _ in range(5):
        ctrl.on_hover()
    assert panel.show_calls == 1


def test_stays_visible_while_cursor_rests_on_icon():
    # cursor inside but NOT moving: no fresh heartbeats, region check true
    panel, region, ctrl = make(inside=True)
    hover(ctrl)
    time.sleep(0.5)
    assert panel.is_visible
    assert panel.hide_calls == 0


def test_hides_after_linger_once_cursor_leaves():
    panel, region, ctrl = make(inside=True)
    hover(ctrl)
    region.inside = False
    start = time.monotonic()
    while panel.is_visible and time.monotonic() - start < 2:
        time.sleep(0.02)
    elapsed = time.monotonic() - start
    assert not panel.is_visible
    assert elapsed >= 0.15  # waited at least the linger period


def test_linger_resets_if_cursor_returns():
    panel, region, ctrl = make(inside=True)
    hover(ctrl)
    region.inside = False
    time.sleep(0.1)  # less than linger
    region.inside = True  # cursor came back
    time.sleep(0.3)
    assert panel.is_visible


def test_mouse_inside_panel_keeps_it_visible():
    panel, region, ctrl = make(inside=False)
    hover(ctrl)
    panel.mouse_inside = True
    time.sleep(0.5)
    assert panel.is_visible
    panel.mouse_inside = False
    time.sleep(0.5)
    assert not panel.is_visible


def test_fresh_heartbeats_count_as_inside():
    panel, _, ctrl = make(inside=False)
    end = time.monotonic() + 0.4
    while time.monotonic() < end:
        ctrl.on_hover()  # keeps heartbeat fresh
        time.sleep(0.02)
    assert panel.is_visible


def test_watchdog_exits_when_hidden_externally():
    panel, _, ctrl = make(inside=True)
    hover(ctrl)
    panel.is_visible = False  # e.g. hidden by blur
    time.sleep(0.1)
    assert panel.hide_calls == 0  # watchdog returned without double-hiding


def test_inside_check_exception_treated_as_outside():
    panel, _, ctrl = make()
    ctrl._inside_check = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    hover(ctrl)
    time.sleep(0.5)
    assert not panel.is_visible
