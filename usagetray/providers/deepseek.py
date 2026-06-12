"""DeepSeek account-balance provider.

Credential: config.json ``deepseek_api_key``, else env ``DEEPSEEK_API_KEY``.
Endpoint:   GET https://api.deepseek.com/user/balance
Headers:    Authorization: Bearer <key>, Accept: application/json

Response shape (DeepSeek official):
    {"is_available": true,
     "balance_infos": [
        {"currency": "CNY", "total_balance": "110.00",
         "granted_balance": "10.00", "topped_up_balance": "100.00"}]}

``balance_infos`` is a list that may carry multiple currencies (CNY, USD).
Static API key - no OAuth refresh. ``fetch()`` never raises.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import requests

from ..models import Metric, UsageSnapshot

BALANCE_URL = "https://api.deepseek.com/user/balance"
TIMEOUT = 10

CURRENCY_SYMBOLS = {"CNY": "¥", "USD": "$"}

# (response field, label template). {sym} is the currency symbol.
BALANCE_FIELDS: list[tuple[str, str]] = [
    ("total_balance", "总余额 ({sym})"),
    ("topped_up_balance", "充值余额 ({sym})"),
    ("granted_balance", "赠送余额 ({sym})"),
]


class DeepSeekProvider:
    id = "deepseek"
    display_name = "DeepSeek"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    # ---- credential handling -------------------------------------------------

    def _read_key(self) -> str | None:
        if self._api_key:
            return self._api_key
        env = os.environ.get("DEEPSEEK_API_KEY")
        return env or None

    def _err(self, message: str) -> UsageSnapshot:
        return UsageSnapshot(
            provider_id=self.id,
            display_name=self.display_name,
            metrics=[],
            fetched_at=datetime.now(timezone.utc),
            error=message,
        )

    # ---- HTTP ----------------------------------------------------------------

    def _request_balance(self, key: str) -> requests.Response:
        headers = {
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        }
        return requests.get(BALANCE_URL, headers=headers, timeout=TIMEOUT)

    # ---- parsing -------------------------------------------------------------

    def _parse(self, body: dict) -> list[Metric]:
        metrics: list[Metric] = []
        infos = body.get("balance_infos")
        if not isinstance(infos, list):
            return metrics
        for info in infos:
            if not isinstance(info, dict):
                continue
            currency = info.get("currency")
            sym = CURRENCY_SYMBOLS.get(currency, str(currency or "?"))
            for field_key, label_tmpl in BALANCE_FIELDS:
                raw = info.get(field_key)
                try:
                    amount = float(raw)
                except (TypeError, ValueError):
                    continue
                metrics.append(
                    Metric(
                        label=label_tmpl.format(sym=sym),
                        used_percent=0.0,
                        kind="amount",
                        text=f"{sym}{amount:.2f}",
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
        key = self._read_key()
        if not key:
            return self._err(
                "未配置 DeepSeek API key（config.json 的 deepseek_api_key 或环境变量 DEEPSEEK_API_KEY）。"
            )

        try:
            resp = self._request_balance(key)
        except requests.Timeout:
            return self._err("请求超时（10s），稍后重试。")
        except requests.ConnectionError:
            return self._err("网络连接失败，稍后重试。")
        except requests.RequestException as exc:
            return self._err(f"请求失败: {exc}")

        if resp.status_code == 401:
            return self._err("DeepSeek API key 无效，请检查 config.json 或 DEEPSEEK_API_KEY。")
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
            return self._err("未能从响应中解析出余额（接口字段可能已变化）。")

        return UsageSnapshot(
            provider_id=self.id,
            display_name=self.display_name,
            metrics=metrics,
            fetched_at=datetime.now(timezone.utc),
            error=None,
        )
