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
| 7 | 命令面板（`/` 过滤 + Tab 补全） | ✓ | ✓ | **切片 A（本 PR）** | `filterCommands` + `sliceWindow`；pty `PALETTE_SHOWN/TAB_COMPLETED` |
| 8 | 选择器浮层（`/resume`/`/theme`/`/mode`） | ✓ | ✓ | **切片 A（本 PR）** | `selector.ts` 复用；pty `SELECTOR_SHOWN/CANCELLED` |
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
