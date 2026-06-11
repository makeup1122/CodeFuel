"""Codex (ChatGPT backend) usage provider.

Credential: %USERPROFILE%\\.codex\\auth.json -> tokens.access_token / tokens.account_id
Endpoint:   GET https://chatgpt.com/backend-api/wham/usage
Headers:    Authorization: Bearer <token>, ChatGPT-Account-Id: <account_id>,
            Accept: application/json, User-Agent: UsageTray

Response shape (real, captured 2026-06):
    {"plan_type": "prolite",
     "rate_limit": {
        "primary_window":   {"used_percent": 100, "reset_at": <epoch>, "limit_window_seconds": 18000, "reset_after_seconds": 7370},
        "secondary_window": {"used_percent": 16,  "reset_at": <epoch>, ...}},
     "additional_rate_limits": [ {"limit_name": "...", "rate_limit": {...}} ],
     "credits": {...}, ...}
``used_percent`` is an int 0-100; ``reset_at`` is epoch seconds.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from ..models import Metric, UsageSnapshot

USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
TIMEOUT = 10


def _auth_path() -> Path:
    base = os.environ.get("CODEX_HOME")
    root = Path(base) if base else Path(os.path.expanduser("~")) / ".codex"
    return root / "auth.json"


def _epoch_to_dt(value) -> datetime | None:
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _window_metric(window, label: str) -> Metric | None:
    if not isinstance(window, dict):
        return None
    used = window.get("used_percent")
    if used is None:
        return None
    try:
        used_f = float(used)
    except (TypeError, ValueError):
        return None
    return Metric(
        label=label,
        used_percent=max(0.0, min(100.0, used_f)),
        resets_at=_epoch_to_dt(window.get("reset_at")),
    )


class CodexProvider:
    id = "codex"
    display_name = "OpenAI Codex"

    def __init__(self, auth_path: Path | None = None) -> None:
        self._auth_path = auth_path or _auth_path()

    def _read_auth(self) -> dict | None:
        if not self._auth_path.exists():
            return None
        try:
            data = json.loads(self._auth_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        tokens = data.get("tokens")
        if not isinstance(tokens, dict):
            return {}
        return tokens

    def _err(self, message: str) -> UsageSnapshot:
        return UsageSnapshot(
            provider_id=self.id,
            display_name=self.display_name,
            metrics=[],
            fetched_at=datetime.now(timezone.utc),
            error=message,
        )

    def _parse(self, body: dict) -> list[Metric]:
        rate = body.get("rate_limit")
        if not isinstance(rate, dict):
            return []
        metrics: list[Metric] = []
        primary = _window_metric(rate.get("primary_window"), "5h 会话")
        if primary:
            metrics.append(primary)
        secondary = _window_metric(rate.get("secondary_window"), "周限额")
        if secondary:
            metrics.append(secondary)
        return metrics

    def fetch(self) -> UsageSnapshot:
        try:
            return self._fetch()
        except Exception as exc:
            return self._err(f"未知错误: {exc}")

    def _fetch(self) -> UsageSnapshot:
        tokens = self._read_auth()
        if tokens is None:
            return self._err("未检测到 Codex 登录，请先在终端运行 codex 并完成登录。")
        if not tokens:
            return self._err("凭证格式无法识别，请检查 .codex/auth.json。")

        token = tokens.get("access_token")
        account_id = tokens.get("account_id")
        if not token:
            return self._err("凭证中缺少 access_token，请在终端重新运行 codex 登录。")

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "UsageTray",
        }
        if account_id:
            headers["ChatGPT-Account-Id"] = account_id

        try:
            resp = requests.get(USAGE_URL, headers=headers, timeout=TIMEOUT)
        except requests.Timeout:
            return self._err("请求超时（10s），稍后重试。")
        except requests.ConnectionError:
            return self._err("网络连接失败，稍后重试。")
        except requests.RequestException as exc:
            return self._err(f"请求失败: {exc}")

        if resp.status_code in (401, 403):
            return self._err("登录已过期，请在终端运行 codex 并完成登录刷新。")
        if resp.status_code == 429:
            return self._err("接口限流（429），稍后重试。")
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
