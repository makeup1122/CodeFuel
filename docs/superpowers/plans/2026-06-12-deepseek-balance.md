# DeepSeek 余额显示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 UsageTray 新增 DeepSeek provider，在面板里以纯文本金额展示账户余额（总额 / 充值 / 赠送），不上托盘图标。

**Architecture:** 复用现有 provider 协议与数据流。给 `Metric` 加可选 `kind`/`text` 字段以承载金额（区别于百分比进度条）；新增 `providers/deepseek.py`，key 从 config 注入、缺省回退环境变量；前端 `metricRow()` 按 `kind` 分支渲染。

**Tech Stack:** Python 3.11、requests、pytest、pywebview（前端 vanilla JS）。

设计依据：`docs/superpowers/specs/2026-06-12-deepseek-balance-design.md`

---

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `usagetray/models.py` | Metric 加 `kind`/`text`；`worst_metric` 只看 percent | 修改 |
| `tests/test_models.py` | worst_metric 含 amount 行时的行为 | 新增 |
| `tests/fixtures/deepseek_balance.json` | DeepSeek 响应样本 | 新增 |
| `usagetray/providers/deepseek.py` | 读 key、请求、解析余额、错误兜底 | 新增 |
| `tests/test_deepseek.py` | provider 全路径测试 | 新增 |
| `tests/conftest.py` | 加 `deepseek_balance` fixture | 修改 |
| `usagetray/config.py` | DEFAULTS 加 `deepseek_api_key` + provider 开关 | 修改 |
| `tests/test_config.py` | 补 DEFAULTS 断言 | 修改 |
| `usagetray/providers/__init__.py` | 注册 DeepSeekProvider、注入 key | 修改 |
| `usagetray/app.py` | build_providers 传 key | 修改 |
| `usagetray/ui/panel.py` | 两处 `order` 加 deepseek | 修改 |
| `usagetray/ui/panel.html` | 主题色 + metricRow kind 分支 | 修改 |
| `README.md` | provider 列表 + 配置示例 | 修改 |

---

## Task 1: Metric 加 kind/text 字段

**Files:**
- Modify: `usagetray/models.py:11-27`

- [ ] **Step 1: 修改 Metric dataclass**

把 `usagetray/models.py` 的 `Metric` 类（第 11-27 行）替换为：

```python
@dataclass
class Metric:
    """A single limit window for a provider.

    ``used_percent`` is 0-100. ``resets_at`` is UTC (tz-aware) or None.
    ``kind`` is "percent" (progress bar) or "amount" (text like a balance);
    amount metrics carry their display string in ``text`` and ignore
    ``used_percent``.
    """

    label: str
    used_percent: float
    resets_at: datetime | None = None
    kind: str = "percent"
    text: str | None = None

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "used_percent": round(self.used_percent, 1),
            "resets_at": self.resets_at.isoformat() if self.resets_at else None,
            "kind": self.kind,
            "text": self.text,
        }
```

- [ ] **Step 2: 运行现有测试确认不回归**

Run: `python -m pytest tests/ -q`
Expected: PASS（38 passed；新字段有默认值，旧行为不变）

- [ ] **Step 3: Commit**

```bash
git add usagetray/models.py
git commit -m "feat: Metric 支持 amount 类型 (kind/text 字段)"
```

---

## Task 2: worst_metric 只看 percent 行

**Files:**
- Modify: `usagetray/models.py:49-53`
- Test: `tests/test_models.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_models.py`：

