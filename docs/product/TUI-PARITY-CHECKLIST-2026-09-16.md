# TUI Parity Checklist — Ink vs 全屏视图（2026-09-16）

- **目的**：退役 Ink 前，逐项证明全屏视图（`src/opentui/`）功能对齐。
- **状态**：`IN_PROGRESS`（切片 A 已合并/在审；**尚不可退役 Ink**）。
- **基线**：`src/App.tsx`（Ink）为准；全屏为迁移目标。
- **判定**：每项需 (a) 视图实现、(b) 目标测试或 pty 证据、(c) 失败路径可降级。仅"看起来有"不算 DONE。

## 1. 对齐清单

| # | 能力 | Ink | 全屏 | 状态 | 证据/说明 |
|---|---|---|---|---|---|
| 1 | transcript（finalized/active/streaming） | ✓ | ✓ | DONE | P1 + `pty_fullscreen_p2/p3a` |
| 2 | 审批卡 + `y`/`n`（前台可见） | ✓ | ✓ | DONE | P1/P2；`awaiting` 强制 transcript |
| 3 | 顶栏 + footer（tokens/cost/events） | ✓ | ✓ | DONE | P1；cost 恒 UNKNOWN（诚实） |
| 4 | 窄终端降级 | ✓ | ✓ | DONE | `layoutFor`/`SIDEBAR_MIN_WIDTH` |
| 5 | 独立滚动面板 | ✗（Ink 无） | ✓ | 全屏领先 | P2（files/diff） |
| 6 | agents 树 + 会话切换 | ✗ | ✓ | 全屏领先 | P3a（+多会话 e2e） |
| 7 | 命令面板（`/` 过滤 + Tab 补全 + Enter 执行） | ✓ | ✓ | **切片 A** | `filterCommands` + `sliceWindow`；pty `PALETTE_SHOWN` + 行为断言 `PALETTE_ENTER_RAN_STATUS`（Enter 真的执行 `/status`） |
| 8 | 选择器浮层（`/resume`/`/theme`/`/mode`） | ✓ | ✓ | **切片 A** | `selector.ts` 复用；Esc 由 selector 独占（不会 approve/reject）；pty `SELECTOR_SHOWN/CANCELLED` |
| 9 | 斜杠帮助（`/help` 行） | ✓ | ✓ | DONE | 系统消息渲染 |
| 10 | `@` mentions 列表 + 补全 | ✓ | ✓ | **切片 B** | `mentions.ts` + `controller.workspaceFiles()`；pty `MENTION_TAB_COMPLETED`（经**提交后的新 transcript 行**观测） |
| 11 | vim 模式 | ✓ | ✗ | **缺失** | 需接 `controller.vimMode` + 运动键 |
| 12 | 多行 composer + 光标/词移动 + 外部编辑器 | ✓ | △ | **外部编辑器 DONE；多行缺失** | ctrl+g → `openExternalEditor`（pty `EDITOR_ROUNDTRIP: True`）；多行受限于单行 `<input>` |
| 13 | 输入历史（↑/↓） | ✓ | ✓ | **切片 B** | `InputHistory`；pty `HISTORY_PREVIOUS` |
| 14 | 历史搜索（ctrl+r 模式） | ✓ | ✗ | **缺失** | Ink `searchMode` |
| 15 | assistant 文本 Markdown 渲染 | ✓ | ✓ | **切片 B** | opentui `<markdown>` + `SyntaxStyle.create()`；pty `MARKDOWN_TRANSCRIPT_OK` |
| 16 | 代码语法高亮（彩色） | ✓ | ✗ | **缺失** | 现为 `<markdown>` 默认样式，未接配色 |
| 17 | 主题真正生效（颜色） | ✓ | △ | **部分** | 全屏只显示主题名，未应用 `THEMES` 配色 |
| 18 | 首页/欢迎面板 | ✓ | ✗ | **缺失** | `HomeView` 仅 Ink |
| 19 | `/status`、`/cost`、todo 面板 | ✓ | ✓ | DONE | 面板消息已渲染（`line()` 处理 `message.panel`） |

## 2. 结论

- 切片 A 关闭 #7、#8；**退役 Ink 仍需完成 #10–#14、#15–#18**（mentions、vim、多行/编辑器、历史、历史搜索、Markdown、高亮、主题配色、首页）。
- 迁移不变量：`SurfaceClient`/`TuiController`/协议/审批/C7 **不动**（纯视图层）。
- 退役方式（对齐后）：按 Stage 2f 的做法删 Ink 视图与依赖，保留回归清单与本文件的 DONE 证据。

## 3. 下一步（建议顺序）

1. ~~切片 B：mentions + 输入历史 + Markdown~~（已完成，见下）。
2. 切片 C：多行 composer + 光标运动 + 外部编辑器 + vim。
3. 切片 D：主题配色 + 首页/欢迎面板 → 之后退役 Ink。

## 4. 切片 A 的复审教训（已修，保留供追溯）

独立复审 R1 = REVISE，发现一个**真实**缺陷；R2 又发现修复引入的**回归**；另有一个由实现者自查发现（归因如下）：

