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
| 3 | 顶栏 + footer（tokens/cost/events） | ✓ | ✓ | **DONE（此前为假 DONE，见 §13）** | 两个 `<text>` 在 flex 列里高度算成 0：顶栏**从未渲染**（被 transcript 边框覆盖），footer 压在输入框下边框上。§13 加 `height:1` + 中间行 `flexShrink:1` 后两者各占一行；`pty_theme_check.py` 现在同时覆盖 header 与 footer（`THEME_KEYS_CHANGED: ['header','footer']`）。cost 恒 UNKNOWN（诚实）|
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
| 16 | 代码语法高亮（彩色） | ✓ | ✓ | **DONE** | 见 §12：内置 tree-sitter 语法只有 {js,ts,markdown,zig}，```python 无 parser → 无高亮可着色；改由我们自己算区间经 `CodeRenderable.onHighlight` 注入。证据：`scripts/highlight_render_check.ts`（无头、含反向对照）+ `scripts/pty_highlight_check.py`（`CODE_DISTINCT_COLOURS: 4`、`HIGHLIGHT_OK: True`）|
| 17 | 主题真正生效（颜色） | ✓ | ✓ | **DONE** | `theme-colors.ts` 把 `THEMES` 的 Ink 颜色名解析为 hex，并接到 transcript（按角色）、审批卡、顶栏、footer、composer 边框；pty `THEME_APPLIED` 断言 footer 的 SGR 随 `/theme mono` 变化 |
| 18 | 首页/欢迎面板 | ✓ | ✓ | **DONE** | 见 §13：内容模型抽到 `src/home.ts`（Ink 与全屏共用），面板 `src/opentui/home-panel.tsx`；首帧证据 `scripts/pty_home_frame_check.py`（`HOME_PANEL_CHECK: PASS`）|
| 19 | `/status`、`/cost`、todo 面板 | ✓ | ✓ | DONE | 面板消息已渲染（`line()` 处理 `message.panel`） |

## 2. 结论

- 切片 A/B 关闭 #7/#8/#10/#13/#15，#11 vim、#12 多行由切片 D/C2 关闭，#17 由切片 E 关闭，#16 由切片 F 关闭，#18 由切片 G 关闭（并顺带把 #3 的假 DONE 修正为真 DONE）；**退役 Ink 仍缺 #14（ctrl+r 历史搜索）与多行显示/滚动**。
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

**2026-09-17 修正（见 §12.5）**：该工具原先不认 256 色 `38;5;N`（并把其中的 `N` 误当独立 ANSI 码，报出**完全错误**的颜色），且跳过空格写入（残留上一帧字形 → `find_row` 假阴性）。两者都会伪造证据，已修 + 加自检用例。

## 11. 切片 E（2026-09-17）：主题真正生效（#17 DONE）

- **纯模块** `src/opentui/theme-colors.ts`：`INK_HEX` 映射 + `hexFor()` + `viewTheme(name)`（把 `src/theme.ts` 的 Ink 颜色名解析为具体 hex；opentui 对 hex 解析可靠）。单测 `test/opentui-theme-colors.test.ts`（断言每个 token 都是 hex，且 `default`/`mono`/`ansi` 之间确实可区分——否则 `/theme` 只改名字）。
- **接线**：顶栏（`accent`）、footer（`footer`）、transcript 按角色（`user`/`assistant`/`system`/工具三态/`notice`）、审批卡边框（`approvalBorder`）、composer 边框（`border`）、markdown 文本（`assistant`）+ `SyntaxStyle` 主题化作用域。
- **证据**：`scripts/pty_theme_check.py`（基于 `frame_reader`）——同一 token 的 SGR 在 `/theme mono` 前后不同：连续 2 次 `THEME_APPLIED: True`（footer `ASK`：default 灰 → mono 白）。整网回归同批全绿（不变式/parity_a/b/vim/p3a/多会话）。
- **诚实边界**：① header token（`noem`）在该抓帧中未被工具定位到（`None`），故断言只覆盖 footer；② #16 的作用域颜色**已注册但未验证**（需要含代码块的回复）。

### 11.1 #16 实测结论（2026-09-17，**已被 §12 推翻并修正**）

- 为验证给 hermetic stub 的回复加了 fenced python 代码块（`dev_daemon.py`，仅测试夹具）。
- 用 `frame_reader` 断言：代码块**确实渲染**（`FENCED_CODE_RENDERED: True`），
  但 **`CODE_COLOURED: False`** —— 所有 token 的 fg 都是默认 `(255,255,255)`。
- **当时的归因（错）**：`SyntaxStyle.registerStyle(...)` 没有被 markdown 渲染器应用，下一步去查 scope 词表/注册形状。
- 保留 `scripts/pty_highlight_check.py` 作为复现器。**保留本节是为了记录错误归因**：真正的原因是"没有高亮可着色"（语法缺失），不是"作用域没生效"；见 §12。

## 12. 切片 F（2026-09-17）：代码语法高亮（#16 DONE）

### 12.1 修正后的根因（实测，推翻 §11.1 的归因）

- `MarkdownRenderable` 创建代码块时**已经**传了 `treeSitterClient`；`CodeRenderable` 更是在构造里就
  `options.treeSitterClient ?? getTreeSitterClient()` **兜底**，而该 client 工作正常（`isInitialized(): true`）。
  所以"没有 client / client 从未被调用"不成立。
- 真正的缺口是**语法覆盖**：`@opentui/core` 内置的默认 parser 只有
  `{javascript, typescript, markdown, markdown_inline, zig}`（wasm + `highlights.scm` 随包，离线可用）。
  ` ```python ` 因此解析到一个**没有 parser 的 filetype**，client 直接回
  `"No parser available for filetype python"` → `highlights = []` → 没有任何区间可着色 → 全白。
  **作用域注册从来不是问题**：`treeSitterToTextChunks` 的解析是 `getStyle(group)` → 失败再退到
  `getStyle(group.split(".")[0])`，注册 `keyword`/`string`/… 形状是对的，只是没东西可套。
