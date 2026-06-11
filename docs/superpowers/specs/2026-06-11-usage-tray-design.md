# UsageTray — AI 编码工具余量托盘挂件 设计文档

日期：2026-06-11
平台：Windows 10/11（64 位）
技术栈：Python 3.11+ · pystray（托盘）· pywebview（弹出面板）· Pillow（图标绘制）· requests（HTTP）
打包：PyInstaller 单文件 EXE

## 1. 背景与目标

用户同时订阅 Claude Code 和 ChatGPT（Codex CLI），两者都有 5 小时会话限额和 7 天周限额。希望在 Windows 托盘常驻一个挂件，随时看到两边剩余额度，避免写代码写到一半被掐断。

**v1 目标：**
- 托盘图标实时（默认 60s 轮询）显示 Claude Code 与 Codex 的用量
- 左键点击托盘图标弹出详情面板：各项限额的进度条、百分比、重置倒计时
- 零配置：复用本机已有的 Claude Code / Codex CLI 登录凭证，无需填 API key
- 单 EXE 免安装，可选开机自启

**非目标（v1 不做）：**
- 用量阈值通知/弹窗提醒（用户明确不要）
- macOS / Linux 支持（数据层保持平台无关，UI 层只做 Windows）
- 多账号
- DeepSeek / MiniMax（v2 以 Provider 插件形式追加，见 §9）

## 2. 总体架构

```
providers/  ──fetch()──►  poller(后台线程)  ──写──►  state(线程安全缓存)
  claude.py                                            │
  codex.py                                   ┌─────────┴─────────┐
                                             ▼                   ▼
                                        tray(pystray)      panel(pywebview)
                                        图标+右键菜单        HTML 详情面板
```

四个模块职责单一，UI 只读 state，不直接碰网络；单个 Provider 失败不影响其余部分。

### 目录结构

```
usagetray/
  __main__.py        # 入口:装配各模块,处理线程模型
  models.py          # Metric / UsageSnapshot 数据类
  state.py           # AppState:快照缓存+锁+变更回调
  poller.py          # 轮询线程,按 Provider 隔离错误与退避
  providers/
    __init__.py      # Provider 协议定义 + 注册表
    claude.py
    codex.py
  ui/
    tray.py          # pystray 图标绘制与菜单
    panel.py         # pywebview 窗口管理与 JS bridge
    panel.html       # 面板 UI(内联 CSS/JS,单文件)
  config.py          # 配置读写 + 开机自启注册表开关
  log.py             # 日志(RotatingFileHandler)
tests/
  fixtures/          # 各 Provider 的响应 JSON 样本
  test_claude.py
  test_codex.py
  test_poller.py
```

## 3. 数据模型

```python
@dataclass
class Metric:
    label: str                    # 例 "5h 会话" / "周限额" / "周限额(Opus)"
    used_percent: float           # 0–100
    resets_at: datetime | None    # UTC,可为空

@dataclass
class UsageSnapshot:
    provider_id: str              # "claude" / "codex"
    display_name: str             # "Claude Code" / "OpenAI Codex"
    metrics: list[Metric]         # 失败时为空
    fetched_at: datetime
    error: str | None             # 人类可读错误+修复提示;成功为 None
```

### Provider 协议

```python
class Provider(Protocol):
    id: str
    display_name: str
    def fetch(self) -> UsageSnapshot: ...   # 永不抛异常,失败返回带 error 的快照
```

新增服务商 = 在 `providers/` 加一个文件并注册，其余模块零改动。

## 4. 数据源细节

> 两个接口均为各官方客户端使用的非公开接口，字段名以实现时实际抓取的响应为准。
> 实现前先用脚本各调一次真实接口并把响应存入 `tests/fixtures/`，再按真实结构写解析。
> 参考实现：jens-duttke/usage-monitor-for-claude（Claude 侧）、steipete/codexbar（Codex 侧）。

### 4.1 Claude（claude.py）

- **凭证**：`%USERPROFILE%\.claude\.credentials.json` → `claudeAiOauth.accessToken`（含 `expiresAt`）
- **接口**：`GET https://api.anthropic.com/api/oauth/usage`
  请求头：`Authorization: Bearer <token>`、`anthropic-beta: oauth-2025-04-20`
- **预期响应**：`five_hour` / `seven_day`（以及可能的 `seven_day_opus` 等）对象，各含 `utilization`（0–100）与 `resets_at`（ISO 时间）
- **映射**：five_hour → "5h 会话"；seven_day → "周限额"；存在 opus 项则追加 "周限额 (Opus)"
- **token 过期**：若本地 `expiresAt` 已过或接口返回 401，先尝试用 `refreshToken` 走一次标准 OAuth refresh（参考上述开源项目的做法）；刷新失败则在快照 error 中提示"请在终端运行一次 claude 以刷新登录"。刷新成功后将新 token 写回 `.credentials.json` 之外的内存缓存即可，**不回写用户凭证文件**。

### 4.2 Codex（codex.py）

- **凭证**：`%USERPROFILE%\.codex\auth.json` → `tokens.access_token`、`tokens.account_id`
- **接口**：ChatGPT backend 的 Codex 用量端点（`https://chatgpt.com/backend-api/...`，具体路径与请求头以 codexbar 源码及真实抓取为准）
  预期返回主/次两个限额窗口（5h 与周），各含已用百分比与重置时间（`used_percent` / `resets_in_seconds` 或同义字段）
- **映射**：primary → "5h 会话"；secondary → "周限额"
- **token 过期**：401 时提示"请在终端运行 codex 并完成登录刷新"（v1 不实现 Codex 侧 refresh flow，auth.json 由 Codex CLI 自己维护，通常长期有效）

## 5. 轮询与状态

