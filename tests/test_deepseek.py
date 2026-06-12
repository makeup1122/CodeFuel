from __future__ import annotations

import pytest
import requests

from usagetray.providers import deepseek as ds_mod
from usagetray.providers.deepseek import DeepSeekProvider


class FakeResponse:
    def __init__(self, status_code=200, json_body=None, raise_json=False):
        self.status_code = status_code
        self._json = json_body
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("no json")
        return self._json


def test_parse_single_currency(monkeypatch, deepseek_balance):
    provider = DeepSeekProvider(api_key="sk-test")
    monkeypatch.setattr(ds_mod.requests, "get", lambda *a, **k: FakeResponse(200, deepseek_balance))

    snap = provider.fetch()
    assert snap.ok
    assert all(m.kind == "amount" for m in snap.metrics)
    labels = [m.label for m in snap.metrics]
    assert labels == ["总余额 (¥)", "充值余额 (¥)", "赠送余额 (¥)"]
    texts = [m.text for m in snap.metrics]
    assert texts == ["¥110.00", "¥100.00", "¥10.00"]
    # amount 行不参与 worst_metric
    assert snap.worst_metric is None


def test_parse_multi_currency(monkeypatch):
    body = {
        "is_available": True,
        "balance_infos": [
            {"currency": "CNY", "total_balance": "110.00",
             "topped_up_balance": "100.00", "granted_balance": "10.00"},
            {"currency": "USD", "total_balance": "5.00",
             "topped_up_balance": "5.00", "granted_balance": "0.00"},
        ],
    }
    provider = DeepSeekProvider(api_key="sk-test")
    monkeypatch.setattr(ds_mod.requests, "get", lambda *a, **k: FakeResponse(200, body))

    snap = provider.fetch()
    assert snap.ok
    assert len(snap.metrics) == 6
    # 顺序：CNY 三行后接 USD 三行
    assert snap.metrics[0].text == "¥110.00"
    assert snap.metrics[3].text == "$5.00"


def test_no_key_anywhere(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    provider = DeepSeekProvider(api_key=None)
    snap = provider.fetch()
    assert not snap.ok
    assert "未配置" in snap.error


def test_config_key_used(monkeypatch, deepseek_balance):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["auth"] = headers["Authorization"]
        return FakeResponse(200, deepseek_balance)

    monkeypatch.setattr(ds_mod.requests, "get", fake_get)
    provider = DeepSeekProvider(api_key="sk-from-config")
    snap = provider.fetch()
    assert snap.ok
    assert captured["auth"] == "Bearer sk-from-config"


def test_env_fallback(monkeypatch, deepseek_balance):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env")
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["auth"] = headers["Authorization"]
        return FakeResponse(200, deepseek_balance)

    monkeypatch.setattr(ds_mod.requests, "get", fake_get)
    provider = DeepSeekProvider(api_key=None)  # config 空 -> 回退环境变量
    snap = provider.fetch()
    assert snap.ok
    assert captured["auth"] == "Bearer sk-from-env"


@pytest.mark.parametrize(
    "status,needle",
    [(401, "无效"), (429, "限流"), (500, "服务端"), (503, "服务端"), (418, "返回 418")],
)
def test_http_error_codes(monkeypatch, status, needle):
    provider = DeepSeekProvider(api_key="sk-test")
    monkeypatch.setattr(ds_mod.requests, "get", lambda *a, **k: FakeResponse(status, {}))
    snap = provider.fetch()
    assert not snap.ok
    assert needle in snap.error


def test_timeout(monkeypatch):
    provider = DeepSeekProvider(api_key="sk-test")

    def boom(*a, **k):
        raise requests.Timeout()

    monkeypatch.setattr(ds_mod.requests, "get", boom)
    snap = provider.fetch()
    assert not snap.ok
    assert "超时" in snap.error


def test_connection_error(monkeypatch):
    provider = DeepSeekProvider(api_key="sk-test")

    def boom(*a, **k):
        raise requests.ConnectionError()

    monkeypatch.setattr(ds_mod.requests, "get", boom)
    snap = provider.fetch()
    assert not snap.ok
    assert "网络" in snap.error


def test_non_numeric_amount_skipped(monkeypatch):
    body = {
        "is_available": True,
        "balance_infos": [
            {"currency": "CNY", "total_balance": "oops",
             "topped_up_balance": "100.00", "granted_balance": "10.00"},
        ],
    }
    provider = DeepSeekProvider(api_key="sk-test")
    monkeypatch.setattr(ds_mod.requests, "get", lambda *a, **k: FakeResponse(200, body))
    snap = provider.fetch()
    assert snap.ok
    # 坏的 total_balance 被跳过，其余两行保留
    labels = [m.label for m in snap.metrics]
    assert "总余额 (¥)" not in labels
    assert "充值余额 (¥)" in labels


def test_no_balance_infos(monkeypatch):
    provider = DeepSeekProvider(api_key="sk-test")
    monkeypatch.setattr(ds_mod.requests, "get", lambda *a, **k: FakeResponse(200, {"is_available": False}))
    snap = provider.fetch()
    assert not snap.ok
    assert "解析" in snap.error


def test_configured_timeout_is_used(monkeypatch, deepseek_balance):
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["timeout"] = timeout
        return FakeResponse(200, deepseek_balance)

    monkeypatch.setattr(ds_mod.requests, "get", fake_get)
    provider = DeepSeekProvider(api_key="sk-test", timeout=3)
    provider.fetch()
    assert captured["timeout"] == 3


def test_build_providers_passes_timeout():
    from usagetray.providers import build_providers

    providers = {p.id: p for p in build_providers(request_timeout=7)}
    assert providers["claude"]._timeout == 7
    assert providers["codex"]._timeout == 7
    assert providers["deepseek"]._timeout == 7