- 判别实验（`spike/tree-sitter-coverage.ts`，可复跑）：`PARSERS PRESENT: typescript, javascript,
  javascriptreact, typescriptreact, markdown, markdown_inline, zig` / `PARSERS ABSENT: python, rust, go,
  bash, json, sql, yaml, ruby, c, cpp, java, html, css`；`highlightOnce(fixture,"python")` → `highlights=null`
  + warning，`highlightOnce(fixture,"typescript")` → **47 条**（同一 client）。

### 12.2 选型：不逐个 vendor 语法，复用 Ink 路径已经在用的高亮器

- 方案 A（给 python 补一个 tree-sitter wasm + query）只能一个语言一个语言地补（agent 会吐 rust/go/sql/yaml/bash…），
  且要往仓库里放二进制资源。
- 采用方案 B：`src/highlight.ts`（Ink 路径）背后的 **highlight.js 本机已有 191 种语言**。
  自己算出 `[start, end, scope]` 区间，经 opentui **受支持的** `CodeRenderable.onHighlight` 钩子注入：
  - `onHighlight` 在 `highlights.length >= 0` 时**总会被调用**（即使 tree-sitter 结果为空）；
  - 返回非空区间即走 `treeSitterToTextChunks`，由 `SyntaxStyle` 把 scope 名解析成颜色；
  - 有 tree-sitter 结果时（js/ts/markdown/zig）保留原生结果，无语法时用我们的。
- 兼容性同一性：与 Ink 路径**同一个高亮引擎**，这正是 parity 的目标语义。

### 12.3 实现

- `src/opentui/code-highlight.ts`（纯模块）：`fenceLanguage()`（把 `py`/`ts`/`sh`/`yml` 归一到规范名）、
  `codeHighlightRanges()`（走 highlight.js token 树取区间，未知语言/解析失败一律 `[]`，fail-soft）、
  `highlightStyleTable()`（highlight.js token 类 + tree-sitter capture 名两套词表 → 主题 token，含 `default`）、
  `codeBlockRenderNode()`（`<markdown renderNode>` 钩子；**必须**把它调过的 `context.defaultRender()` 原样返回，
  否则 markdown 渲染器会销毁这个默认 renderable、代码块整个消失）。