- **poller**：daemon 线程，默认间隔 60s（config 可调），每轮依次调用各 Provider 的 `fetch()`。
- **错误退避**：按 Provider 独立计算——连续失败时该 Provider 的下次轮询间隔按 60s → 120s → 300s 封顶递增，成功后复位。另一个 Provider 不受影响。
- **手动刷新**：托盘菜单"立即刷新"和面板刷新按钮触发一次立即轮询（Event 唤醒线程）。
- **state**：`dict[provider_id, UsageSnapshot]` + `threading.Lock`；注册回调列表，快照更新后通知 tray 重绘图标、panel 刷新数据。

## 6. UI 设计

### 6.1 托盘图标（tray.py）

- 32×32 图标由 Pillow 动态绘制：**上下两条横向进度条**，上=Claude（橙 #D97757），下=Codex（白/灰），底色深灰。用量 >90% 时该条变红。
- 进度条取该 Provider 各 metric 中**用量最高**的一项（最紧迫的限额）。
- Provider 出错时对应条显示为灰色斜纹/半透明。
- tooltip：`Claude 37% (5h) · Codex 12% (5h)` 式摘要。
- 菜单：左键 → 显示/隐藏面板；右键 → 立即刷新 / 开机自启（勾选项）/ 退出。

### 6.2 弹出面板（panel.py + panel.html）

- pywebview 无边框窗口，约 360×300，置顶，`easy_drag` 关闭。
- 出现位置：屏幕工作区右下角（贴近托盘）。失焦（JS `blur` 事件）自动隐藏；再点托盘重新显示。
- 内容：每个 Provider 一张卡片——
  - 标题行：服务商名 + 最近更新时间（"42 秒前"）
  - 每个 Metric 一行：标签、进度条（同托盘配色，>90% 红）、百分比、重置倒计时（"3h 12m 后重置"）
  - 错误态：卡片显示错误信息与修复提示，保留上次成功数据（标注"数据来自 xx 分钟前"）
- 底部：刷新按钮、退出按钮。
- JS bridge：`pywebview.api.get_snapshots()` / `refresh()` / `quit()`；Python 侧在快照更新时 `evaluate_js` 推送新数据。

### 6.3 线程模型（关键约束）

pywebview 的 `webview.start()` 必须占用主线程（Windows 上的 WebView2 消息循环）。装配顺序：

1. 主线程：创建隐藏的 pywebview 窗口 → `webview.start(func=bootstrap)` 
2. `bootstrap` 内启动 poller 线程与 pystray（`icon.run_detached()`）
3. 托盘事件通过 `window.show()/hide()` 控制面板；退出时先 `icon.stop()` 再 `window.destroy()`

## 7. 配置、日志与打包

- **配置**：`%APPDATA%\UsageTray\config.json`，v1 仅 `poll_interval_seconds`（默认 60）与 `providers` 启用开关。文件不存在时用默认值并自动创建。
- **开机自启**：写/删 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 下的 `UsageTray` 值，托盘菜单勾选切换。
- **日志**：`%APPDATA%\UsageTray\usagetray.log`，RotatingFileHandler（1MB×3），记录轮询错误与异常栈；不记录 token。
- **打包**：`pyinstaller --onefile --noconsole`，panel.html 以 `--add-data` 内嵌；产物 `UsageTray.exe`。
- **单实例**：启动时持有命名互斥量（`CreateMutex`），已运行则直接退出。

## 8. 错误处理矩阵

| 场景 | 行为 |
|---|---|
| 凭证文件不存在 | 卡片提示"未检测到 Claude Code/Codex 登录，请先在终端登录" |
| 凭证 JSON 结构变化 | 卡片提示"凭证格式无法识别"，日志记录详情 |
| 401 / token 过期 | Claude：尝试 refresh，失败则提示重新登录；Codex：直接提示 |
| 网络错误 / 超时(10s) | 保留上次数据并标注过期时间，按退避策略重试 |
| 接口字段变化 | 解析失败按错误处理，不崩溃；日志含原始响应（脱敏） |
| 单 Provider 持续失败 | 其余 Provider 正常轮询与展示 |

任何未捕获异常由 poller 顶层兜底记日志，应用本体不退出。

## 9. v2 扩展（仅留接口，不实现）

- **DeepSeek**：`GET https://api.deepseek.com/user/balance`（API key 鉴权），返回美元/人民币余额——属"余额型" Metric，`Metric` 需支持 `kind: percent | balance`（v1 先按 percent 实现，字段预留注释即可，不做抽象）。
- **MiniMax**：token plan 用量，待确认官方是否开放查询接口。
- 配置文件的 `providers` 数组天然支持开关新增项。

## 10. 测试策略

- **单测**（pytest + responses/monkeypatch 模拟 HTTP）：
  - 各 Provider：正常解析（用 fixtures 真实响应样本）、凭证缺失、401、网络超时、字段缺失
  - poller：单 Provider 失败隔离、退避计时、手动刷新唤醒
- **手动验收清单**：托盘图标随用量更新；点击弹出/失焦隐藏；断网后恢复；凭证删除后的提示；退出干净（无残留进程）；打包后的 EXE 在干净环境运行。

## 11. 里程碑

1. **M1 数据层**：providers + models + poller + 单测，CLI 方式打印两家实时用量（先验证真实接口）
2. **M2 UI**：托盘图标 + 面板 + 线程装配
3. **M3 收尾**：配置/自启/日志/单实例 + PyInstaller 打包验收

## 12. 风险

- 两个接口均非公开承诺接口，可能随官方客户端改版变动 → Provider 层隔离变更影响，解析失败有兜底展示
- WebView2 运行时缺失（极少数精简系统）→ 启动时检测并提示安装链接