1. **死代码**：palette 的 `↑/↓`/`Tab`/`Enter` 分支被误嵌进 `if (selector)` 内 → 命令面板导航/补全完全不可达。根因是键路由只存在于组件里、无纯函数可测；现抽出 `src/opentui/viewkeys.ts`（键归属优先级：selector > approval > 冻结全局键 > palette > agents > 纯提交）并单测覆盖优先级（含"palette 打开时 Enter 不得切换会话"）。
2. **null 误判（实现者自查，非 R1 发现）**：`pendingSelector` 在关闭时是 **null** → 所有键都被判给 selector 层 → Enter/移动**全部失效**（连普通回合都无法提交）。改为真值判断，并加 `null/undefined/false` 回归测试。
3. **R2 发现的回归（P1）**：修复 #1 时把 `tab`/`pageup`/`pagedown` 的分支一并删掉 → 面板切换/滚动失效，连带 **P2 面板选择与 P3a 会话切换**不可达。已把 `tab`/`pgup`/`pgdn` 作为显式 panel 归属放回 resolver（优先级在 palette 之后），并补单测；行为复验：P3a `RESUMED: True`、parity A 四项 True、多会话 `SWITCHED_TO_OTHER_SESSION: True`。

**证据纪律**：切片 A 第一版的 pty 断言是**假阳性**（"commands" 取自命令描述文本、"Tab 补全"取自残留帧）。现改为：面板标题 `─commands`（有边框）+ **行为断言**（Enter 后面板出现 `session status … turns 0`）。

**残留风险（诚实）**：Ink `palette` 用例的 `useInput` 处理器引用可能滞后一帧，并行负载下偶发；现改为 UI 用例串行 + 等待 composer 回显 + 额外两拍，连续 8 次干净。Ink 退役后此风险消失。

## 5. 已知轻微限制

- palette 打开时按 Esc 会走**冻结全局层**（streaming 时 interrupt / 否则无操作），不会关闭 palette；关闭方式为删掉 `/`。属 UX 轻微项，未改（避免动全局键语义）。

## 6. 切片 B（2026-09-16，已完成）

- **代码**：`viewkeys.ts` 新增 `mention`/`history` 键层（优先级：selector > approval > 冻结全局键 > palette > **mention** > panel(Tab) > agents > **history(↑/↓)** > 提交）；`app.tsx` 接 `workspaceFiles()`+`mentions.ts` 的 `@` 补全、`InputHistory` 的 ↑/↓、assistant 文本改用 opentui `<markdown>`（`SyntaxStyle.create()`）。
- **证据**（`scripts/pty_fullscreen_parity_b.py`，连续 2 次一致）：`HISTORY_PREVIOUS: True`、`MENTION_TAB_COMPLETED: True`（断言仅针对**提交窗口**，避免跨帧假阳性）、`MARKDOWN_RENDER_PATH_OK: True`（**smoke**：证明回复经 markdown 路径仍落入 transcript，**不是**格式测试）、`SLICE_B_ALL_SIGNALS_VERIFIED: True`（独立聚合，非复制单信号）。
- **复审条件（已修）**：① mention 列表打开时 **Enter 仍提交**（与 Ink 一致；此前被吞为 no-op）；② markdown 只作用于 **finalized** 消息（与 Ink 一致，避免流式半截 markdown 畸形）；③ 断言收紧 + 诚实标签 + 独立聚合信号。
- **证据方法论（重要，写进规范）**：**观测 composer 行的变化不可靠**（cell-diff 渲染器对单行改动可能不重发）；**观测新 transcript 内容可靠**（提交的消息、回复必然是新单元格）。因此 mention 补全通过"补全后提交 → 新用户消息出现在 transcript"来验证。
- 单测：`test/opentui-viewkeys.test.ts` 新增 mention/history 优先级用例（含"mention 打开时字母仍归 composer""agents 面板优先于 history"）；全量 **157 + 19 = 176 pass**。
- **未做**：彩色语法高亮（#16）、vim、多行 composer/外部编辑器、`ctrl+r` 历史搜索、主题配色、首页（切片 C/D）。

## 7. 切片 C（2026-09-16）：外部编辑器 DONE；多行/vim 的真实阻塞点

- **DONE — 外部编辑器（#12 部分）**：Ctrl-G 打开 `$EDITOR` 编辑草稿并回填（复用 `editor.ts`）；pty `EDITOR_ROUNDTRIP: True`（连续多次）。绑定历经三次修正（记录供追溯）：① `ctrl && name === "g"` → **死绑定**（opentui 对控制字节不置 `ctrl` 标志）；② 仅按 `name === "g"` → **回归风险**（Tab 后输入框失焦时普通 `g` 也会命中、误开编辑器）；③ 最终按 **控制字节 `sequence === "\u0007"`** 绑定（普通 `g` 的 sequence 为 `"g"`），并加"普通 g 不开编辑器"的回归测试。
- **键投递矩阵（`scripts/pty_fullscreen_parity_c.py`，每个候选键**独立重启**应用）**：`return / tab / escape / up / down / ctrl-n / ctrl-p / ctrl-j(name=linefeed) / ctrl-g(name=g) / ctrl-o / f2 / alt-g` **均可到达**（矩阵测量需要临时开启 `NOEM_KEY_DEBUG` 仪器；脚本无仪器时打印 `DELIVERY_MATRIX_SKIPPED`，不谎报）。`sequence` 可用于区分：Ctrl-G 为 `\u0007`、普通 `g` 为 `g`。
- **方法论教训**：同一实例连续投递会因 Tab/Enter 改变焦点而**污染**矩阵（初版探针因此误报"全部可达"，我据此得出过错误结论并在本轮更正）。
- **真实阻塞点（多行 + vim）**：不是键投递，而是 **composer 形态**——当前用 opentui 原生**单行 `<input>`**，因此 `ctrl+j` 换行**无法显示**，vim 的模态编辑也无法接管原生编辑。需要"自持 composer"（自绘文本+光标，接 `composer.ts`）或改 `textarea`，属更大改动，**未做**。
- 因此 **#11 vim 仍缺失、#12 多行仍缺失**；Ink 退役继续阻塞。
