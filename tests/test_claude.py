from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from codefuel.providers import claude as claude_mod
from codefuel.providers.claude import ClaudeProvider


class FakeResponse:
    def __init__(self, status_code=200, json_body=None, raise_json=False):
        self.status_code = status_code
        self._json = json_body
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("no json")
        return self._json


def write_creds(tmp_path: Path, oauth: dict | None, raw: str | None = None) -> Path:
    p = tmp_path / ".credentials.json"
    if raw is not None:
        p.write_text(raw, encoding="utf-8")
    else:
        p.write_text(json.dumps({"claudeAiOauth": oauth} if oauth is not None else {}), encoding="utf-8")
    return p


# ---- success path -----------------------------------------------------------


def test_parse_real_fixture(tmp_path, monkeypatch, claude_usage):
    creds = write_creds(tmp_path, {"accessToken": "tok", "refreshToken": "ref"})
    provider = ClaudeProvider(creds_path=creds)
    monkeypatch.setattr(claude_mod.requests, "get", lambda *a, **k: FakeResponse(200, claude_usage))

    snap = provider.fetch()
    assert snap.ok
    labels = [m.label for m in snap.metrics]
    # five_hour, seven_day, seven_day_sonnet present; opus is null -> skipped
    assert "5h 会话" in labels
    assert "周限额" in labels
    assert "周限额 (Sonnet)" in labels
    assert "周限额 (Opus)" not in labels
    five = next(m for m in snap.metrics if m.label == "5h 会话")
    assert five.used_percent == 48.0
    assert five.resets_at is not None and five.resets_at.tzinfo is not None


def test_worst_metric(tmp_path, monkeypatch, claude_usage):
    creds = write_creds(tmp_path, {"accessToken": "tok"})
    provider = ClaudeProvider(creds_path=creds)
    monkeypatch.setattr(claude_mod.requests, "get", lambda *a, **k: FakeResponse(200, claude_usage))
    snap = provider.fetch()
    assert snap.worst_metric.label == "周限额"  # 64% is highest


# ---- credential errors ------------------------------------------------------


def test_missing_credentials(tmp_path):
    provider = ClaudeProvider(creds_path=tmp_path / "nope.json")
    snap = provider.fetch()
    assert not snap.ok
    assert "未检测到" in snap.error


def test_malformed_credentials(tmp_path):
    creds = write_creds(tmp_path, None, raw="{ not json")
    provider = ClaudeProvider(creds_path=creds)
    snap = provider.fetch()
    assert not snap.ok
    assert "无法识别" in snap.error


def test_missing_access_token(tmp_path):
    creds = write_creds(tmp_path, {"refreshToken": "ref"})
    provider = ClaudeProvider(creds_path=creds)
    snap = provider.fetch()
    assert not snap.ok
    assert "accessToken" in snap.error


# ---- 401 + refresh ----------------------------------------------------------


def test_401_no_refresh_token(tmp_path, monkeypatch):
    creds = write_creds(tmp_path, {"accessToken": "tok"})
    provider = ClaudeProvider(creds_path=creds)
    monkeypatch.setattr(claude_mod.requests, "get", lambda *a, **k: FakeResponse(401, {}))
    snap = provider.fetch()
    assert not snap.ok
    assert "过期" in snap.error


def test_401_refresh_succeeds(tmp_path, monkeypatch, claude_usage):
    creds = write_creds(tmp_path, {"accessToken": "old", "refreshToken": "ref"})
    provider = ClaudeProvider(creds_path=creds)

    calls = {"get": 0}

    def fake_get(url, headers=None, timeout=None):
        calls["get"] += 1
        if calls["get"] == 1:
            return FakeResponse(401, {})
        # second call uses refreshed token
        assert headers["Authorization"] == "Bearer new-token"
        return FakeResponse(200, claude_usage)

    def fake_post(url, json=None, headers=None, timeout=None):
        assert json["grant_type"] == "refresh_token"
        return FakeResponse(200, {"access_token": "new-token", "refresh_token": "new-ref"})

    monkeypatch.setattr(claude_mod.requests, "get", fake_get)
    monkeypatch.setattr(claude_mod.requests, "post", fake_post)

    snap = provider.fetch()
    assert snap.ok
    assert calls["get"] == 2
    # refreshed token cached in memory, not written to file
    assert provider._access_override == "new-token"
    on_disk = json.loads(creds.read_text(encoding="utf-8"))
    assert on_disk["claudeAiOauth"]["accessToken"] == "old"


def test_401_refresh_fails(tmp_path, monkeypatch):
    creds = write_creds(tmp_path, {"accessToken": "old", "refreshToken": "ref"})
    provider = ClaudeProvider(creds_path=creds)
    monkeypatch.setattr(claude_mod.requests, "get", lambda *a, **k: FakeResponse(401, {}))
    monkeypatch.setattr(claude_mod.requests, "post", lambda *a, **k: FakeResponse(400, {}))
    snap = provider.fetch()
    assert not snap.ok
    assert "claude" in snap.error.lower() or "过期" in snap.error


# ---- network / field errors -------------------------------------------------


def test_timeout(tmp_path, monkeypatch):
    creds = write_creds(tmp_path, {"accessToken": "tok"})
    provider = ClaudeProvider(creds_path=creds)

    def boom(*a, **k):
        raise requests.Timeout()

    monkeypatch.setattr(claude_mod.requests, "get", boom)
    snap = provider.fetch()
    assert not snap.ok
    assert "超时" in snap.error


def test_connection_error(tmp_path, monkeypatch):
    creds = write_creds(tmp_path, {"accessToken": "tok"})
    provider = ClaudeProvider(creds_path=creds)

    def boom(*a, **k):
        raise requests.ConnectionError()

    monkeypatch.setattr(claude_mod.requests, "get", boom)
    snap = provider.fetch()
    assert not snap.ok
    assert "网络" in snap.error


def test_empty_fields(tmp_path, monkeypatch):
    creds = write_creds(tmp_path, {"accessToken": "tok"})
    provider = ClaudeProvider(creds_path=creds)
    monkeypatch.setattr(
        claude_mod.requests, "get", lambda *a, **k: FakeResponse(200, {"unknown": {}})
    )
    snap = provider.fetch()
    assert not snap.ok
    assert "解析" in snap.error
