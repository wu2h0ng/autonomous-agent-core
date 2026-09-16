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
| 10 | `@` mentions 列表 + 补全 | ✓ | ✓ | **切片 B/C2** | `mentions.ts` + `controller.workspaceFiles()`；pty `MENTION_COMPLETED_ON_SUBMIT`（经**提交后的新 transcript 行**观测；Tab 在有内容时被 textarea 自身消费） |
| 11 | vim 模式（normal/insert + 运动/操作符） | ✓ | ✓ | **切片 D DONE** | 纯模块 `src/opentui/vim.ts` + `controller.vimMode`；pty `VIM_NORMAL_EDIT_SUBMITTED`；见 §9 |
| 12 | 多行 composer + 光标/词移动 + 外部编辑器 | ✓ | ✓ | **切片 C2 DONE** | `<textarea>` 底座（多行/光标/词移动原生）+ Ctrl-G 外部编辑器；见 §8 |
| 13 | 输入历史（↑/↓） | ✓ | ✓ | **切片 B** | `InputHistory`；pty `HISTORY_PREVIOUS` |
| 14 | 历史搜索（ctrl+r 模式） | ✓ | ✗ | **缺失** | Ink `searchMode` |
| 15 | assistant 文本 Markdown 渲染 | ✓ | ✓ | **切片 B** | opentui `<markdown>` + `SyntaxStyle.create()`；pty `MARKDOWN_RENDER_PATH_OK`（smoke） |
| 16 | 代码语法高亮（彩色） | ✓ | ✗ | **未生效（已实测）** | stub 现在返回 fenced python 块且**渲染正常**，但代码 token 的 fg 全为默认白 → 注册的 `SyntaxStyle` scope **未被 markdown 渲染器应用**；诚实复现器 `scripts/pty_highlight_check.py`（`CODE_COLOURED: False`，未修好前 exit 1）|
| 17 | 主题真正生效（颜色） | ✓ | ✓ | **DONE** | `theme-colors.ts` 把 `THEMES` 的 Ink 颜色名解析为 hex，并接到 transcript（按角色）、审批卡、顶栏、footer、composer 边框；pty `THEME_APPLIED` 断言 footer 的 SGR 随 `/theme mono` 变化 |
| 18 | 首页/欢迎面板 | ✓ | ✗ | **缺失** | `HomeView` 仅 Ink |
| 19 | `/status`、`/cost`、todo 面板 | ✓ | ✓ | DONE | 面板消息已渲染（`line()` 处理 `message.panel`） |

## 2. 结论

- 切片 A/B 关闭 #7/#8/#10/#13/#15，#11 vim、#12 多行由切片 D/C2 关闭；**退役 Ink 仍缺 #14（ctrl+r 历史搜索）、#16（彩色高亮）、#17（主题配色）、#18（首页）与多行显示/滚动**（mentions、vim、多行/编辑器、历史、历史搜索、Markdown、高亮、主题配色、首页）。
- 迁移不变量：`SurfaceClient`/`TuiController`/协议/审批/C7 **不动**（纯视图层）。
- 退役方式（对齐后）：按 Stage 2f 的做法删 Ink 视图与依赖，保留回归清单与本文件的 DONE 证据。

## 3. 下一步（建议顺序）

1. ~~切片 B：mentions + 输入历史 + Markdown~~（已完成，见下）。
2. ~~切片 C：多行 composer + 光标运动 + 外部编辑器~~（已完成 C2 多行；vim 见 §9）。
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

## 8. 切片 C2（2026-09-16）：textarea 单文本真源（多行完成）