- `src/opentui/app.tsx`：`SyntaxStyle` 改为注册整张作用域表；`<markdown>` 接 `renderNode`（模块级常量，身份稳定）。
- `highlight.js` 提升为显式依赖（此前仅经 `cli-highlight` 传递）。
- 未映射的 scope（如 `emphasis`）刻意留空 → 落到 `default`（`theme.assistant`），不硬凑颜色。

### 12.4 证据

- **无头**（`scripts/highlight_render_check.ts`，`bun run`，因 OpenTUI 原生渲染器无 node FFI）：用 opentui 自带
  `createTestRenderer` 直接读**渲染器单元格缓冲**，断言精确的 scope→颜色映射：
  `def`/`return` → `#11a8cd`(accent)、`"hello "` → `#0dbc79`(toolDone)、`greet(...)` → `#e5e510`(toolPending)、
  注释 → `#808080`(notice)、未映射的 `+ name` → 默认色；并逐行断言代码块文本**未被着色破坏**。
  带**反向对照**：同一文档**不接** `renderNode` 时 python 块必须**无颜色** —— 否则该检查无法证伪。
- **PTY 端到端**（`scripts/pty_highlight_check.py`）：`CODE_TOKEN_COUNT: 14`、`CODE_DISTINCT_COLOURS: 4`
  `[(0,175,135),(0,175,215),(128,128,128),(215,215,0)]`、`FENCED_CODE_RENDERED: True`、`HIGHLIGHT_OK: True`（exit 0）。
- 单测 `test/opentui-code-highlight.test.ts`（5 条）：别名归一、作用域表（含 `default`、`comment` 为 dim、
  `keyword` 与 `title` 不同色）、三种主题下颜色确实变化、python 区间命中 `def`/`return`/`"hello "`/注释/`greet`、
  未知语言与空语言 fail-soft。全量 **171 + 19 = 190 pass**。
- 颜色编码说明：终端报 256 色，所以线上到的是**托盘索引**（keyword→38、string→36、title→184、comment→8），
  不是主题 hex；断言因此用托盘 RGB。

### 12.5 顺带修好的证据工具缺陷（`frame_reader.py`）

排查中发现两个会**伪造证据**的缺陷，已修 + 加自检：

1. **只认真彩 `38;2;r;g;b`，不认 256 色 `38;5;N`** —— 更糟的是它会把 `ESC[38;5;36m` 里的 `36` 当**独立 ANSI 码**，
   于是托盘 36（青绿）被报成 ANSI 36（`(17,168,205)` 青色）。本轮就一度据此误判 `"hello "` 被染成了 keyword 色。
   现按真实 xterm 托盘查表，并加自检：`38;5;36` 必须得到 `PALETTE_256[36]`，且**不得**等于 `(17,168,205)`。
2. **空格字符被跳过**（`byte > b" "`）—— 空格不清除上一帧残留字形，于是文本行里留着上一帧的边框字符。
   后果是 `find_row("def ")` 在侧栏有内容（重绘更多）时**假阴性**（`FENCED_CODE_RENDERED: False`），
   同一检查的结果会随无关的仓库脏度变化。现空格按真实终端语义写入单元格，并加自检。

## 13. 切片 G（2026-09-17）：首页/欢迎面板（#18 DONE）+ 顶栏/页脚版式缺陷（#3）

### 13.1 缺口（实测）

首帧取证（无输入，40×120）显示 transcript **整片空白**：`ensureSession` 只在 `runTurn` 里被调用
（lazy），所以首帧 `messages` 为空 —— 与 Ink 的 `showHome = finalized.length === 0 && active.length === 0`
等价，即首页面板**可达且会一直留到第一轮**，不是一闪而过。Ink 有 `HomeView` 而全屏什么都没有。

### 13.2 顺带发现的真实缺陷：顶栏从未渲染、页脚压在输入框边框上

同一个首帧里，行 00 直接是 transcript 边框：**顶栏（`◆ noem v…`）根本没出现**，
而 footer 与 message 框的下边框**画在同一行**。用 46 行的更高终端复测，顶栏依旧缺失 →
不是被裁掉。根因：**flex 列里同级 `<text>` 的高度被算成 0**（同列 `flexGrow:1` 的兄弟节点因此多拿到 2 行）。
证据链：给顶栏加 `style={{height:1}}` 后它立刻出现在行 00、其余整体下移一行；footer 同样如此。

