from __future__ import annotations

import time
from datetime import datetime, timezone

from codefuel.models import Metric, UsageSnapshot
from codefuel.poller import Poller
from codefuel.state import AppState


class FakeProvider:
    def __init__(self, pid, ok=True, retry_after=None):
        self.id = pid
        self.display_name = pid
        self.ok = ok
        self.retry_after = retry_after
        self.calls = 0

    def fetch(self):
        self.calls += 1
        if self.ok:
            return UsageSnapshot(self.id, self.display_name, [Metric("m", 10.0)],
                                 datetime.now(timezone.utc), None)
        return UsageSnapshot(self.id, self.display_name, [], datetime.now(timezone.utc),
                             "boom", retry_after_seconds=self.retry_after)


def _wait_for(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while not predicate() and time.time() < deadline:
        time.sleep(0.02)
    return predicate()


def test_failure_isolation():
    good = FakeProvider("good", ok=True)
    bad = FakeProvider("bad", ok=False)
    state = AppState()
    poller = Poller([good, bad], state)

    poller.poll_provider(good)
    poller.poll_provider(bad)

    assert state.get("good").ok
    assert not state.get("bad").ok


def test_state_callback_invoked():
    p = FakeProvider("p")
    state = AppState()
    seen = []
    state.subscribe(lambda snaps: seen.append(set(snaps.keys())))
    poller = Poller([p], state)
    poller.poll_provider(p)
    assert seen and "p" in seen[-1]


def test_no_fetch_without_request():
    p = FakeProvider("p")
    poller = Poller([p], AppState(), min_gap=0)
    poller.start()
    try:
        time.sleep(0.3)
        assert p.calls == 0  # nothing happens until refresh_now()
        poller.refresh_now()
        assert _wait_for(lambda: p.calls == 1)
    finally:
        poller.stop()


def test_refresh_is_throttled_by_min_gap():
    p = FakeProvider("p")
    poller = Poller([p], AppState(), min_gap=3600)
    poller.start()
    try:
        poller.refresh_now()
        assert _wait_for(lambda: p.calls == 1)
        # within the gap: throttled, no second fetch
        poller.refresh_now()
        time.sleep(0.3)
        assert p.calls == 1
        # force bypasses the throttle
        poller.refresh_now(force=True)
        assert _wait_for(lambda: p.calls == 2)
    finally:
        poller.stop()


def test_failed_provider_not_auto_retried():
    p = FakeProvider("p", ok=False)
    poller = Poller([p], AppState(), min_gap=0)
    poller.start()
    try:
        poller.refresh_now()
        assert _wait_for(lambda: p.calls == 1)
        time.sleep(0.3)
        assert p.calls == 1  # no automatic retry after failure
        poller.refresh_now()
        assert _wait_for(lambda: p.calls == 2)  # retried on next request
    finally:
        poller.stop()


def test_provider_exception_does_not_crash_loop():
    class Exploding:
        id = "x"
        display_name = "x"

        def fetch(self):
            raise RuntimeError("kaboom")

    ok = FakeProvider("p")
    poller = Poller([Exploding(), ok], AppState(), min_gap=0)
    poller.start()
    try:
        poller.refresh_now()
        # the exploding provider is caught by the loop; the healthy one still runs
        assert _wait_for(lambda: ok.calls == 1)
    finally:
        poller.stop()


def test_429_sets_cooldown_and_blocks_forced_refresh():
    p = FakeProvider("p", ok=False, retry_after=300)
    poller = Poller([p], AppState(), min_gap=0)
    poller.poll_provider(p)  # 429 -> 300s cooldown
    assert poller._cooldown_until["p"] > time.monotonic() + 100
    poller.refresh_now(force=True)  # forced, but cooldown wins
    assert "p" not in poller._pending


def test_cooldown_expired_allows_fetch():
    p = FakeProvider("p", ok=False, retry_after=0.05)
    poller = Poller([p], AppState(), min_gap=0)
    poller.poll_provider(p)
    time.sleep(0.08)
    poller.refresh_now(force=True)
    assert "p" in poller._pending  # cooldown elapsed -> queued again


def test_plain_failure_does_not_set_cooldown():
    p = FakeProvider("p", ok=False)  # error but no retry_after
    poller = Poller([p], AppState(), min_gap=0)
    poller.poll_provider(p)
    poller.refresh_now(force=True)
    assert "p" in poller._pending  # non-429 failures don't block
