"""Claude Code usage provider.

Credential: %USERPROFILE%\\.claude\\.credentials.json -> claudeAiOauth.accessToken
Endpoint:   GET https://api.anthropic.com/api/oauth/usage
Headers:    Authorization: Bearer <token>, anthropic-beta: oauth-2025-04-20

Response shape (real, captured 2026-03):
    {"five_hour": {"utilization": 48.0, "resets_at": "...ISO..."},
     "seven_day": {...}, "seven_day_opus": null, "seven_day_sonnet": {...},
     "extra_usage": {...}, ...}
Each window is either null or {"utilization": float 0-100, "resets_at": ISO}.

On 401 with a usable refreshToken we attempt one standard OAuth refresh and
retry. The refreshed token is kept only in memory; we never write back to the
user's .credentials.json.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from ..models import Metric, UsageSnapshot, parse_retry_after

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
BETA_HEADER = "oauth-2025-04-20"
TIMEOUT = 10

# Window key -> display label. Order defines display order. Keys not listed
# are ignored (e.g. seven_day_oauth_apps, extra_usage, iguana_necktie).
WINDOW_LABELS: list[tuple[str, str]] = [
    ("five_hour", "5h 会话"),
    ("seven_day", "周限额"),
    ("seven_day_opus", "周限额 (Opus)"),
    ("seven_day_sonnet", "周限额 (Sonnet)"),
]


def _creds_path() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    root = Path(base) if base else Path(os.path.expanduser("~")) / ".claude"
    return root / ".credentials.json"


def _parse_iso(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class ClaudeProvider:
    id = "claude"
    display_name = "Claude Code"

    def __init__(self, creds_path: Path | None = None, timeout: int = TIMEOUT) -> None:
        self._creds_path = creds_path or _creds_path()
        self._timeout = timeout
        # In-memory token override after a successful refresh (never persisted).
        self._access_override: str | None = None
        self._refresh_override: str | None = None

    # ---- credential handling -------------------------------------------------

    def _read_creds(self) -> dict | None:
        if not self._creds_path.exists():
            return None
        try:
            data = json.loads(self._creds_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}  # present-but-unreadable marker
        oauth = data.get("claudeAiOauth")
        if not isinstance(oauth, dict):
            return {}
        return oauth

    def _err(self, message: str, retry_after: float | None = None) -> UsageSnapshot:
        return UsageSnapshot(
            provider_id=self.id,
            display_name=self.display_name,
            metrics=[],
            fetched_at=datetime.now(timezone.utc),
            error=message,
            retry_after_seconds=retry_after,
        )

    # ---- HTTP ----------------------------------------------------------------

    def _request_usage(self, token: str) -> requests.Response:
        headers = {
            "Authorization": f"Bearer {token}",
            "anthropic-beta": BETA_HEADER,
            "Accept": "application/json",
        }
        return requests.get(USAGE_URL, headers=headers, timeout=self._timeout)

    def _try_refresh(self, refresh_token: str) -> str | None:
        """Attempt a standard OAuth refresh. Returns new access token or None.

        The new tokens are cached in memory only; we do not write to the
        user's credential file.
        """
        try:
            resp = requests.post(
                TOKEN_URL,
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": OAUTH_CLIENT_ID,
                },
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=self._timeout,
            )
        except requests.RequestException:
            return None
        if resp.status_code != 200:
            return None
        try:
            body = resp.json()
        except ValueError:
            return None
        new_access = body.get("access_token")
        if isinstance(body.get("refresh_token"), str):
            self._refresh_override = body["refresh_token"]
        if isinstance(new_access, str) and new_access:
            self._access_override = new_access
            return new_access
        return None

    # ---- parsing -------------------------------------------------------------

    def _parse(self, body: dict) -> list[Metric]:
        metrics: list[Metric] = []
        for key, label in WINDOW_LABELS:
            window = body.get(key)
            if not isinstance(window, dict):
                continue
            util = window.get("utilization")
            if util is None:
                continue
            try:
                used = float(util)
            except (TypeError, ValueError):
                continue
            metrics.append(
                Metric(
                    label=label,
                    used_percent=max(0.0, min(100.0, used)),
                    resets_at=_parse_iso(window.get("resets_at")),
                )
            )
        return metrics

    # ---- public API ----------------------------------------------------------

    def fetch(self) -> UsageSnapshot:
        try:
            return self._fetch()
        except Exception as exc:  # never raise out of fetch()
            return self._err(f"未知错误: {exc}")

    def _fetch(self) -> UsageSnapshot:
        oauth = self._read_creds()
        if oauth is None:
            return self._err("未检测到 Claude Code 登录，请先在终端运行一次 claude 登录。")
        if not oauth:
            return self._err("凭证格式无法识别，请检查 .claude/.credentials.json。")

        token = self._access_override or oauth.get("accessToken")
        refresh_token = self._refresh_override or oauth.get("refreshToken")
        if not token:
            return self._err("凭证中缺少 accessToken，请在终端重新运行 claude 登录。")

        try:
            resp = self._request_usage(token)
        except requests.Timeout:
            return self._err(f"请求超时（{self._timeout}s），稍后重试。")
        except requests.ConnectionError:
            return self._err("网络连接失败，稍后重试。")
        except requests.RequestException as exc:
            return self._err(f"请求失败: {exc}")

        # 401 -> try one refresh, then retry once.
        if resp.status_code == 401 and refresh_token:
            new_token = self._try_refresh(refresh_token)
            if new_token:
                try:
                    resp = self._request_usage(new_token)
                except requests.RequestException as exc:
                    return self._err(f"刷新后请求失败: {exc}")

        if resp.status_code == 401:
            return self._err("登录已过期，请在终端运行一次 claude 以刷新登录。")
        if resp.status_code == 429:
            return self._err(
                "接口限流（429），稍后重试。",
                retry_after=parse_retry_after(resp.headers.get("Retry-After")),
            )
        if resp.status_code >= 500:
            return self._err(f"服务端错误（{resp.status_code}），稍后重试。")
        if resp.status_code != 200:
            return self._err(f"接口返回 {resp.status_code}。")

        try:
            body = resp.json()
        except ValueError:
            return self._err("接口返回非 JSON，无法解析。")
        if not isinstance(body, dict):
            return self._err("接口响应结构异常。")

        metrics = self._parse(body)
        if not metrics:
            return self._err("未能从响应中解析出任何限额项（接口字段可能已变化）。")

        return UsageSnapshot(
            provider_id=self.id,
            display_name=self.display_name,
            metrics=metrics,
            fetched_at=datetime.now(timezone.utc),
            error=None,
        )
