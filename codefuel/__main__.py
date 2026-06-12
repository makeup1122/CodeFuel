"""Entry point: assembles modules and handles the thread model.

Modes:
    python -m codefuel            -> GUI tray app
    python -m codefuel --cli      -> print both providers' current usage and exit
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from .providers import build_providers


def _fmt_reset(dt: datetime | None) -> str:
    if dt is None:
        return "无重置信息"
    delta = dt - datetime.now(timezone.utc)
    secs = int(delta.total_seconds())
    if secs <= 0:
        return "即将重置"
    h, rem = divmod(secs, 3600)
    m, _ = divmod(rem, 60)
    if h > 24:
        d, h = divmod(h, 24)
        return f"{d}d {h}h 后重置"
    return f"{h}h {m}m 后重置"


def run_cli() -> int:
    # Console may be a legacy codepage (e.g. GBK) that can't encode ¥ etc.;
    # force UTF-8 output so amount rows don't crash with UnicodeEncodeError.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    from .config import load_config

    config = load_config()
    providers = build_providers(
        config.get("providers"),
        config.get("deepseek_api_key", ""),
    )
    exit_code = 0
    for provider in providers:
        snap = provider.fetch()
        print(f"=== {snap.display_name} ({snap.provider_id}) ===")
        if snap.error:
            print(f"  [错误] {snap.error}")
            exit_code = 1
            continue
        if not snap.metrics:
            print("  (无数据)")
            continue
        for m in snap.metrics:
            if m.kind == "amount":
                print(f"  {m.label:<14} {m.text or ''}")
                continue
            bar_len = 20
            filled = int(round(m.used_percent / 100 * bar_len))
            bar = "#" * filled + "-" * (bar_len - filled)
            print(f"  {m.label:<14} [{bar}] {m.used_percent:5.1f}%  {_fmt_reset(m.resets_at)}")
        print()
    return exit_code


def run_gui() -> int:
    # Lazy import: GUI deps (pystray/pywebview) only needed in GUI mode.
    from .app import main as gui_main

    return gui_main()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="codefuel", description="AI coding usage tray")
    parser.add_argument("--cli", action="store_true", help="print current usage and exit")
    args = parser.parse_args(argv)

    if args.cli:
        return run_cli()
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