- **底座**：composer 由原生单行 `<input>` 改为 opentui **`<textarea>`**（原生多行编辑、光标、词移动），视图只保留 **overlay/提交/模态** 的键归属。
- **单一文本真源**：文本以 textarea（`plainText`）为准，视图用**微任务**同步镜像给 overlay（同步读会**滞后一键**并导致 overlay 失同步）；历史召回/补全/编辑器回填统一走 `editBuffer.setText(...)` + **`setCursorByOffset(len)`**（`setText` 会把光标留在行首，否则下一次击键变成前置插入、backspace 失效）。
- **Enter 单一归属**：`onSubmit` 提交（Enter 绑定为 `submit`，`ctrl+j` 为 `newline`）；**agents 面板是唯一例外**（`agentsPanelRef` 抑制 textarea 提交，改由 resolver 执行会话切换），且 textarea 始终聚焦（面板选中时仍可打字）。
- **overlay 只拥有自己的键**：palette 仅 `↑/↓/Tab/Enter`、mention 仅 `Tab` —— **可打印键一律穿透**。这修掉了 `/exit` 陷阱：此前 overlay 吞字符 → `/stat` 只进 `/` → Enter 执行默认项 `/exit`（干净退出，被误读为渲染崩溃）。
- **deviation（诚实记录，已更正）**：textarea 有内容时 **Tab 被其自身消费**（空文本时才会到达 handler，这解释了 p3a 的 Tab 可用而 mention 的 Tab 不可用），无可用 keybinding 覆盖。因此 **mention 补全实际发生在提交时**（提交前自动补全打开的 `@token`）。此前文档"Tab 在空/短草稿下仍可用"的说法**不成立**（空草稿不会有打开的 mention），已撤回；证据信号 `MENTION_TAB_COMPLETED` 亦更名为 `MENTION_COMPLETED_ON_SUBMIT`（原名误导）。
- **复审发现并修复的 P1 回归**：textarea 的 `onSubmit` 与 resolver 的 palette Enter **双触发** → 命令执行两次（`/status` 出现两次 + 一条 `unknown command: /stat`）。修法：`overlayOwnsEnterRef`（palette/selector/approval 打开时抑制 textarea 提交）；不变式脚本新增 **`COMMAND_RAN_EXACTLY_ONCE`**。
- **后续会话定位的根因（HISTORY/MENTION 长期为红）**：`overlayOwnsEnterRef` 用了 `selector !== undefined`，而 `pendingSelector` 关闭时是 **null** → 判定恒真 → textarea `onSubmit` **永远早退**，**根本没有可用提交路径**（无历史条目→无会话→无文件→无 mentions）。修为 `!== null` 后整网转绿。同 `viewkeys.ts` 已记录的 null/undefined 陷阱。
- **产品级修复**：`controller.workspaceFiles()` 曾缓存**空文件列表** → 一次过早抓取即可让整个会话的 `@` mentions 失效；改为**只缓存非空结果**。视图侧亦改为「每次打开的 mention 只抓一次」（原先按 query 依赖会 cancel 上一次抓取）。
- **多行显示（2026-09-17 用可读行帧工具实测更正）**：此前称 `<text>` 会折叠内嵌换行，**实测不成立** —— 提交两行草稿后，`line1`/`line2` 在 transcript 落在**不同行**（行 02/03），composer 亦然（行 36/37）。该「显示缺口」条目已撤回。
- **证据**：`pty_fullscreen_composer_invariant.py`（/stat → 面板 → Enter 执行 `/status` → **进程存活**）连续 2 次 `INVARIANT_OK: True`；`parity_a` 四项、`parity_b` 四项（`HISTORY_PREVIOUS`/`MENTION_COMPLETED_ON_SUBMIT`（信号由 `MENTION_TAB_COMPLETED` 更名）/`MARKDOWN_RENDER_PATH_OK`/`SLICE_B_ALL`）、`parity_c` `EDITOR_ROUNDTRIP`、`p3a` `RESUMED`/`TYPABLE`、多会话 `PROVEN_CROSS_SESSION_SWITCH` 全 True；单测 **158 + 19**。
- **未做**：**vim 模态层**（下一个独立切片 #11）；多行滚动/高度自适应；textarea 的 paste/undo 语义专项验证。
- **已知限制（复审记录）**：① palette/mention 以 `input.length` 当光标 → 仅在**文末**触发（多行草稿中间输入 `@` 不补全）；② 空工作区时（不缓存空结果）Ink 路径会**每击键**发一次 `client.files()` GET（轻微、待优化）；③ `setCursorByOffset(value.length)` 用 UTF-16 长度对原生 offset，**非 ASCII（中文）草稿可能有光标偏移**（未构造出复现，仅提示）。

## 9. 切片 D（2026-09-17）：vim 模态层（#11 完成）

