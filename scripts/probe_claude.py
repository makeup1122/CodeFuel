"""One-shot probe for the Claude usage API.

Reads %USERPROFILE%\\.claude\\.credentials.json -> claudeAiOauth.accessToken,
calls GET https://api.anthropic.com/api/oauth/usage and dumps the response
to tests/fixtures/claude_usage.json after redacting any obvious secrets.

NEVER prints the full access token.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "claude_usage.json"


def creds_path() -> Path:
    return Path(os.environ["USERPROFILE"]) / ".claude" / ".credentials.json"


def main() -> int:
    path = creds_path()
    if not path.exists():
        print(f"NO credentials file at {path}")
        return 1

    data = json.loads(path.read_text(encoding="utf-8"))
    oauth = data.get("claudeAiOauth", {})
    token = oauth.get("accessToken")
    if not token:
        print("No claudeAiOauth.accessToken found in credentials")
        print("Top-level keys:", list(data.keys()))
        return 1

    print(f"Token loaded (len={len(token)}, prefix={token[:6]}...)")
    print(f"expiresAt: {oauth.get('expiresAt')}")

    headers = {
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "oauth-2025-04-20",
        "Accept": "application/json",
    }
    resp = requests.get(USAGE_URL, headers=headers, timeout=15)
    print(f"HTTP {resp.status_code}")
    print("Response headers content-type:", resp.headers.get("content-type"))

    try:
        body = resp.json()
    except ValueError:
        print("Non-JSON body (first 500 chars):")
        print(resp.text[:500])
        return 1

    print("---- response JSON (keys) ----")
    print(json.dumps(body, indent=2, ensure_ascii=False)[:4000])

    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved fixture -> {FIXTURE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
