# DeepSeek 余额显示 — 设计文档

日期：2026-06-12
状态：已批准设计，待写实施计划

## 目标

为 UsageTray 托盘挂件新增第三个 provider：DeepSeek，在面板里以纯文本金额展示账户余额（总额 + 充值/赠送细分）。不上托盘图标，只进面板卡片。

## 背景

现有架构：

- `providers/` 下每个服务一个模块，实现 `Provider` 协议（`id`、`display_name`、永不抛异常的 `fetch() -> UsageSnapshot`）。
- `models.py` 定义 `Metric`（单个限额窗口，`used_percent` 0-100）和 `UsageSnapshot`。
- 后台 `Poller` 按需拉取，`AppState` 缓存快照，`panel.html` 通过 JS 桥渲染。
- 托盘图标只画 Claude/Codex 两条固定 bar，DeepSeek 不参与图标渲染。

核心矛盾：现有 `Metric` 只有 `used_percent` 百分比语义，UI 只会画进度条；而余额是金额，没有自然上限，不适合画进度条。

## 需求确认

| 项 | 决定 |
|---|---|
| API key 来源 | `config.json` 的 `deepseek_api_key`，缺省回退环境变量 `DEEPSEEK_API_KEY` |
| 显示形式 | 纯文本金额，不画进度条 |
| 细分展示 | 总余额 / 充值余额 / 赠送余额 各一行独立 metric |
| 低额提醒 | 不做 |
| 接口 | `GET https://api.deepseek.com/user/balance`（Bearer key） |

## 方案选择

数据模型如何承载金额，考虑过三个方案：

- **A（采用）**：给 `Metric` 加可选 `kind` / `text` 字段。改动最小，现有 `to_dict → JSON → JS` 数据流、错误兜底全部原样复用。
- B：`UsageSnapshot` 加 snapshot 级 `balance` 字段。Metric 干净，但序列化/渲染/缓存/兜底都要加分支，改动面更大。
- C：Metric 拆成 PercentMetric / AmountMetric 两类。类型最正确，但 Python/JSON/JS 三处都要判别，对此体量过度设计。

采用 A：用一个可选 `kind` 区分百分比行与金额行，复用既有渲染路径。

## 详细设计

### 1. 数据模型（models.py）

`Metric` 增加两个可选字段，默认值保证现有 Claude/Codex 行为不变：

```python
@dataclass
class Metric:
    label: str
    used_percent: float          # amount 类型时填 0.0，不参与显示
    resets_at: datetime | None = None
    kind: str = "percent"        # "percent" | "amount"
    text: str | None = None      # amount 类型的展示文本，如 "¥110.00"

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "used_percent": round(self.used_percent, 1),
            "resets_at": self.resets_at.isoformat() if self.resets_at else None,
            "kind": self.kind,
            "text": self.text,
        }
```

`UsageSnapshot.worst_metric` 改为只看 percent 类型，避免 amount 行干扰托盘红色判定：

```python
@property
def worst_metric(self) -> Metric | None:
    percent_metrics = [m for m in self.metrics if m.kind == "percent"]
    if not percent_metrics:
        return None
    return max(percent_metrics, key=lambda m: m.used_percent)
```

### 2. DeepSeek Provider（providers/deepseek.py）

与 claude.py / codex.py 同构，`fetch()` 永不抛异常。

- **接口**：`GET https://api.deepseek.com/user/balance`，头 `Authorization: Bearer <key>`、`Accept: application/json`，10s 超时。
- **响应结构**（DeepSeek 官方）：
  ```json
  {
    "is_available": true,
    "balance_infos": [
      {"currency": "CNY", "total_balance": "110.00",
       "granted_balance": "10.00", "topped_up_balance": "100.00"}
    ]
  }
  ```
  `balance_infos` 是数组，可能含多币种（CNY、USD）。
- **Key 读取**：构造时注入 `DeepSeekProvider(api_key=...)`。key 为空时在 provider 内回退查环境变量 `DEEPSEEK_API_KEY`；仍无则返回配置提示错误快照。静态 API key，无 OAuth refresh 逻辑。
- **产出 metric**：每币种 3 行 amount metric，按 `balance_infos` 数组顺序：
  ```
  总余额 (¥)    ¥110.00
  充值余额 (¥)  ¥100.00
  赠送余额 (¥)   ¥10.00
  ```
  币种符号映射 CNY→`¥`、USD→`$`。金额字段是字符串，解析为 float 后格式化；解析失败的行跳过。`is_available` 只读不展示。