- **纯模块 `src/opentui/vim.ts`**：`resolveVimKey(name, pendingOp)`（映射对齐 Ink：`h/j/k/l`、`0/$`、`w/b/e`、`x`、`i/a/A/I`、`d/c` + `dd/dw/d$`、Enter 提交、Esc 清 pending）+ `applyVimAction(state, action)`（复用 `composer.ts` 原语；`c` 操作符后回到 insert）+ `offsetFromCursor`（逻辑光标 → offset，越界 clamp）。单测 `test/opentui-vim.test.ts`（bypass-detecting）。
- **视图/路由**：新增 `vim` 键层（在 resolver 中**优先级最高**，仅当 `controller.vimMode && !vimInsert`）。normal 模式下 **textarea 失焦**（字母因此不会被插入，全部由该层处理）；插入态按 **Esc** → 进入 normal（除非正在 streaming，此时 Esc 仍归冻结全局层做纠正）；`i/a/A/I` → 回到 insert 并重新聚焦。
- **证据**：`scripts/pty_fullscreen_vim.py`（`/vim` → insert 打 "hello" → Esc → `0` → `x` → normal 下 Enter）连续 2 次 `VIM_NORMAL_EDIT_SUBMITTED: True`（提交窗口内为 `ello`，且不含 `hello`；断言只看**提交窗口**，因为更早的帧本来就含 insert 期的 "hello" 回显）。
- **回归网（同批全绿）**：composer 不变式（含 `COMMAND_RAN_EXACTLY_ONCE`）、`parity_a`、`parity_b`（`SLICE_B_ALL`）、`parity_c`、`p3a`、多会话；单测 **162 + 19**。
- **教训（第 3 次同类陷阱）**：`vimNormal` 一度写成 `selector === undefined`，而 `pendingSelector` 关闭时是 **null** → vim 层永不激活（"0"/"x" 被当普通文本插入）。同一个 null/undefined 陷阱在本会话已出现三次（selector 层、`overlayOwnsEnterRef`、`vimNormal`）——**新增涉及 `pendingSelector` 的判断必须用 `=== null`/真值**。
- **仍未做**：`ctrl+r` 历史搜索、彩色语法高亮、主题配色、首页面板、多行**显示**（`<text>` 折叠换行）、多行滚动/高度自适应。

## 10. 可读行帧工具（2026-09-17）

`scripts/frame_reader.py`：把 pty 原始字节重建成**真实屏幕**（`ESC[r;cH` 定位 + SGR 颜色/加粗 + 文本/CR/LF/擦除 + UTF-8 宽字符），提供 `text_rows()`/`row_text(i)`/`spans(i)`/`token_style(token)`。用途：行结构断言（多行是否真分行）、颜色断言（#16/#17：同一 token 在不同主题下 SGR 应不同）、可视化检查（`--demo`；`--self-test` 自检 0 失败）。

实测结论：① 提交两行草稿后 transcript 的 `line1`/`line2` 分属不同行 → 多行显示正常；② opentui 自带默认调色（placeholder `fg=(102,102,102)`），`THEMES` 需显式覆盖才生效。

## 11. 切片 E（2026-09-17）：主题真正生效（#17 DONE）

- **纯模块** `src/opentui/theme-colors.ts`：`INK_HEX` 映射 + `hexFor()` + `viewTheme(name)`（把 `src/theme.ts` 的 Ink 颜色名解析为具体 hex；opentui 对 hex 解析可靠）。单测 `test/opentui-theme-colors.test.ts`（断言每个 token 都是 hex，且 `default`/`mono`/`ansi` 之间确实可区分——否则 `/theme` 只改名字）。
- **接线**：顶栏（`accent`）、footer（`footer`）、transcript 按角色（`user`/`assistant`/`system`/工具三态/`notice`）、审批卡边框（`approvalBorder`）、composer 边框（`border`）、markdown 文本（`assistant`）+ `SyntaxStyle` 主题化作用域。
- **证据**：`scripts/pty_theme_check.py`（基于 `frame_reader`）——同一 token 的 SGR 在 `/theme mono` 前后不同：连续 2 次 `THEME_APPLIED: True`（footer `ASK`：default 灰 → mono 白）。整网回归同批全绿（不变式/parity_a/b/vim/p3a/多会话）。
- **诚实边界**：① header token（`noem`）在该抓帧中未被工具定位到（`None`），故断言只覆盖 footer；② #16 的作用域颜色**已注册但未验证**（需要含代码块的回复）。

### 11.1 #16 实测结论（2026-09-17，未生效）

- 为验证给 hermetic stub 的回复加了 fenced python 代码块（`dev_daemon.py`，仅测试夹具）。
- 用 `frame_reader` 断言：代码块**确实渲染**（`FENCED_CODE_RENDERED: True`，26 个代码 token 可见），
  但 **`CODE_COLOURED: False`** —— 所有 token 的 fg 都是默认 `(255,255,255)`。
- 结论：`SyntaxStyle.registerStyle("keyword"/"string"/"comment"/"function")` **没有被 markdown 渲染器应用**。
  下一步需查 opentui 高亮器期望的 **scope 词表/样式形状**（core 里出现过 `comment`/`function`/`string`/`string.special.url`
  等名字，但显然还需正确的注册形状或 `SyntaxStyle.fromStyles(...)` 用法）。
- 保留 `scripts/pty_highlight_check.py` 作为**诚实复现器**：修好前它 exit 1，修好后应打印 `CODE_COLOURED: True`。
