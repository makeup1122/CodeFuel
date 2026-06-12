"""Config read/write + Windows autostart registry toggle.

Config lives at %APPDATA%\\UsageTray\\config.json. Missing file -> defaults are
used and the file is created.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "UsageTray"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

DEFAULTS = {
    "min_fetch_gap_seconds": 60,
    "providers": {"claude": True, "codex": True, "deepseek": True},
    "deepseek_api_key": "",
    "log_level": "INFO",            # DEBUG | INFO | WARNING | ERROR (env USAGETRAY_DEBUG forces DEBUG)
    "panel_linger_seconds": 2.0,    # how long the panel lingers after the cursor leaves
    "request_timeout_seconds": 10,  # HTTP timeout for each provider's usage call
    "panel_width": 400,             # panel window width in CSS px (height auto-fits)
}


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return config_dir() / "config.json"


def load_config() -> dict:
    path = config_path()
    if not path.exists():
        save_config(DEFAULTS)
        return dict(DEFAULTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULTS)
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in data.items() if k in DEFAULTS})
    # merge provider toggles
    providers = dict(DEFAULTS["providers"])
    if isinstance(data.get("providers"), dict):
        providers.update(data["providers"])
    cfg["providers"] = providers
    return cfg


def save_config(cfg: dict) -> None:
    config_path().write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# ---- autostart (Windows registry) -------------------------------------------


def _exe_command() -> str:
    """Command to register for autostart.

    Frozen (PyInstaller) -> the exe path. Source -> pythonw -m usagetray.
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pyw = Path(sys.executable).with_name("pythonw.exe")
    runner = str(pyw) if pyw.exists() else sys.executable
    return f'"{runner}" -m usagetray'


def is_autostart_enabled() -> bool:
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> None:
    try:
        import winreg
    except ImportError:
        return
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _exe_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except OSError:
                pass
