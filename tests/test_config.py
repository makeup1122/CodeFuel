from __future__ import annotations

import json

from codefuel import config as config_mod


def test_defaults_created_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    cfg = config_mod.load_config()
    assert cfg["min_fetch_gap_seconds"] == 60
    assert cfg["providers"]["claude"] is True
    assert cfg["providers"]["codex"] is True
    assert cfg["providers"]["deepseek"] is True
    assert cfg["deepseek_api_key"] == ""
    assert cfg["log_level"] == "INFO"
    assert cfg["panel_linger_seconds"] == 2.0
    assert cfg["request_timeout_seconds"] == 10
    assert cfg["panel_width"] == 400
    # file was created
    assert (tmp_path / "CodeFuel" / "config.json").exists()


def test_load_merges_partial(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    d = tmp_path / "CodeFuel"
    d.mkdir(parents=True)
    (d / "config.json").write_text(
        json.dumps({"min_fetch_gap_seconds": 30, "providers": {"codex": False}}),
        encoding="utf-8",
    )
    cfg = config_mod.load_config()
    assert cfg["min_fetch_gap_seconds"] == 30
    assert cfg["providers"]["codex"] is False
    assert cfg["providers"]["claude"] is True  # default preserved


def test_malformed_config_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    d = tmp_path / "CodeFuel"
    d.mkdir(parents=True)
    (d / "config.json").write_text("{ not json", encoding="utf-8")
    cfg = config_mod.load_config()
    assert cfg["min_fetch_gap_seconds"] == 60
