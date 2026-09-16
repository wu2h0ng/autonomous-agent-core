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
| 10 | `@` mentions 列表 + 补全 | ✓ | ✗ | **缺失** | 需接 `mentions.ts` + files 列表 |
| 11 | vim 模式 | ✓ | ✗ | **缺失** | 需接 `controller.vimMode` + 运动键 |
| 12 | 多行 composer + 光标/词移动 + 外部编辑器 | ✓ | ✗ | **缺失** | 全屏目前是单行 `input`；需接 `composer.ts`/`editor.ts` |
| 13 | 输入历史（↑/↓） | ✓ | ✗ | **缺失** | 需接 `history.ts` |
| 14 | 历史搜索（ctrl+r 模式） | ✓ | ✗ | **缺失** | Ink `searchMode` |
| 15 | assistant 文本 Markdown 渲染 | ✓ | ✗ | **缺失** | 需接 `markdown.ts` |
| 16 | 代码语法高亮 | ✓ | ✗ | **缺失** | 需接 `highlight.ts` |
| 17 | 主题真正生效（颜色） | ✓ | △ | **部分** | 全屏只显示主题名，未应用 `THEMES` 配色 |
| 18 | 首页/欢迎面板 | ✓ | ✗ | **缺失** | `HomeView` 仅 Ink |
| 19 | `/status`、`/cost`、todo 面板 | ✓ | ✓ | DONE | 面板消息已渲染（`line()` 处理 `message.panel`） |

## 2. 结论

- 切片 A 关闭 #7、#8；**退役 Ink 仍需完成 #10–#14、#15–#18**（mentions、vim、多行/编辑器、历史、历史搜索、Markdown、高亮、主题配色、首页）。
- 迁移不变量：`SurfaceClient`/`TuiController`/协议/审批/C7 **不动**（纯视图层）。
- 退役方式（对齐后）：按 Stage 2f 的做法删 Ink 视图与依赖，保留回归清单与本文件的 DONE 证据。

## 3. 下一步（建议顺序）

1. 切片 B：mentions + 输入历史 + Markdown/高亮（纯模块已存在，视图接线为主）。
2. 切片 C：多行 composer + 光标运动 + 外部编辑器 + vim。
3. 切片 D：主题配色 + 首页/欢迎面板 → 之后退役 Ink。

## 4. 切片 A 的复审教训（已修，保留供追溯）

独立复审 R1 = REVISE，发现两个**真实**缺陷（均已修复并有测试）：

1. **死代码**：palette 的 `↑/↓`/`Tab`/`Enter` 分支被误嵌进 `if (selector)` 内 → 命令面板导航/补全完全不可达。根因是键路由只存在于组件里、无纯函数可测；现抽出 `src/opentui/viewkeys.ts`（键归属优先级：selector > approval > 冻结全局键 > palette > agents > 纯提交）并单测覆盖优先级（含"palette 打开时 Enter 不得切换会话"）。
2. **null 误判**：`selectorOpen: pendingSelector !== undefined`，而控制器在关闭时返回 **null** → 所有键都被判给 selector 层 → Enter/移动**全部失效**（连普通回合都无法提交）。改为真值判断，并加 `null/undefined/false` 回归测试。

**证据纪律**：切片 A 第一版的 pty 断言是**假阳性**（"commands" 取自命令描述文本、"Tab 补全"取自残留帧）。现改为：面板标题 `─commands`（有边框）+ **行为断言**（Enter 后面板出现 `session status … turns 0`）。

**残留风险（诚实）**：Ink `palette` 用例的 `useInput` 处理器引用可能滞后一帧，并行负载下偶发；现改为 UI 用例串行 + 等待 composer 回显 + 额外两拍，连续 8 次干净。Ink 退役后此风险消失。
