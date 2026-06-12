from __future__ import annotations

import json

from usagetray import config as config_mod


def test_defaults_created_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    cfg = config_mod.load_config()
    assert cfg["min_fetch_gap_seconds"] == 60
    assert cfg["providers"]["claude"] is True
    assert cfg["providers"]["codex"] is True
    # file was created
    assert (tmp_path / "UsageTray" / "config.json").exists()


def test_load_merges_partial(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    d = tmp_path / "UsageTray"
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
    d = tmp_path / "UsageTray"
    d.mkdir(parents=True)
    (d / "config.json").write_text("{ not json", encoding="utf-8")
    cfg = config_mod.load_config()
    assert cfg["min_fetch_gap_seconds"] == 60