- **错误文案**（对齐 claude.py 中文风格）：
  - 无 key → "未配置 DeepSeek API key（config.json 的 deepseek_api_key 或环境变量 DEEPSEEK_API_KEY）。"
  - 401 → "DeepSeek API key 无效，请检查 config.json 或 DEEPSEEK_API_KEY。"
  - 429 → "接口限流（429），稍后重试。"
  - ≥500 → "服务端错误（N），稍后重试。"
  - 超时 / 连接失败 → 复用现有文案
  - 非 JSON / 结构异常 / 零有效行 → 对应提示

### 3. 配置与注册

**config.py** — `DEFAULTS` 新增字段（新字段在 DEFAULTS 内即被 `load_config` 的现有合并逻辑识别，无需改合并代码）：

```python
DEFAULTS = {
    "min_fetch_gap_seconds": 60,
    "providers": {"claude": True, "codex": True, "deepseek": True},
    "deepseek_api_key": "",
}
```

**providers/__init__.py** — 注册并注入 key：

```python
def build_providers(enabled=None, deepseek_api_key=""):
    from .claude import ClaudeProvider
    from .codex import CodexProvider
    from .deepseek import DeepSeekProvider

    enabled = enabled or {}
    registry = [
        ClaudeProvider(),
        CodexProvider(),
        DeepSeekProvider(api_key=deepseek_api_key or None),
    ]
    return [p for p in registry if enabled.get(p.id, True)]
```

**app.py** — 调用处传入 key：

```python
providers = build_providers(
    self.config.get("providers"),
    self.config.get("deepseek_api_key", ""),
)
```

**排序** — `panel.py` 的 `Panel.push_update` 和 `Api.get_snapshots` 两处 `order` 字典各加 `"deepseek": 2`。

### 4. UI（panel.html）

- CSS 新增 DeepSeek 主题色 `--deepseek: #4d6bfe`，用于卡片标题圆点 `.card-head .name.deepseek::before`。
- `metricRow()` 按 `kind` 分支 —— 前端唯一逻辑改动。amount 行只渲染 label + 右侧金额文本，不画 bar / 重置时间：

```js
function metricRow(m, pid) {
  if (m.kind === 'amount') {
    return `<div class="metric">
      <div class="metric-top"><span class="label">${esc(m.label)}</span>
        <span class="amount">${esc(m.text || '')}</span></div>
    </div>`;
  }
  // 原 percent 分支不变
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

- amount 文本样式：`.metric-top .amount { color: var(--text); font-variant-numeric: tabular-nums; font-weight: 600; }`
- 卡片渲染、错误兜底（lastGood 显示上次成功数据）、刷新机制全部原样复用。

### 5. 测试

新增 `tests/test_deepseek.py`（对齐 test_claude.py，mock requests，不打真实网络）：

- 成功解析：CNY 单币种 → 3 行 amount metric，`kind=="amount"`、`text` 格式正确、`snapshot.ok`
- 多币种：CNY+USD → 6 行，顺序正确
- 无 key：config 与环境变量都缺 → 错误快照，文案含配置提示
- config key 优先于环境变量
- 环境变量回退：config 空、环境变量有 → 用环境变量
- 401 / 429 / 5xx / 超时 / 连接失败 → 各自中文错误快照，`fetch()` 不抛异常
- 金额字符串异常 → 跳过该行不崩溃

补充改动：

- `test_config.py`：断言 DEFAULTS 含 `deepseek_api_key`，providers 含 `deepseek`
- `worst_metric` 测试（若有）：含 amount metric 时 `worst_metric` 只看 percent 行

## 影响面

| 文件 | 改动 |
|---|---|
| `usagetray/models.py` | Metric 加 2 字段；worst_metric 过滤 percent |
| `usagetray/providers/deepseek.py` | 新增 |
| `usagetray/providers/__init__.py` | 注册 + 注入 key |
| `usagetray/config.py` | DEFAULTS 加字段 |
| `usagetray/app.py` | build_providers 传 key |
| `usagetray/ui/panel.py` | order 加 deepseek |
| `usagetray/ui/panel.html` | 主题色 + metricRow kind 分支 |
| `tests/test_deepseek.py` | 新增 |
| `tests/test_config.py` | 补断言 |
| `README.md` | 文档更新（provider 列表、配置示例） |

## 非目标（YAGNI）

- 不做托盘图标集成（DeepSeek 不上图标）
- 不做低余额红色提醒
- 不做进度条 / 预算上限
- 不做用量历史曲线