```python
from __future__ import annotations

from usagetray.models import Metric, UsageSnapshot


def test_worst_metric_ignores_amount_rows():
    snap = UsageSnapshot(
        provider_id="x",
        display_name="X",
        metrics=[
            Metric(label="周限额", used_percent=64.0),
            Metric(label="总余额 (¥)", used_percent=0.0, kind="amount", text="¥999.00"),
        ],
    )
    # amount 行 used_percent=0 但不应被当成 worst；percent 行才算
    assert snap.worst_metric is not None
    assert snap.worst_metric.label == "周限额"


def test_worst_metric_none_when_only_amounts():
    snap = UsageSnapshot(
        provider_id="x",
        display_name="X",
        metrics=[
            Metric(label="总余额 (¥)", used_percent=0.0, kind="amount", text="¥10.00"),
        ],
    )
    assert snap.worst_metric is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL —— 当前 `worst_metric` 对全部 metric 取 max，amount 行会被纳入（`test_worst_metric_none_when_only_amounts` 返回 amount 行而非 None）

- [ ] **Step 3: 修改 worst_metric**

把 `usagetray/models.py` 的 `worst_metric` 属性（第 49-53 行）替换为：

```python
    @property
    def worst_metric(self) -> Metric | None:
        """The percent metric with the highest utilization (most urgent limit).

        Amount metrics (balances) have no utilization and are excluded so they
        never drive the tray red-threshold logic.
        """
        percent_metrics = [m for m in self.metrics if m.kind == "percent"]
        if not percent_metrics:
            return None
        return max(percent_metrics, key=lambda m: m.used_percent)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_models.py tests/test_claude.py -v`
Expected: PASS（含原 `test_worst_metric`，确认 Claude 路径未回归）

- [ ] **Step 5: Commit**

```bash
git add usagetray/models.py tests/test_models.py
git commit -m "feat: worst_metric 排除 amount 行"
```

---

## Task 3: DeepSeek 响应 fixture + conftest

**Files:**
- Create: `tests/fixtures/deepseek_balance.json`
- Modify: `tests/conftest.py:26-28`

- [ ] **Step 1: 写 fixture**

新建 `tests/fixtures/deepseek_balance.json`（单币种 CNY，对齐 DeepSeek 官方响应）：

```json
{
  "is_available": true,
  "balance_infos": [
    {
      "currency": "CNY",
      "total_balance": "110.00",
      "granted_balance": "10.00",
      "topped_up_balance": "100.00"
    }
  ]
}
```

- [ ] **Step 2: 加 fixture 到 conftest**

在 `tests/conftest.py` 末尾（第 28 行后）追加：

```python


@pytest.fixture
def deepseek_balance() -> dict:
    return load_fixture("deepseek_balance.json")
