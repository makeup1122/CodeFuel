"""One-shot probe for the Codex (ChatGPT backend) usage API.

Reads %USERPROFILE%\\.codex\\auth.json -> tokens.access_token / tokens.account_id,
calls GET https://chatgpt.com/backend-api/wham/usage (endpoint + headers per
steipete/codexbar CodexOAuthUsageFetcher.swift) and dumps the response to
tests/fixtures/codex_usage.json.

NEVER prints the full access token or account id.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "codex_usage.json"


def auth_path() -> Path:
    return Path(os.environ["USERPROFILE"]) / ".codex" / "auth.json"


def main() -> int:
    path = auth_path()
    if not path.exists():
        print(f"NO auth file at {path}")
        return 1

    data = json.loads(path.read_text(encoding="utf-8"))
    tokens = data.get("tokens", {})
    token = tokens.get("access_token")
    account_id = tokens.get("account_id")
    if not token:
        print("No tokens.access_token found in auth.json")
        print("Top-level keys:", list(data.keys()))
        print("tokens keys:", list(tokens.keys()))
        return 1

    print(f"Token loaded (len={len(token)}, prefix={token[:6]}...)")
    print(f"account_id present: {bool(account_id)} (len={len(account_id) if account_id else 0})")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "UsageTray",
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id

    resp = requests.get(USAGE_URL, headers=headers, timeout=20)
    print(f"HTTP {resp.status_code}")
    print("Response headers content-type:", resp.headers.get("content-type"))

    try:
        body = resp.json()
    except ValueError:
        print("Non-JSON body (first 800 chars):")
        print(resp.text[:800])
        return 1

    print("---- response JSON ----")
    print(json.dumps(body, indent=2, ensure_ascii=False)[:4000])

    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved fixture -> {FIXTURE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
