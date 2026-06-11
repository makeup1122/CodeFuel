# UsageTray

A Windows system-tray widget that shows your remaining **Claude Code** and
**OpenAI Codex** usage at a glance — 5-hour session limits and weekly limits —
so you don't get cut off mid-task.

It reuses the login credentials your Claude Code / Codex CLIs already store on
disk. No API keys to enter, zero configuration.

## What it shows

- A tray icon with two horizontal bars: top = Claude (orange), bottom = Codex
  (grey). Each bar tracks the provider's most-used limit; it turns red above 90%
  and dims with a hatch pattern when that provider errors.
- Left-click the icon for a dark popup panel: a card per provider with a
  progress bar, percentage, and reset countdown for each limit window.
- Right-click menu: **Refresh now**, **Start at login** (off by default),
  **Quit**.

## Requirements

- Windows 10/11 (64-bit) with the **WebView2 runtime** (preinstalled on current
  Windows 11; otherwise install from Microsoft's Evergreen WebView2 page).
- Logged-in Claude Code (`~/.claude/.credentials.json`) and/or Codex
  (`~/.codex/auth.json`). If a credential is missing or expired, that card shows
  a fix hint; the other provider keeps working.
- Python 3.11+ (only to run from source / build).

## Run from source

```powershell
python -m pip install -r requirements.txt

# Print current usage to the terminal (data-layer smoke test):
python -m usagetray --cli

# Launch the tray app:
python -m usagetray
```

## How it works

```
providers/ --fetch()--> poller (daemon thread) --writes--> state (locked cache)
  claude.py                                          |
  codex.py                              tray (pystray)   panel (pywebview)
```

- **providers/** read local credentials and call each tool's private usage
  endpoint. `fetch()` never raises — on failure it returns a snapshot whose
  `error` carries a human-readable fix hint.
  - Claude: `GET https://api.anthropic.com/api/oauth/usage`
    (`anthropic-beta: oauth-2025-04-20`). On a 401 it attempts one standard
    OAuth refresh using the local `refreshToken`; the refreshed token is kept in
    memory only and **never written back** to your credentials file.
  - Codex: `GET https://chatgpt.com/backend-api/wham/usage`
    (`Authorization: Bearer`, `ChatGPT-Account-Id`).
- **poller** polls every 60s (configurable), with per-provider error backoff
  (60 → 120 → 300s). One provider failing never blocks the other.
- **state** is a thread-safe snapshot cache; the UI only reads from it.

## Configuration

`%APPDATA%\UsageTray\config.json` (created on first run):

```json
{
  "poll_interval_seconds": 60,
  "providers": { "claude": true, "codex": true }
}
```

Logs: `%APPDATA%\UsageTray\usagetray.log` (rotating, 1 MB × 3). Tokens are never
logged. A named mutex prevents a second instance from launching.

## Build a single EXE

```powershell
python -m pip install pyinstaller
python -m PyInstaller --noconfirm UsageTray.spec
# -> dist\UsageTray.exe
```

The `.spec` bundles `panel.html` as data and builds a windowed (no console)
single-file executable. The autostart registry entry points at the EXE when
frozen, or at `pythonw -m usagetray` when run from source.

## Tests

```powershell
python -m pytest -q
```

Covers each provider (real-response parsing via captured fixtures, missing
credentials, 401 + refresh, timeouts, field changes), the poller (failure
isolation, backoff, manual-refresh wake), and config loading.
