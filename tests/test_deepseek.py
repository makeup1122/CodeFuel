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