修法（3 处）：顶栏 `<text style={{height:1}}>`、footer `<text style={{height:1}}>`、
中间行 `<box flexGrow:1 flexShrink:1>`（yoga 默认 `flexShrink:0`，不给中间行收缩权就会溢出 1 行）。
修完后 40 行与 42 行终端都各就各位。

**这使 #3「顶栏 + footer」此前的 DONE 是假的**；现已修正为真 DONE，并且
`pty_theme_check.py` 的 header 定位从 `None` 变成了实测值
（`default: (0,175,215)` → `mono: (255,255,255)`，`THEME_KEYS_CHANGED: ['header','footer']`）——
切片 E 记的"诚实边界①：header 未被工具定位到"因此**自动关闭**。

### 13.3 实现

- `src/home.ts`（新建，**不依赖 ink 也不依赖 opentui**）：`shortenPath` 从 `HomeView.tsx` 迁入并共用
  （Ink 侧改为 re-export，`test/homeview.test.tsx` 零改动仍绿）；`homeFacts`/`homeFieldRows`/`homeTipRows`/
  `homePanel(facts, narrow)`/`shouldShowHome(finalizedCount, activeCount)`。内容模型与渲染器解耦，
  这样退役 Ink 不会把内容一起带走。
- `src/opentui/home-panel.tsx`（新建）：把行渲染成带主题色的 `<span>`（`dim`/`bold` 走 `createTextAttributes`），
  每行显式 `height:1`；宽版用 `borderStyle="rounded"` 对齐 Ink 的 `borderStyle="round"`，
  窄版（<60 列）与 Ink 一致为**无边框三行**。
- `src/opentui/app.tsx`：`showHome` 接入 transcript；`provider` 传 `null` 与 Ink 完全一致
  （Ink 的 `App` 也从未收到 `provider`，两边都走 `openai-compatible · <model>` 回退，属两边同源的既有缺口，非回退）。

### 13.4 证据

- **单测** `test/opentui-home.test.tsx`（7 条）：判定语义；provider 三种取值；五个字段等宽对齐与取值；
  无分支回退 + 超长路径仍被限宽；窄版就是 Ink 那三行（无卡片、无 `Quick start`）；
  **防漂移**——把 opentui 面板每一行与 Ink `HomeView` 实际渲染帧（剥掉边框后）逐行精确比对；
  **deviation 断言**——Ink 的提示写着 `shift+tab switches mode`，而全仓 `shift+tab` **只出现在这句提示里**
  （Ink 的 `useInput`、`keys.ts`、`viewkeys.ts` 都没有），模式其实由 `/mode` 设置；面板改为
  `/mode switches permission mode`，并断言它**不含** `shift+tab`、**含** `/mode`。
  全量 **171 + 26 = 197 pass**。
- **PTY** `scripts/pty_home_frame_check.py`：首帧 `HOME_PANEL_FIRST_FRAME: True`、五个字段全在、
  `Quick start` 在、`HEADER_RENDERED: True`、`FOOTER_NOT_OVER_BORDER: True`；
  一轮后 `HOME_PANEL_GONE_AFTER_TURN: True`；`HOME_PANEL_CHECK: PASS`。
- **整网回归**（布局改动影响面大，全跑）：composer 不变式、parity_a/b、p2、vim、p3a、多会话、smoke、
  theme、highlight 全部与上一批一致；`pty_highlight_check.py` 现在报 5 种不同颜色（多出的是滚动条灰）。

### 13.5 诚实边界

- 面板在**很矮**的终端上会被 `stickyScroll`/`stickyStart="bottom"` 顶掉上半部分（Ink 同样会溢出），
  未做重排。
- 宽版卡片的内边距用 `paddingLeft:1`（Ink 是 `paddingX:2`），因为外面还有 transcript 的 1 列内边距，
  合计与 Ink 一致；左右差异未逐列比对。
- `provider` 字段两边都恒为 `null` → 永远显示 `openai-compatible`；修它需要给两个视图都传真实
  `provider_id`（`SurfaceProviderStatus` 里有该字段），属**既有产品缺口**，本轮未动。
- Ink 侧那句假提示**未改**（Ink 即将退役），仅在新面板上不再复制，并在单测里钉住。

