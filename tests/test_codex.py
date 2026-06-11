from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path

import requests

from usagetray.providers import codex as codex_mod
from usagetray.providers.codex import CodexProvider


class FakeResponse:
    def __init__(self, status_code=200, json_body=None, raise_json=False):
        self.status_code = status_code
        self._json = json_body
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("no json")
        return self._json


def write_auth(tmp_path: Path, tokens: dict | None, raw: str | None = None) -> Path:
    p = tmp_path / "auth.json"
    if raw is not None:
        p.write_text(raw, encoding="utf-8")
    else:
        p.write_text(json.dumps({"tokens": tokens} if tokens is not None else {}), encoding="utf-8")
    return p


# ---- success path -----------------------------------------------------------


def test_parse_real_fixture(tmp_path, monkeypatch, codex_usage):
    auth = write_auth(tmp_path, {"access_token": "tok", "account_id": "acc"})
    provider = CodexProvider(auth_path=auth)

    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return FakeResponse(200, codex_usage)

    monkeypatch.setattr(codex_mod.requests, "get", fake_get)
    snap = provider.fetch()
    assert snap.ok
    assert captured["url"] == "https://chatgpt.com/backend-api/wham/usage"
    assert captured["headers"]["Authorization"] == "Bearer tok"
    assert captured["headers"]["ChatGPT-Account-Id"] == "acc"

    labels = [m.label for m in snap.metrics]
    assert labels == ["5h 会话", "周限额"]
    primary = snap.metrics[0]
    assert primary.used_percent == 100.0
    assert primary.resets_at is not None and primary.resets_at.tzinfo == timezone.utc
    assert snap.metrics[1].used_percent == 16.0


def test_no_account_id_header(tmp_path, monkeypatch, codex_usage):
    auth = write_auth(tmp_path, {"access_token": "tok"})
    provider = CodexProvider(auth_path=auth)
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["headers"] = headers
        return FakeResponse(200, codex_usage)

    monkeypatch.setattr(codex_mod.requests, "get", fake_get)
    snap = provider.fetch()
    assert snap.ok
    assert "ChatGPT-Account-Id" not in captured["headers"]


# ---- credential errors ------------------------------------------------------


def test_missing_auth(tmp_path):
    provider = CodexProvider(auth_path=tmp_path / "nope.json")
    snap = provider.fetch()
    assert not snap.ok
    assert "未检测到" in snap.error


def test_malformed_auth(tmp_path):
    auth = write_auth(tmp_path, None, raw="{bad")
    provider = CodexProvider(auth_path=auth)
    snap = provider.fetch()
    assert not snap.ok
    assert "无法识别" in snap.error


def test_missing_access_token(tmp_path):
    auth = write_auth(tmp_path, {"account_id": "acc"})
    provider = CodexProvider(auth_path=auth)
    snap = provider.fetch()
    assert not snap.ok
    assert "access_token" in snap.error


# ---- 401 / network / fields -------------------------------------------------


def test_401(tmp_path, monkeypatch):
    auth = write_auth(tmp_path, {"access_token": "tok", "account_id": "acc"})
    provider = CodexProvider(auth_path=auth)
    monkeypatch.setattr(codex_mod.requests, "get", lambda *a, **k: FakeResponse(401, {}))
    snap = provider.fetch()
    assert not snap.ok
    assert "codex" in snap.error.lower()


def test_timeout(tmp_path, monkeypatch):
    auth = write_auth(tmp_path, {"access_token": "tok"})
    provider = CodexProvider(auth_path=auth)

    def boom(*a, **k):
        raise requests.Timeout()

    monkeypatch.setattr(codex_mod.requests, "get", boom)
    snap = provider.fetch()
    assert not snap.ok
    assert "超时" in snap.error


def test_field_change(tmp_path, monkeypatch):
    auth = write_auth(tmp_path, {"access_token": "tok"})
    provider = CodexProvider(auth_path=auth)
    monkeypatch.setattr(
        codex_mod.requests, "get", lambda *a, **k: FakeResponse(200, {"rate_limit": {}})
    )
    snap = provider.fetch()
    assert not snap.ok
    assert "解析" in snap.error


def test_non_json(tmp_path, monkeypatch):
    auth = write_auth(tmp_path, {"access_token": "tok"})
    provider = CodexProvider(auth_path=auth)
    monkeypatch.setattr(
        codex_mod.requests, "get", lambda *a, **k: FakeResponse(200, None, raise_json=True)
    )
    snap = provider.fetch()
    assert not snap.ok
    assert "JSON" in snap.error