```

- [ ] **Step 3: Commit**

```bash
git add tests/fixtures/deepseek_balance.json tests/conftest.py
git commit -m "test: DeepSeek 余额响应 fixture"
```

---

## Task 4: DeepSeekProvider — 成功解析

**Files:**
- Create: `usagetray/providers/deepseek.py`
- Test: `tests/test_deepseek.py`

- [ ] **Step 1: 写失败测试**

新建 `tests/test_deepseek.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_deepseek.py::test_parse_single_currency -v`
Expected: FAIL —— `ModuleNotFoundError: usagetray.providers.deepseek`

- [ ] **Step 3: 写 provider 实现**

新建 `usagetray/providers/deepseek.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_deepseek.py::test_parse_single_currency -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add usagetray/providers/deepseek.py tests/test_deepseek.py
git commit -m "feat: DeepSeekProvider 余额解析"
```

---

## Task 5: DeepSeekProvider — 多币种 + key 来源

**Files:**
- Modify: `tests/test_deepseek.py`

- [ ] **Step 1: 追加测试**

在 `tests/test_deepseek.py` 末尾追加：

```python
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
```

- [ ] **Step 2: 运行测试确认通过**

Run: `python -m pytest tests/test_deepseek.py -v`
Expected: PASS（全部 5 个测试）

- [ ] **Step 3: Commit**

```bash
git add tests/test_deepseek.py
git commit -m "test: DeepSeek 多币种与 key 来源"
```

---

## Task 6: DeepSeekProvider — 错误路径

**Files:**
- Modify: `tests/test_deepseek.py`

- [ ] **Step 1: 追加测试**

在 `tests/test_deepseek.py` 末尾追加：

```python
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
```

- [ ] **Step 2: 运行测试确认通过**

Run: `python -m pytest tests/test_deepseek.py -v`
Expected: PASS（含 5 个参数化 + 4 个错误路径）

- [ ] **Step 3: Commit**

```bash
git add tests/test_deepseek.py
git commit -m "test: DeepSeek 错误路径"
```

---

## Task 7: 配置 DEFAULTS

**Files:**
- Modify: `usagetray/config.py:16-19`
- Modify: `tests/test_config.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_config.py` 的 `test_defaults_created_when_missing` 里（第 12 行 `assert cfg["providers"]["claude"] is True` 之后）追加断言：

```python
    assert cfg["providers"]["deepseek"] is True
    assert cfg["deepseek_api_key"] == ""
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_config.py::test_defaults_created_when_missing -v`
Expected: FAIL —— KeyError `deepseek` / `deepseek_api_key`

- [ ] **Step 3: 修改 DEFAULTS**

把 `usagetray/config.py` 的 `DEFAULTS`（第 16-19 行）替换为：

```python
DEFAULTS = {
    "min_fetch_gap_seconds": 60,
    "providers": {"claude": True, "codex": True, "deepseek": True},
    "deepseek_api_key": "",
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS（新字段经现有合并逻辑自动识别）

- [ ] **Step 5: Commit**

```bash
git add usagetray/config.py tests/test_config.py
git commit -m "feat: config 加 deepseek_api_key 与 provider 开关"
```

---

## Task 8: 注册 provider + app 注入 key

**Files:**
- Modify: `usagetray/providers/__init__.py:25-35`
- Modify: `usagetray/app.py:32-33`

- [ ] **Step 1: 改 build_providers**

把 `usagetray/providers/__init__.py` 的 `build_providers`（第 25-35 行）替换为：

```python
def build_providers(
    enabled: dict[str, bool] | None = None,
    deepseek_api_key: str = "",
) -> list[Provider]:
    """Instantiate the registered providers.

    ``enabled`` maps provider id -> bool; missing ids default to enabled.
    ``deepseek_api_key`` is injected into DeepSeekProvider (empty -> provider
    falls back to the DEEPSEEK_API_KEY env var).
    """
    from .claude import ClaudeProvider
    from .codex import CodexProvider
    from .deepseek import DeepSeekProvider

    enabled = enabled or {}
    registry: list[Provider] = [
        ClaudeProvider(),
        CodexProvider(),
        DeepSeekProvider(api_key=deepseek_api_key or None),
    ]
    return [p for p in registry if enabled.get(p.id, True)]
```

- [ ] **Step 2: 改 app.py 调用**

把 `usagetray/app.py` 第 32 行：

```python
        providers = build_providers(self.config.get("providers"))
```

替换为：

```python
        providers = build_providers(
            self.config.get("providers"),
            self.config.get("deepseek_api_key", ""),
        )
```

- [ ] **Step 3: 运行全套测试**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 4: 冒烟验证 provider 装配**

Run:
```bash
python -c "from usagetray.providers import build_providers; print([p.id for p in build_providers()])"
```
Expected: `['claude', 'codex', 'deepseek']`

- [ ] **Step 5: Commit**

```bash
git add usagetray/providers/__init__.py usagetray/app.py
git commit -m "feat: 注册 DeepSeekProvider 并注入 key"
```

---

## Task 9: 面板排序

**Files:**
- Modify: `usagetray/ui/panel.py`（`Api.get_snapshots` 与 `Panel.push_update` 两处 `order`）

- [ ] **Step 1: 改两处 order 字典**

在 `usagetray/ui/panel.py` 中，两处 `order = {"claude": 0, "codex": 1}` 都替换为：

```python
        order = {"claude": 0, "codex": 1, "deepseek": 2}
```

一处在 `Api.get_snapshots`（约第 75 行），一处在 `Panel.push_update`（约第 320 行）。两处都要改。

- [ ] **Step 2: 确认无遗漏**

Run: `python -m pytest tests/ -q` 然后
```bash
git grep -n 'order = {"claude"' usagetray/ui/panel.py
```
Expected: 两行输出，均包含 `"deepseek": 2`

- [ ] **Step 3: Commit**

```bash
git add usagetray/ui/panel.py
git commit -m "feat: 面板排序加入 deepseek"
```

---

## Task 10: 前端渲染（panel.html）

**Files:**
- Modify: `usagetray/ui/panel.html`

- [ ] **Step 1: 加主题色变量**

在 `:root` 块（约第 8-18 行）的 `--codex: #c8c8d0;` 之后加一行：

```css
    --deepseek: #4d6bfe;
```

- [ ] **Step 2: 加卡片圆点 + 金额样式**

在 `.card-head .name.codex::before { ... }`（约第 53 行）之后加：

```css
  .card-head .name.deepseek::before { content: "●"; color: var(--deepseek); margin-right: 6px; }
```

在 `.metric-top .pct { ... }`（约第 58 行）之后加：

```css
  .metric-top .amount { color: var(--text); font-variant-numeric: tabular-nums; font-weight: 600; }
```

- [ ] **Step 3: metricRow 按 kind 分支**

把 `metricRow(m, pid)` 函数（约第 121-130 行）替换为：

```js
  function metricRow(m, pid) {
    if (m.kind === 'amount') {
      return `<div class="metric">
        <div class="metric-top"><span class="label">${esc(m.label)}</span>
          <span class="amount">${esc(m.text || '')}</span></div>
      </div>`;
    }
    const hot = m.used_percent >= 90 ? ' hot' : '';
    const w = Math.max(0, Math.min(100, m.used_percent));
    return `<div class="metric">
      <div class="metric-top"><span class="label">${esc(m.label)}</span>
        <span class="pct">${m.used_percent.toFixed(0)}%</span></div>
      <div class="bar ${pid}"><span class="${hot.trim()}" style="width:${w}%"></span></div>
      <div class="reset">${esc(resetIn(m.resets_at))}</div>
    </div>`;
  }
```

- [ ] **Step 4: 语法自检（无构建步骤，肉眼 + 浏览器）**

打开 `usagetray/ui/panel.html` 确认：`--deepseek` 变量、`.name.deepseek::before`、`.amount` 样式、`metricRow` 的 `kind === 'amount'` 分支都已就位，括号配对正确。

- [ ] **Step 5: Commit**

```bash
git add usagetray/ui/panel.html
git commit -m "feat: 面板渲染 DeepSeek 金额行"
```

---

## Task 11: 端到端冒烟运行

**Files:** 无（仅运行验证）

- [ ] **Step 1: 全套测试**

Run: `python -m pytest tests/ -q`
Expected: PASS（约 50+ passed）

- [ ] **Step 2: 真实启动（需有 DeepSeek key）**

先临时设置 key（PowerShell）：
```powershell
$env:DEEPSEEK_API_KEY = "sk-你的key"
python -m usagetray
```
预期：托盘出现图标；鼠标悬停弹出面板；面板里 Claude / Codex / DeepSeek 三张卡片，DeepSeek 卡片显示蓝色圆点 + 三行金额（总余额 / 充值余额 / 赠送余额）。未设置 key 时 DeepSeek 卡片显示"未配置 DeepSeek API key…"错误提示，其他两个 provider 不受影响。

> 若无法本地启动 GUI，此步可由用户手动验证；测试套件已覆盖 provider 全路径。

- [ ] **Step 3: 关闭后无需提交**（仅验证）

---

## Task 12: 文档更新

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 更新 provider 列表**

在 `README.md` 描述 Codex provider 的条目之后（约第 59 行的 Codex 行后），加一条 DeepSeek 说明：

```markdown
  - DeepSeek: `GET https://api.deepseek.com/user/balance`
    (`Authorization: Bearer`)。Key 来自 config.json 的 `deepseek_api_key`，
    缺省回退环境变量 `DEEPSEEK_API_KEY`。展示账户余额（总额 / 充值 / 赠送），
    不上托盘图标。
```

- [ ] **Step 2: 更新配置示例**

把 `README.md` 配置块（约第 68-73 行）替换为：

```json
{
  "min_fetch_gap_seconds": 60,
  "providers": { "claude": true, "codex": true, "deepseek": true },
  "deepseek_api_key": ""
}
```

并在配置块下方加一句说明：

```markdown
`deepseek_api_key` 留空时回退到环境变量 `DEEPSEEK_API_KEY`。
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README 加入 DeepSeek provider 说明"
```

---

## 完成标准

- `python -m pytest tests/ -q` 全绿
- `build_providers()` 返回含 `deepseek`
- 面板出现 DeepSeek 卡片，金额行无进度条、有蓝色圆点
- 无 key 时 DeepSeek 卡片显示配置提示，不影响 Claude/Codex
- README 反映新 provider 与配置
