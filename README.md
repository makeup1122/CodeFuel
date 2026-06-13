# CodeFuel

<p align="center"><img src="assets/icon.png" width="112" alt="CodeFuel icon"></p>

**English** | [简体中文](README.zh-CN.md)

A lightweight Windows system-tray widget that keeps your AI coding "fuel gauge"
in view — the remaining **Claude Code** and **OpenAI Codex** usage limits plus
your **DeepSeek** account balance — so you don't run dry mid-task.

For Claude and Codex it reuses the login credentials their CLIs already store on
disk: no API keys to enter. DeepSeek uses a balance API key you supply.

> The interface is in Chinese (简体中文).

<p align="center"><img src="assets/screenshot.png" width="320" alt="CodeFuel hover panel"></p>

## What it shows

- **Tray icon** — two stacked bars: top = Claude (orange), bottom = Codex
  (grey). Each bar tracks that provider's most-used limit, turns red above 90%,
  and dims with a hatch pattern when the provider errors.
- **Hover panel** — a dark popup with one card per provider:
  - Claude / Codex: a progress bar, percentage, and reset countdown for each
    limit window (5-hour session, weekly, etc.).
  - DeepSeek: account balance as plain text — total, topped-up, and granted —
    per currency. No progress bar (a balance has no natural ceiling) and no tray
    glyph.

  The panel appears on hover and hides itself once the cursor leaves both the
  icon and the panel. Left-click also opens it as a fallback.
- **Right-click menu** — Refresh now · Start at login (off by default) · Quit.

Data is fetched on demand only — at startup, when you open the panel (throttled),
and on manual refresh — so it never hammers the rate-limited usage endpoints.

## Requirements

- Windows 10/11 (64-bit) with the **WebView2 runtime** (preinstalled on current
  Windows 11; otherwise install Microsoft's Evergreen WebView2 runtime).
- For the Claude / Codex cards: a logged-in Claude Code
  (`~/.claude/.credentials.json`) and/or Codex (`~/.codex/auth.json`). If a
  credential is missing or expired, that card shows a fix hint; the others keep
  working.
- For the DeepSeek card: a DeepSeek API key (see [Configuration](#configuration)).
- Python 3.11+ — only needed to run from source or build the EXE.

## Install

Grab `CodeFuel.exe` from the [Releases](../../releases) page and run it — it's a
single self-contained executable, no installer.

Or run from source:

```powershell
python -m pip install -r requirements.txt

# Print current usage to the terminal (data-layer smoke test):
python -m codefuel --cli

# Launch the tray app:
python -m codefuel
```

## Configuration

A config file is created on first run at `%APPDATA%\CodeFuel\config.json`:

```json
{
  "min_fetch_gap_seconds": 60,
  "providers": { "claude": true, "codex": true, "deepseek": true },
  "deepseek_api_key": "",
  "log_level": "INFO",
  "panel_linger_seconds": 2.0,
  "request_timeout_seconds": 10,
  "panel_width": 400
}
```

- `min_fetch_gap_seconds` — when you open the panel, a provider is re-fetched at
  most once per this many seconds (manual refresh bypasses it).
- `providers` — toggle individual cards on/off.
- `deepseek_api_key` — your DeepSeek balance key. Leave empty to fall back to the
  `DEEPSEEK_API_KEY` environment variable. With no key, the DeepSeek card shows a
  hint and the other providers are unaffected.
- `log_level` — `DEBUG` / `INFO` / `WARNING` / `ERROR`. The `CODEFUEL_DEBUG`
  environment variable still forces `DEBUG` regardless of this value.
- `panel_linger_seconds` — how long the panel stays up after the cursor leaves
  both the icon and the panel.
- `request_timeout_seconds` — HTTP timeout for each provider's usage call.
- `panel_width` — panel window width in CSS px (height auto-fits to content).

Changes take effect on the next launch (config is read once at startup).

Logs live next to the config at `%APPDATA%\CodeFuel\codefuel.log` (rotating,
1 MB × 3). Credentials and tokens are never logged. A named mutex prevents a
second instance from launching.

## How it works

```
providers/ --fetch()--> poller (daemon thread) --writes--> state (locked cache)
  claude.py                                          |
  codex.py                              tray (pystray)   panel (pywebview)
  deepseek.py
```

- **providers/** read local credentials (or an API key) and call each tool's
  usage endpoint. `fetch()` never raises — on failure it returns a snapshot
  whose `error` carries a human-readable fix hint.
  - **Claude** — `GET https://api.anthropic.com/api/oauth/usage`
    (`anthropic-beta: oauth-2025-04-20`). On a 401 it attempts one standard
    OAuth refresh using the local `refreshToken`; the refreshed token is kept in
    memory only and **never written back** to your credentials file.
  - **Codex** — `GET https://chatgpt.com/backend-api/wham/usage`
    (`Authorization: Bearer`, `ChatGPT-Account-Id`).
  - **DeepSeek** — `GET https://api.deepseek.com/user/balance`
    (`Authorization: Bearer`).
- **poller** fetches on demand only (no periodic polling): once at startup, when
  the panel is shown (throttled per `min_fetch_gap_seconds`), and on manual
  refresh. One provider failing never blocks the others.
- **state** is a thread-safe snapshot cache; the UI only reads from it.

## Build a single EXE

```powershell
python -m pip install pyinstaller
python -m PyInstaller --noconfirm CodeFuel.spec
# -> dist\CodeFuel.exe
```

The `.spec` bundles `panel.html` as data and produces a windowed (no console)
single-file executable. The "Start at login" entry points at the EXE when frozen,
or at `pythonw -m codefuel` when run from source.

## Tests

```powershell
python -m pytest -q
```

Covers each provider (real-response parsing via captured fixtures, missing
credentials, 401 + refresh, rate limits, timeouts, field changes), the data
model, the poller (on-demand fetch, throttling, failure isolation), and config
loading.

## License

[MIT](LICENSE) © 2026 makeup1122
