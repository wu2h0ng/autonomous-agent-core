# 终端线能力对位地图（2026-09-18）

- **状态**：`DOCS_ONLY / MEASURED_ON_MAIN / RECOMMEND_ONLY / NO_IMPLEMENTATION_AUTHORITY`
- **日期**：2026-09-18
- **基线**：`origin/main = 03ac66b563e689fd3c87d38eed2aae400989f6d5`（PR #69 的 merge commit）；
  本文件全部行号与命令输出均为该 HEAD 上的实测。worktree：`.worktrees/wt-parity`，分支 `docs/terminal-parity-map-20260918`。
- **对象（我方）**：`main` 上的终端线——`apps/cli-ts`（唯一支持的交互 TUI，`noem`）+ `apps/api_server` + `apps/runtime_daemon` + `packages/os_core` + `packages/contracts`。
- **对象（他方）**：Claude Code、Codex CLI、Hermes、OpenClaw、Pi。
- **本文件做什么**：把"终端线离主流还有多远"从一个叙事问题变成一个**有证据、可复核、按操作者能力域分组**的地图；并显式记录**我们有意不追的东西**。
- **本文件不做什么，也不授权什么**：不主张 parity、不主张超越、不主张自主（不使用 `Autonomy(S,E,O,V,T)`）、不主张产品就绪或市场验证；不授权任何实现、契约、协议、内核、合并、发布、付费或 ADR 开写；不修改 `docs/CURRENT_STATE.yaml`（协调者独占），需要它的改动以 §10 的精确文本给出。
- **上游**：`docs/product/TERMINAL-AGENT-CLI-BENCHMARK-2026-07-26.md`（形态与证据上限）、
  `docs/product/AGENT-PRODUCT-DESIGN-SOURCE-STUDY-2026-07-10.md`（跨产品设计原则）、
  根仓 `docs/agent-cli/TERMINAL-VS-MAINSTREAM-GAP-2026-09-13.md`（差距刷新）、
  `docs/product/TUI-PARITY-CHECKLIST-2026-09-16.md`（Ink→全屏 19 项对齐）、
  根仓 `docs/agent-cli/TERMINAL-DISTRIBUTION-STATUS-2026-09-18.md`（分发现状，**已过期，见 §1.4**）。
- **同批姊妹件**：`docs/reviews/MERGE-CONVERGENCE-PLAN-2026-09-18.md`（PR #84，收敛）、
  `docs/reviews/PR-CODE-REVIEW-2026-09-18.md`（PR #81，四份代码 PR 复核）、
  `docs/reviews/STATE-FRESHNESS-AUDIT-2026-09-18.md`（PR #71，状态文档新鲜度）。三份均**未合并**。

## 0. 三条口径（读本文前必须先接受）

1. **`main` 才是产品。** 今天有 **21** 个 PR 对着 `03ac66b5` 开放，**一个都没合并**
   （实测：`gh pr list --state open --limit 100 --json number --jq 'length'` → `21`）。
   其中若干条实现了显著能力。本文把 **`main` 上的状态当作"今天会发货的产品"**，
   把未合并的分支单列 §4，标为 **implemented on an unmerged branch**。
   > 口径差异记录：任务包写"十八个 PR 开放"。实测 21 个。数量在 2026-09-18 当天增长过
   > （`MERGE-CONVERGENCE-PLAN` §6 记录了同日新增 #85/#86），所以两个数字都可能是当时的真值；
   > 本文以**实测的 21** 为准，并注明它会过期。
2. **模型能力今天是 `NOT_MET`，不是"好"或"差"。** 本机没有任何 live provider 凭据
   （实测：`AGENT_OS_PROVIDER_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GEMINI_API_KEY` 全未设置），
   本次任务也未运行任何 live provider 调用。因此**"这个 agent 写代码有多强"这一项没有任何测量**，
   本文任何地方都不得被读成对编码能力的评价。
3. **`DESIGN_ONLY` 不是"差不多做了"。** 今天明确处于 `DESIGN_ONLY` 的有：
   **MCP 为 `PARK`**（全仓只有一处非授权信封解析器，§2.6）、
   **subagents / fan-out 与 typed hooks 只有 Gating Card**（在未合并的 PR #70 上）、
   **checkpoint / rewind 完全不存在**（在未合并的 PR #72 上只有设计件）。
   本文不把它们计为"已具备"。

## 1. 方法与证据纪律

### 1.1 我方证据：测量，不回忆

每一条"我们有"都必须附以下之一：

- `file:line`（在该 HEAD 上亲自读到）；
- 一条**我实际跑过**的命令 + 原始输出；
- 一个具名测试；
- 一个已记录的、有评审身份的 gate。

状态词按仓库既有口径**逐词区分**，不合并：
`specified / implemented / tested / integrated / verified / released`。
本文额外区分两个容易混淆的点：

- **`implemented` 是指在 `main` 上可执行**，不是"分支上有代码"；
- **`verified` 只指我这次在该 HEAD 上实跑过并留下输出**，不指 CI 曾经绿过。

### 1.2 他方证据：有来源，或者标明没有

对每一个归给他方的能力，本文给 **URL + 抓取日期（2026-09-18）**。三类来源，强度不同：

| 标记 | 含义 |
|---|---|
| `[vendor-doc]` | 官方文档页面。描述的是**厂商主张/设计意图**，不证明实现质量 |
| `[source]` | 在**固定 commit** 上读到的源码（更强：是当时真实存在的形状，但仍不证明可靠性） |
| `[unverified]` | 无法取到来源；本文要么删掉要么显式标为未核实 |

**本次的一处工具限制必须明说**：环境里的 Web 搜索配额已用尽（HTTP 403），
所以**没有做独立第三方核查**，也没有做跨来源交叉验证。本文的他方事实全部来自
官方文档或官方源码，按 §1.2 的强度分级阅读。

### 1.3 不写"自信的对位叙事"

本文不在无法取证的地方写对位结论。凡是"他们大概也有……"这类句子，一律删除或移入 §7 未核实清单。

### 1.4 一处必须修正的引用（根仓分发件的基线已过期）

根仓 `docs/agent-cli/TERMINAL-DISTRIBUTION-STATUS-2026-09-18.md` 自报基线是 `8ab29119`。
**实测它已经落后**（该结论由同日的 `STATE-FRESHNESS-AUDIT` 提出，本文复核其方向）：

```console
$ git rev-list --count 8ab29119..HEAD     # HEAD = 03ac66b5
45
$ grep -n 'npm run' .github/workflows/ci.yml
332:        run: npm run test:ci
```

即：该文件 §4 记 `cli-ts` job "只有 3 个 `run:` 步骤"，在 `03ac66b5` 上是 **5 个**
（`:310` `bun install --frozen-lockfile`、`:332` `npm run test:ci`、`:337` `npm run typecheck`、
`:365` `pip install …`、`:372` `bash scripts/install_smoke.sh`），
且该基线落后 **45** 个提交（另有文档记 32 —— 那是**另一个 HEAD** 上的读数，
`CURRENT_STATE.yaml` 的同一 pin 也承认自己的数值是"在 HEAD 203b8862 上"测的；
本文用自己实测的 45）。
因此本文**只引用它 §1 的路径分类与 §2 的 `private:true`/registry 结论**（那两条在 HEAD 上仍然成立，见 §2.9），
不引用它的步骤数、tarball 数字与"CI 缺 Python 运行时"的结论。
该文件在**另一个 git 仓库**里，本次只读审计，未修改、未做任何 git 操作。

### 1.5 会话摘要（本文自己的测量）

```console
$ PYTHONPATH=packages/contracts/src:packages/os_core/src:. uv run --extra product-test \
    python -m pytest tests/product -q
2753 passed, 1 skipped in 222.87s (0:03:42)        # exit 0

$ uv run --extra product-test ruff check apps packages/contracts/src packages/os_core/src tests/product
All checks passed!

$ cd apps/cli-ts && bun install --frozen-lockfile && npm run test:ci && npm run typecheck
59 packages installed
=== ran 34 test files in 40 s  /  === all test files passed      # 34 files / 235 tests / 235 pass / 0 fail
typecheck exit 0
```

**这意味着 `CURRENT_STATE.yaml` 里"23 个既存失败"的表述在 `03ac66b5` 上已不成立**
（该纠正方向与 `STATE-FRESHNESS-AUDIT` 一致）。本文不修改该文件，建议文本见 §10。

## 2. 对位地图（按操作者可见能力域）

每域四段：**他们有（含来源）/ 我们有（含证据）/ 缺口 / 是否在范围内**。
"是否在范围内"只描述**已记录的立场**（GC/ADR/benchmark 的明文），不表达本文的偏好。

### 2.1 起步与安装

**他们有**

- Claude Code：一条命令安装，跑 `claude` 即用；`/init` 生成起点、`/doctor` 做安装自检 `[vendor-doc]`
  （<https://code.claude.com/docs/en/how-claude-code-works>，2026-09-18）。
- Codex CLI：安装通道 ≥5 条——macOS/Linux 的 `curl … | sh`、Windows 的 PowerShell 一行、
  `npm install -g @openai/codex`、`brew install --cask codex`、GitHub Release 平台二进制；
  另有 IDE 扩展、`codex app` 桌面端、Codex Web 云端 `[source]`
  （<https://raw.githubusercontent.com/openai/codex/main/README.md>，2026-09-18）。
- Pi：一个 npm 包 + `pi` 即用；`pi install/update` 管包与自更新 `[vendor-doc]`
  （<https://pi.dev/docs/latest/usage>，2026-09-18）。
- OpenClaw：`openclaw setup` / `onboard` / `configure`，并有 `doctor`、`completion`、`dashboard` `[vendor-doc]`
  （<https://docs.openclaw.ai/cli>，2026-09-18）。
- Hermes：`hermes setup --portal` 之后 `hermes chat` `[vendor-doc]`
  （<https://hermes-agent.nousresearch.com/docs/user-guide/cli>，2026-09-18）。

**我们有**（`main` 实测）

- 入口统一在 `apps/cli-ts/src/cli.tsx`：交互 TUI（默认）+ 子命令 `doctor`(`:85`)、`daemon`(`:96`)、
  `provider`(`:129`)、`session`(`:138`)、`--version`、`--help`、无头 `-p`；视图是**动态 import**，
  因此子命令在没有原生 FFI 的运行时上也能跑（`cli.tsx:1-9` 的模块注释）。
- `bin` 有 4 个别名：`noem` / `agentos` / `agent-os` / `agent-os-ts`（`apps/cli-ts/package.json:15-20`）。
- `doctor` 是只读 4 项自检（descriptor → reachable → auth → protocol），
  exit 0 全过 / 1 任一失败（`apps/cli-ts/src/doctor.ts`）。
- 本机安装路径今天成立的两条：源码（`bun install --frozen-lockfile` + `npm run build`）与
  本地 tarball → `npm install -g <tgz>`。
- **证据等级**：`implemented` + `tested`（`npm run test:ci` 34 文件 235 例全绿，我实跑）。

**缺口**

1. **registry 通道今天不可能**：`apps/cli-ts/package.json:4` 为 `"private": true`；包不在 registry 上。
   这是**发布授权**问题，不是工程问题。
2. **装完之后需要用户机器上有 Bun**：`bin` 目标 `dist/cli.js` 的 shebang 是 `#!/usr/bin/env bun`，
   且 `package.json:7-9` 声明的是 `engines.bun >= 1.4.0`（**没有** `engines.node`）。
3. **没有 `completion`、没有 `dashboard`、没有向导**（对比 OpenClaw/Hermes）。
4. 单文件二进制可构建可运行，但**只有宿主平台**（`apps/cli-ts/scripts/compile.ts` 无 `--target`），
   且**只含客户端**——daemon 仍是 Python。

**是否在范围内**：**在范围内**，但被 founder gate 挡住（发布/付费/自更新属独立 gate）。
注意根仓分发件关于"主路线是 npm 全局（Node ≥20）"的记录已被 `55f8e3b8` 的 Bun 切换取代。

### 2.2 交互编辑与 composer

**他们有**

- Claude Code：终端内的会话循环，`Esc` 立即停止并取消正在跑的工具调用，
  **输入纠正+回车可以在不停工具的情况下发给模型** `[vendor-doc]`（同上 URL）。
- Hermes：多行编辑、slash 自动补全、历史、`Ctrl+G` 外部编辑器、`Ctrl+S` 草稿暂存（可叠多份）、
  `!cmd` 直跑 shell（零 token）、粘贴多行时压成单行预览 `[vendor-doc]`。
- Pi：`@` 模糊找文件、Tab 路径补全、`Shift+Enter` 多行、`Ctrl+V` 贴图、`Ctrl+G` 外部编辑器、
  `!cmd` / `!!cmd`、实验性全屏 TUI（鼠标滚动、Kitty 内联图）`[vendor-doc]`。
- Codex CLI：`/vim`、`/keymap`、`/theme` 等 slash 命令 `[source]`
  （`codex-rs/tui/src/slash_command.rs`，commit `7498521d`，2026-09-18）。

**我们有**（`main` 实测）

- composer 是 opentui `<textarea>`（原生多行/光标/词移动），单文本真源 + 微任务镜像到浮层。
- vim 模态层：纯模块 `apps/cli-ts/src/opentui/vim.ts`（`h/j/k/l 0 $ w b e x i a A I d c dd dw d$`），
  单测 `test/opentui-vim.test.ts`。
- `Ctrl-G` 外部编辑器（`apps/cli-ts/src/editor.ts`）、`Ctrl-R` 反向历史搜索（复用 `InputHistory.search`）、
  ↑/↓ 历史（`src/history.ts`）、`@` mentions（`src/mentions.ts` + `controller.workspaceFiles()`）。
- Markdown 渲染 + **彩色代码高亮**（`src/opentui/code-highlight.ts`，走 highlight.js 区间经
  `CodeRenderable.onHighlight` 注入；内置 tree-sitter 只覆盖 `{js,ts,markdown,zig}`）。
- 主题真正生效（`src/opentui/theme-colors.ts`）、首页/欢迎面板（`src/home.ts` + `src/opentui/home-panel.tsx`）、
  命令面板 + 选择器浮层（`src/opentui/overlays.ts` / `viewkeys.ts`）。
- composer 高度随草稿自适应并**带闸**（`src/layout.ts` 的 `composerRows`，上限 12 行且不超过终端 1/3）。
- **证据等级**：`implemented` + `tested`（`npm run test:ci` 235 例全绿）。
  行为级 pty 证据在 `apps/cli-ts/scripts/` 下的 15 个 `pty_*.py` 脚本里——
  **但这些脚本会起 hermetic daemon，本次任务硬约束禁止起 daemon，所以我没有运行它们**（见 §7）。
  它们的结论以 `TUI-PARITY-CHECKLIST-2026-09-16.md` 的逐项记录为准（**转引，非本次实测**）。

**缺口**

1. **`!cmd` 直接跑 shell 我们没有**（我们只有 `workspace.shell`，走 permit/审批，且默认 allowlist 只有 pytest 系）。
   这是**有意的**差异（见 §5）。
2. 无 `Ctrl+S` 草稿栈、无粘贴压缩预览、无图片粘贴、无语音（Hermes 有）。
3. 无 `/keymap`、无状态栏字段排序（Codex 有 `/statusline`）。

**是否在范围内**：composer 主体**已闭合**（Ink 退役清单 19/19 DONE）。
`!cmd` 与贴图**不在当前范围内**（前者与 §5 的 authority 差异冲突，后者未立项）。

### 2.3 会话管理与历史

**他们有**

- Claude Code：会话以 JSONL 落 `~/.claude/projects/`，**由此支持 rewinding / resuming / forking**；
  `--continue` / `--resume` / `--fork-session` / `/branch`；`/resume` 选择器默认按当前 worktree 过滤，
  快捷键可扩大到其它 worktree 或项目 `[vendor-doc]`。
- Pi：`/resume` 选择器、`/new`、`/name`、`/session`、**`/tree` 跳到会话中任意一点继续**、
  `/fork`、`/clone`、`/compact`、`/export`（HTML/JSONL）、`/import`、`/share`；
  `-c/-r/--no-session/--name/--session/--fork`；会话存 `~/.pi/agent/sessions/` 按工作目录分组 `[vendor-doc]`。
- Hermes：`--continue` / `--resume <id|latest>` / `--resume "标题"`；恢复时显示"Previous Conversation"面板；
  `/title`、`hermes sessions list`；会话存 SQLite，含 lineage `[vendor-doc]`。
- OpenClaw：`sessions`、`resume`、`transcripts`、`audit`，另有多平台/节点会话面 `[vendor-doc]`。

**我们有**（`main` 实测）

- 内核侧只读会话列表端点（`GET /v1/surface/sessions`）+ 客户端 `/resume` 消费
  （`apps/cli-ts/src/controller.ts:472` `/resume` 分支、`:1019` `adoptSnapshot`）。
- `--resume <id>` 启动参数（`apps/cli-ts/src/cli.tsx:56` 解析，`:172-173` 转成 `/resume <id>` 提交）。
- `/export` 导出（`controller.ts:510`）。
- 会话/回合状态是**durable 事件流**（append-only + 序列 CAS），
  回合边界是 `SESSION_TURN_STARTED` / `SESSION_TURN_COMPLETED`。
- 只读 agents 树 + 跨会话切换（`src/opentui/agent-tree-source.ts`，`--no-agents` 可关）；
  切换守卫是回合状态谓词（拒绝在 busy/awaiting_approval/streaming/stalled/closed 时切换）。
- **证据等级**：`implemented` + `tested`；跨会话切换的 e2e 在
  `scripts/pty_fullscreen_p3a_multisession.py`（**未由本次运行**）。

**缺口**

1. **无 fork / branch / clone**（三家都有）。
2. **无会话搜索选择器**（我们只有单会话 `--resume <id>` 与列表）。
3. **无 `/compact`、无 `/context` 可视化**（Claude Code / Pi / Hermes 都有）。
4. **无 checkpoint / rewind**——今天在任何操作者可及路径上都不存在（见 §3）。
5. 多会话切换的**选中项**只有只读单元覆盖，pty 只能证明同会话（历史上的一次假 NOT_MET 已归因于 fixture bug）。

**是否在范围内**：**在范围内但未开工**。#2/#3 是产品体验增量；#1 与 #4 需要内核工作
（`/compact` 涉及已冻结的裁剪语义 —— 见 `MERGE-CONVERGENCE-PLAN` 记录的 S4 同名事件冲突）。
**主张 parity 前必须先做这些**，因为它们不是观感，是能力。

### 2.4 中断与恢复

**他们有**

- Claude Code：`Esc` 立即停止并取消正在跑的工具调用；**再按一次 `Esc` 回退文件改动**
  （编辑前对文件内容做快照；checkpoint 只覆盖文件改动，符号链接/硬链接会被跳过，
  对远端系统的动作**不能** checkpoint，只能用权限模式控制）`[vendor-doc]`。
- Pi：`Enter` 排队引导消息、`Alt+Enter` 排队后续消息、`Escape` 中止并把排队的消息还给编辑器、
  `Alt+Up` 取回队列 `[vendor-doc]`。
- Hermes：`Ctrl+C` 中断（2 秒内两次强制退出）；`busy_input_mode` 三选一
  （`interrupt` 默认 / `queue` / `steer`）；`/stop` 取消回合**及其前台工作**；
  前台长命令**移到后台而非杀掉**；`Ctrl+Z` 挂起到 shell `[vendor-doc]`。
- OpenClaw：`sessions`/`triage`、审批取消语义（"关闭或取消该回合即失效其待决权限，
  迟到的批准不能重启它"）`[vendor-doc]`。

**我们有**（`main` 实测）

- `Esc` / `Ctrl-C` 在 streaming 时发**纠正**（C7 correction），走 `keys.ts:6-17` 的冻结全局映射；
  Esc **永不** approve/reject（idle / `awaiting_approval` 时是 no-op，`keys.ts:34-42`）。
- 停滞（stall）是 typed 状态，且**区分两种停滞原因**：
  `no durable resolution within <n>ms`（daemon 还没报结果）vs
  `durable event drain failed: <message> - the cursor stays at <n>`
  （`controller.ts` 的 `stallMs`/`stalled` 逻辑，`:1199-1219`）。
- 效果未知（UNKNOWN）有硬门：Run 停 `PAUSED`、`resume` 被拒（`UNKNOWN_REQUIRES_REVIEW`）、
  只派发一次、不自动重发（`_action_outcome.py` 的 insert-only reservation/outcome）。
- **证据等级**：`implemented` + `tested`（`tests/product` 2753 通过里含相关断言）。

**缺口（这是本域最重的一条）**

1. **单会话"停掉"在 `main` 上不生效。** `POST …/pause` 路由存在，但对 surface 会话会因
   Run 停在 `QUEUED` 而 `QUEUED` 的允许集不含 `PAUSED` 而抛 `InvalidTransitionError`。
   在 `main` 上，`packages/os_core/src/agent_os_core/task_service.py` 的转移表**没有**这条边。
   > 这是**未合并分支已修**的能力：PR #77 打开 `QUEUED → PAUSED` 并加中途优雅停机点。
2. **无排队/引导（steer/queue）**：中途输入只有"纠正"这一条语义，没有"排到本回合之后"。
3. **无 checkpoint/回退文件**：Pi 的 `/tree`、Claude Code 的 `Esc Esc` 都没有对应物。
4. 我们**没有** `Ctrl+Z` 挂起语义、没有"把前台命令移到后台"。

**是否在范围内**：#1 **在范围内且已实现（未合并）**（PR #77）；#2 **在范围内且未实现**；
#3 是 §3 的 `DESIGN_ONLY`；#4 不在范围内。

### 2.5 权限与审批

**他们有**

- Claude Code：权限模式四挡（`Auto` 分类器后台判定风险 / `Manual` / `Accept edits` / `Plan`），
  `Shift+Tab` 循环；`settings.json` 里可放行具体命令；权限由 Claude Code 而非 prompt 强制 `[vendor-doc]`。
- Codex CLI：approval 策略 `untrusted | on-request（默认）| granular | never`；
  `granular` 是**按类别的逐项开关**（`sandbox_approval` / `rules` / `skill_approval` /
  `request_permissions` / `mcp_elicitations`）；sandbox 策略
  `danger-full-access | read-only{network_access} | external-sandbox | workspace-write{writable_roots, network_access}`；
  另有 exec policy 规则（`execpolicy`）与 admin 可控的 `allow_managed_hooks_only` `[source]`
  （`codex-rs/protocol/src/protocol.rs:986-1112`，commit `7498521d`，2026-09-18）。
- OpenClaw：审批是**三层叠加**——policy + allowlist + （可选）人工批准；
  `tools.exec.mode ∈ deny|allowlist|ask|auto|full`；`askFallback`；
  allowlist 条目支持 `argPattern`（ECMAScript argv 正则）；
  **可执行文件身份绑定**（解析后真实路径；可写可执行文件再加内容哈希），
  改动即拒；批准与执行之间重校验；durable grant 有生命周期与撤销面；
  MCP 工具 grant 按 agent+server+tool 绑定 `[vendor-doc]`（<https://docs.openclaw.ai/tools/exec-approvals>，2026-09-18）。
- Hermes：`HERMES_YOLO_MODE` / `--yolo` / `/yolo` 一键自动批准，状态栏常驻警告 `[vendor-doc]`。
- Pi：**故意不做**权限弹窗（见 §5 的引用原文）`[vendor-doc]`。

**我们有**（`main` 实测）

- 权限模式是 `PermissionMode = Literal["ASK", "ACCEPT_READ_ONLY", "ACCEPT_IN_WORKSPACE"]`
  （`packages/contracts/src/agent_os_contracts/surface.py:17`）。
- 交互审批卡：digest 绑定 + diff + `[HUMAN APPROVAL REQUIRED]` + 键位行；
  卡边框取主题 token（`apps/cli-ts/src/opentui/app.tsx:707`）。
- 拒绝只减权、永不允许、永不自动批准 tier-3：`apply_deny_rules`
  （`packages/os_core/src/agent_os_core/permission_gate.py:86-116`，docstring 原文
  "There is no rule that can ALLOW, auto-approve…"），裁决落 `DENY_BY_RULE`（`:39`）。
- tier≥3 必须真人 `ApprovalDecision`；审批票据绑定 action digest；
  permit 只在 `PolicyKernel.permit` 铸造、5 分钟过期、派发前校验。
- OS 级隔离**可选**：macOS Seatbelt（`execution_isolation ∈ {trusted_workspace_only(默认), sandboxed}`，
  `domain_packs/developer_agent/workspace_capability.py:233,296-321`），sandboxed 时不可用即 fail-closed。
- **证据等级**：`implemented` + `tested` + `integrated`（在 `main` 上）；
  Seatbelt 的"真实阻断"证据是 macOS-only 的 12 例 `tests/product/test_os_sandbox.py`（本次未单跑，但在 §1.5 的整包里）。

**缺口**

1. **权限 DENY 对操作者不可见**（`main` 上）：`DENY_BY_RULE` 不产 `ACTION_PROPOSED`，
   于是终端既不画卡也无提示；headless 仍报 `success / is_error false / EXIT=0`。
   > **未合并分支已修**（PR #75：卡 + headless exit 4），但 PR #81 的独立复核给了
   > **REQUEST CHANGES**：恢复历史会话时**历史 DENY 会被算进当前回合**，
   > 干净回合被误报成 exit 4（已复现）。**所以这条在合并前仍必须先修那个阻断项。**
2. **审批卡深度不足**：无 risk tier 徽标、无"本会话/该前缀"档、无现场解释、无评论
   （Codex 有 y/a/p/d 与 `/permissions`；Claude Code 有 Tab 评论）。
3. **无 OS 级隔离的默认值**：默认是 `trusted_workspace_only`（有意的产品边界）。
4. **无 YOLO/一键自动批准**（❌ 有意不提供，见 §5）。
5. **无 `argPattern` 式参数级 allowlist**：我们的 shell 是**精确匹配 allowlist**
   （`domain_packs/developer_agent/shell_denial.py`，默认只有 pytest 系），理由在模块 docstring 里
   写明"字符串级危险命令分类曾被证伪为 brittle"。

**是否在范围内**：**在范围内**。这是产品差异化的所在（authority spine），
所以补的是**可见性与真相**（#1/#2），不是放宽权限。

### 2.6 可扩展性

**他们有**

- Claude Code：skills、MCP、**hooks**、subagents（+ Claude in Chrome）。
  hooks 的事件词汇非常大，且钩子可以是 shell 命令 / HTTP 端点 / MCP 工具调用 / LLM 提示 / subagent；
  `PreToolUse` 可以**阻断**；还有 `PermissionRequest`、`PermissionDenied`（可让模型重试）、
  `SubagentStart/Stop`、`PreCompact`、`Elicitation`（MCP 请求用户输入）等 `[vendor-doc]`
  （<https://code.claude.com/docs/en/hooks>，2026-09-18）。
- Codex CLI：`/skills`、`/hooks`、`/mcp`、`/plugins`、`/agents`、`/subagents` 等命令存在；
  hook 配置可由 admin 用 `requirements.toml` 的 `allow_managed_hooks_only` 收口 `[source]`。
- OpenClaw：插件市场、skills workshop、`mcp serve`、webhooks、cron/automations、
  `worker`/`node`/`fleet`，以及"skill CLI 自动放行" `[vendor-doc]`。
- Hermes：原生插件 + 可移植 Agent Plugins v1、skills 自动注册为 slash 命令、stdio MCP 条目 `[vendor-doc]`。
- Pi：扩展/技能/提示模板/主题/包；**但明确不做内置 MCP、不做 sub-agents** `[vendor-doc]`（见 §5）。

**我们有**（`main` 实测）

```console
$ rg -il mcp apps packages/contracts/src packages/os_core/src domain_packs
packages/os_core/src/agent_os_core/protocol_ingress.py
packages/contracts/src/agent_os_contracts/protocol_ingress.py
$ rg -n -i "mcp" packages/os_core/src/agent_os_core/protocol_ingress.py
46:        elif raw.get("protocol") == "MCP":
47:            protocol = "MCP"
$ rg -n -i "subagent|fan-out|rewind|typed hook" apps packages/contracts/src packages/os_core/src domain_packs
packages/os_core/src/agent_os_core/srl_execution.py:210:    Hardening (subagent N6/N7): ...
apps/cli-ts/src/opentui/agent-tree-source.ts:34:/** Bound the fan-out: one link request per mandate, capped. */
```

- **MCP：`PARK`。** 全仓只有一处**非授权信封解析分支**与契约里两个 `Literal` 成员
  （`protocol_ingress.py:46-47`；`protocol_ingress.py:111,137`）。没有 client/server/传输/工具注册。
- **typed hooks：不存在。** `hook` 的 14 处命中全是**内核内部代码 seam**（provider 传输钩子
  `_request_body`/`_transport_headers`/`_parse_completion`/`_refusal_text`，`provider.py:492-510`）
  或视图层的 `onHighlight`，**没有操作者安装面**。
- **subagents / fan-out：不存在。** 没有"创建会话/驱动回合"的能力；
  `CHAT_CAPABILITY_IDS` 是硬编码 7 项（`agent_loop.py:67-75`）。
- **checkpoint / rewind：`rewind` 零命中；`apps/` 内 `checkpoint` 零命中。**
- **AGENTS.md / CLAUDE.md 分层发现：有**（这是唯一真的扩展面）：
  `packages/os_core/src/agent_os_core/agent_context.py:187` `discover_agents_markdown_layers`，
  根层在前、嵌套按排序目录，剪掉 `.git` 等重目录，有层数/字符/目录/条目上界，每层带 sha256；
  同目录优先 `AGENTS.md`，其次 `CLAUDE.md`（`:161-163`）。
- **操作者本地配置**：`~/.agent-os/provider.json`（0600，仓外，**不写 key**）、
  `AGENTS_OS_PROVIDER_LOG`（opt-in JSONL 尝试日志）。

**缺口**：MCP / hooks / subagents / skills / 插件生态 **全部为零**。
这三项（MCP、subagents/fan-out、typed hooks）今天**只有 Gating Card**（在未合并的 PR #70 上），
状态 `DESIGN_ONLY / DOCS_ONLY / AWAITING_CTO_GATE / NO_IMPLEMENTATION_AUTHORITY`；
checkpoint/rewind 也只有 GC（未合并的 PR #72）。

**是否在范围内**：**MCP 在范围内但被有意 PARK**（要先用我们自己的 eval 证明"扩展工具面"是
**可归因瓶颈**，见 §5）；**typed hooks 在范围内、建议第一阶段只做只读 observer**（founder 权重 ~10%）；
**subagents/fan-out 的 A 形态（操作者并行管理多个独立会话）在范围内，B 形态（父派生并扇出）
必须另立 ADR + C6/C7 保持证明**；**checkpoint/rewind 在范围内，但 GC 主张只做"追加式 + 前向 restore"，
不做时间旅行**。以上全部**未获 CTO gate**。

### 2.7 可观测性与成本

**他们有**

- Pi：footer 显示 cwd、会话名、token/缓存用量、**cost**、context 占用、当前模型 `[vendor-doc]`。
- Hermes：状态栏显示模型、context 进度条（颜色分级）、**估算成本**、压缩次数、后台任务数、
  时长、标题、YOLO 警告；`/usage` 给分类明细 `[vendor-doc]`。
- OpenClaw：`status --usage` 与 Control UI 展示 provider 配额，
  数据来自 provider usage 端点（覆盖 Anthropic/Gemini/Copilot/MiniMax/OpenAI Codex/…）`[vendor-doc]`。
- Claude Code：`/context` 看空间占用、`/doctor` 诊断、debug log 与 `CLAUDE_CODE_DEBUG_LOG_LEVEL=verbose` `[vendor-doc]`。

**我们有**（`main` 实测）

- `/status` 与 `/cost` 面板；**token 精确、cost 恒 `UNKNOWN`（无定价源）**，
  原文 `cost: UNKNOWN (no pricing source)`（`controller.ts:269,554`）。
- durable 任务事件审计 + `/task` + `/export`。
- **opt-in 机器可读 provider 尝试日志**：`AGENT_OS_PROVIDER_LOG` 命名一个 JSONL 文件；
  每次模型调用尝试一条记录（latency/tokens/outcome/failure code），
  **不含 prompt 与 completion 文本**，0600、append-only、且写失败不得破坏回合。
- `/doctor` 的 launcher 解析与告警：`resolveDaemonCandidates`（`apps/cli-ts/src/daemon.ts:147`）
  返回一条**有序候选链** `AGENT_OS_RUNTIME_CMD(override) → checkout → PATH → uv run`，
  `resolveDaemonLaunch`（`:190`）取首选；某个候选在就绪前就死掉时**交接给下一个候选**
  （而不是把整段 deadline 等完），并把交接与**有界、已脱敏的 launcher stderr 尾巴**报出来
  （`:15-16,119,124,295-301`）；`doctor` 用 `launcherNotes`（`doctor.ts:75-108`）报告 launcher
  来源，且这些是 advisory note，不改变 `ok`/exit code。
- `workspace.search` 的诚实性：`truncated_reason ∈ null|scan_cap|result_cap|output_cap`
  + `scanned_files` + `unexamined_files`，且 `_truncate_json` 会另带 `summary`，
  使"`matches: []` 不等于不存在"这件事对**模型**可见：
  工具描述在 `provider.py:1282-1288`（"`matches: []` with `truncated_reason: \"scan_cap\"`
  means the tree …"），上限常量在
  `domain_packs/developer_agent/workspace_capability.py:1252`（`_SEARCH_MAX_SCANNED_FILES = 1000`），
  描述表本体在 `provider.py:1261`（`_TOOL_DESCRIPTIONS`）。
- **证据等级**：`implemented` + `tested`（含 `tests/product/test_workspace_search_scan_cap.py`、
  `test_workspace_tool_descriptions.py`、`test_provider_failure_visibility.py`）。

**缺口**

1. **没有 metrics 导出、没有 trace 导出**（都是未合并分支上的能力：PR #73 的 `/metrics` 面板、
   PR #86 的 `/trace`）。
2. **没有客户端侧限流**。需要把两件事分开：
   **有**——provider 端 `429` 的**分类与重试**（`ProviderErrorCode.RATE_LIMITED`，
   `packages/contracts/src/agent_os_contracts/provider.py:53`；`provider.py:970,985,1002,1012`
   的失败分类与有界退避，以及 `Retry-After` 两种 RFC 9110 形式的采纳）；
   **没有**——任何客户端请求速率/并发上限，所以"客户端限流"这一项在 `main` 上是 `NOT_MET`。
   > 未合并分支已实现：PR #73（真实令牌桶 + 信号量 + 跨调用 429 冷却 + `/metrics`）。
3. **没有金额成本**（无定价源；这是有意的诚实，不是缺陷——见 §5）。
4. **没有 provider 配额/用量的对位**（OpenClaw 有）。
5. 客户端 token 计数是**活动会话累计**，非活动会话只靠只读列表轮询。

**是否在范围内**：**在范围内且是 founder 自己给的最大权重（ops ~35%）**。
#1 已实现未合并；#2 是**有意的**（GC-SUBAGENTS D6 记录"不引入定价源"）。

### 2.8 无头与脚本化

**他们有**

- Pi：`-p` 打印模式、`--mode json`（JSON Lines 全事件）、`--mode rpc`（stdin/stdout RPC）、
  `--export <in> [out]`；打印模式还能读管道 stdin `[vendor-doc]`。
- Claude Code：`-p` 与 `--output-format stream-json` 一类无头形态；CI/CD 场景 `[vendor-doc]`
  （`headless.ts:14-16` 的注释记录我们刻意对齐了这一形状）。
- OpenClaw：`--json` 保留 stdout 给单个 JSON 文档、失败时非零退出并输出
  `{"ok":false,"error":{"type":"cli_error","message":…}}` 信封 `[vendor-doc]`。
- Codex CLI：`codex exec`（非交互）`[source]`。

**我们有**（`main` 实测）

- `noem -p <prompt> --output-format text|json|stream-json`
  （`apps/cli-ts/src/headless.ts:29`），`stream-json` 是 NDJSON（init…result），
  注释明说是对齐 `claude -p --output-format stream-json` 的形状。
- **冻结的退出码表**：`OK=0 / ERROR=1 / APPROVAL_REQUIRED=2 / NOT_COMPLETED=3`
  （`headless.ts:22-27`），由 `test/headless.test.ts` 钉住，并在
  `apps/cli-ts/scripts/install_smoke.sh` 的 hop 7 里对真实工件断言。
- 关闭管道（`| head -3`）按主流行为静默 exit 0，而不是抛 EPIPE（`cli.tsx:18-23`）。
- **证据等级**：`implemented` + `tested`（235 例含 headless 组）。

**缺口**

1. **没有 RPC 模式**（Pi 有 `--mode rpc`）。
2. **失败工具运行在 `--output-format json` 下仍报 success**（**读码结论，未做运行期复现**）：
   `headless.ts:104-140` 的退出判定只看 `controller.status`、
   `controller.lastStopReason !== "completed"` 与 `controller.lastError`，
   **从不看工具结果**；因此"回合完成但某次 `workspace.run_tests` 退出码非 0"会落到
   `result("success", …, "completed")` + `exit 0`。修它是跨 Python/TS 的协作改动，未做。
3. **拒绝的退出码今天不可达**（`denied:out_of_allowlist` 只会走 exit 3）——
   PR #75 引入 exit 4，但 PR #81 的复核指出该分支在真实路径上只有 stub 能触发。
4. **无 JSON 失败信封**（OpenClaw 的形状我们没对齐）。
5. **参数校验是点状而不是通用的**：`--output-format` 的非法值**会**报错并 `exitCode = 1`
   （`apps/cli-ts/src/cli.tsx:149-153`）；但**不存在通用的未知 flag 拒绝**——
   参数解析用 `flagValue(args, …)` 逐个查找（`cli.tsx:31-37`），
   未被识别的 flag 不会产生错误，缺值的 `-p` 也会继续走到挂载 TUI 的路径。
   （这条与 `CURRENT_STATE` 的 P1 记录同向；我读到了校验点的**存在**与通用拒绝的**缺失**，
   未逐 flag 构造运行期复现。）

**是否在范围内**：**在范围内**。#2/#5 是**可信度**问题（脚本会把失败读成成功），优先级应高于观感。

### 2.9 分发与升级

**他们有**

- Codex CLI：5 条安装通道 + IDE + 桌面 app + 云端 + 平台二进制矩阵 `[source]`。
- Pi：`pi update [self|pi|--all|--extensions|--models]`——**自更新是一等命令** `[vendor-doc]`。
- Claude Code：终端 / 桌面 / IDE 扩展 / claude.ai/code / Remote Control / Slack / CI-CD，多界面 `[vendor-doc]`。
- OpenClaw：`update` / `migrate` / `backup` / `restore` / 签名与安全面 `[vendor-doc]`。
- Hermes：`hermes plugins update`、Portal 安装路径 `[vendor-doc]`。

**我们有**（`main` 实测）

- 三条真实通道：源码、本地 tarball → `npm install -g`、`bun build --compile` 单文件（宿主平台）。
- CI 有一个 **install smoke**（8 跳：deps → build → artifact → version → pack → start → answer → stop），
  在 CI 的 `cli-ts` job 里执行（`.github/workflows/ci.yml:372`），
  走的是**用户真实路径**（`bun dist/cli.js`），不是从源码驱动；
  用 hermetic daemon + `--no-daemon` + 回复逐字节等于 `dev_daemon.TURN1_TEXT`，
  使"误连到真实 provider"不可能通过。
- **证据等级**：`implemented` + `tested`（CI 步骤 + `test/` 断言）。
  **我没有运行 `scripts/install_smoke.sh` / `scripts/e2e.sh`**（会起 daemon，被硬约束禁止）。

**缺口**

1. **registry 发布 `NOT_MET`**（`private: true`；包不在 registry 上）。
2. **自更新完全没有**：`rg -i "self.?update|selfupdate|auto.?update" apps/cli-ts` 零命中；
   `--help` 里没有 update/upgrade 子命令。这是 founder gate（"后续独立 GC"），
   且**未合并分支 PR #85 已实现**（`noem self-update`，显式、校验完整性、可回滚）。
3. **需要两个工具链**：Bun（跑 cli）+ uv/Python（跑 daemon）。"一条命令装完就能跑"今天不成立。
4. **无 Windows**、无 Linux 沙箱、无签名/公证、无平台二进制矩阵。
5. **CI 只跑 source 路径**：15 个 `pty_*.py` 与 `e2e.sh` **不在 CI**。

**是否在范围内**：**在范围内**，但发布/付费/自更新是 **founder gate**；
平台矩阵与签名是工程侧可推进的部分（需要先定"单二进制是否硬需求"）。

## 3. `DESIGN_ONLY` 清单（明确不存在，不得计为"已具备"）

| 能力 | 今天的状态 | 唯一载体 | 位置 |
|---|---|---|---|
| MCP（client / server / 传输 / 工具注册） | **`PARK`**；全仓一处非授权信封解析分支 | GC | PR #70（未合并） |
| subagents / fan-out | **不存在**；`CHAT_CAPABILITY_IDS` 无相关能力 | GC-P3 + AB + 新 GC | `main` 有 P3a 只读树；GC 在 PR #70（未合并） |
| typed hooks | **不存在**；只有内核内部代码 seam | GC | PR #70（未合并） |
| checkpoint / rewind | **不存在**；`rewind` 零命中，`apps/` 内 `checkpoint` 零命中 | GC | PR #72（未合并） |
| skills / 插件市场 | **不存在** | — | ADR-0055：外部 Skill 必须先编译为 typed capability |
| 会话 fork / branch | **不存在** | — | — |
| `/compact` / `/context` | **不存在** | — | 见 `MERGE-CONVERGENCE-PLAN` §3.2 的选项 A/B/C |
| 单会话停止（`main`） | **不生效**（`QUEUED→PAUSED` 边不存在） | PR #77（未合并） | — |
| 权限 DENY 可见（`main`） | **不可见**（无卡、headless 报 success） | PR #75（未合并，且被复核 REQUEST CHANGES） | — |
| client 限流 / `/metrics` | **不存在** | PR #73（未合并） | — |
| trace 导出 | **不存在** | PR #86（未合并） | — |
| 自更新 | **不存在** | PR #85（未合并） | — |
| 终端编码 eval 语料（`coding_v1`） | **不在 `main`**（见 §4） | PR #74（未合并） | `main` 只有 `l1_basic.json` / `e3_live_basic.json` |

## 4. 未合并分支上**已实现**的能力（in-flight）

截至 2026-09-18，`gh pr list --state open --limit 100` 返回 **21** 个 PR，全部以 `03ac66b5` 为基线，
**一个都没合并**。以下是"已实现但不在 `main`"的部分（合并前不得计入产品）：

| PR | 分支 | 内容 | 复核状态 |
|---|---|---|---|
| #69 | `tui/parity-f-code-highlight` | **已合并**（`03ac66b5`，本文基线） | — |
| #73 | `codex/ops-client-ratelimit-20260918` | 客户端限流 + 跨调用 429 冷却 + provider metrics | 独立复核 APPROVE WITH FINDINGS（本地拒绝污染延迟分布，已复现） |
| #74 | `codex/terminal-coding-eval-20260918` | TERMINAL-CODING-EVAL-1：真实终端编码语料 + 离线 qualification | — |
| #75 | `codex/deny-visibility-20260918` | 权限 DENY 可见（卡 + headless exit 4） | **REQUEST CHANGES**（历史 DENY 污染当前回合，已复现） |
| #76 | `codex/contract-surface-1-2-20260918` | surface 协议 1.1 → 1.2（附加字段收口） | APPROVE WITH FINDINGS（反向偏斜硬失败未写入诚实边界） |
| #77 | `codex/surface-session-stop-20260918` | 单会话停止（`QUEUED→PAUSED` + 中途优雅停机） | APPROVE WITH FINDINGS（均为文档/精度问题） |
| #79 | `codex/approval-event-observability-20260918` | 交互确认记为 durable approval | 已被 #74 合入（`73c87afa`） |
| #80 | `codex/mcp-precondition-20260918` | MCP 前置门测量（**判定 (c) 今天无法回答**） | — |
| #83 | `codex/tui-stop-key-20260918` | TUI 停止键（Ctrl-X → 真实 pause）+ DENY 卡 pty 证据 | 栈在 #75+#77 之上 |
| #85 | `codex/self-update-20260918` | `noem self-update`（显式、校验、可回滚） | 栈在 #73 之上 |
| #86 | `codex/trace-export-20260918` | governed turn 的 typed trace（契约 + 投影 + 路由 + `/trace`） | 栈在 #73 之上 |
| #87 | `codex/tui-resume-20260918` | `/resume` 真正 resume 一个 PAUSED 会话 | 栈在 #83 之上 |
| #82 | `codex/product-eval-triage-20260918` | 冻结 provider 环境作用域 + `tests/product_eval` 分诊 | — |
| #70/#72/#71/#81/#84/#78 | docs-only | 三份 GC / checkpoint GC / 状态审计 / 独立复核 / 收敛方案 / CURRENT_STATE 真值 | — |
| #47 / #63 / #3 | 旧线 | SPINE-1 donor 抽取 / textarea composer（已被 #64 取代）/ ADR-0039 | — |

**读法**：上表的每一行都**不是今天的产品**。#75 尤其要注意：它被写成"修好了 DENY 不可见"，
但独立复核复现了一个**反向谎报**（把没发生的拒绝说成发生了），合并前必须先修。

## 5. 我们**有意不追**的（含理由）

这一节和"缺口"同等重要。目标里写明了不追求超越、不追求范式级差异化，
所以只列缺口会把产品往 founder 已经排除的方向推。

### 5.1 治理权威脊，代价是摩擦（有意保留）

Hermes 有 `/yolo`、OpenClaw 有 `tools.exec.mode: full` + `askFallback: full` 的 YOLO 组合、
Codex 有 `never` approval + `danger-full-access`、Pi **故意不做权限弹窗**。
我们**不提供**任何"一次放行全部/绕过 tier-3"的形态。

理由（有记录的立场，不是我发明的）：`TERMINAL-AGENT-CLI-BENCHMARK-2026-07-26.md` §1 把
"provider output is proposal-only；每个有后果的动作都在 typed capability 契约、policy、精确动作 permit、
纠正 epoch 与 durable receipt 之后"写成**唯一的差异化**；§6 明确"不要在 project trust、
命令绑定与进程隔离明确之前暴露 Pi 式强大 shell 语义"。
代价诚实记录：**我们的交互更啰嗦，能做成的动作更少**，而这是**有意的**。

### 5.2 不做插件市场 / 不做"生态即质量"

`ADR-0055`：外部 Skill **不是内核对象**，必须先编译为 `CapabilitySpec` + Workflow/Procedure 候选 +
Knowledge 依赖 + Credential/Policy 要求。
`TERMINAL-AGENT-CLI-BENCHMARK` §6：**"不要把 plugins、MCP 或 sub-agents 当作 agent 质量的证明"**。
所以 OpenClaw 的 marketplace / Hermes 的 Agent Plugins v1 / Codex 的 plugins 我们**不追**，
直到有可测的任务瓶颈。

### 5.3 不做 MCP server（入站面），client 也要先过前置门

`GC-MCP-FORM-AND-BOUNDARY-2026-09-18.md`（PR #70）判定：
**Y（server）不做**，直到五条判据全部满足（其中"存在本仓之外的、真实的、非我们编写的消费者，
且已有次数级使用证据"今天**没有任何证据**）；
**Z 不推荐**；**X（client）先做边界与探针、继续 `PARK`**。
若 eval **无法**证明"扩展工具面"是可归因瓶颈，**那份否证本身就是不做 MCP 的依据**。

### 5.4 不让模型输出变成被执行的代码

`GC-TYPED-HOOKS-2026-09-18.md` §5：hook 安装来源**只允许** `~/.agent-os/hooks.json`，
**明确排除仓库内/工作区内**来源。理由可证伪：workspace 内容可被 agent 通过
`workspace.edit`/`apply_patch` 写入，若它能选择要执行的 hook，就等价于**把模型输出变成被执行的代码**。
同理 `§6.4`：hook API 上不存在 `exec`/`eval`/`subprocess` 语义，也没有可用执行器对象。
代价：我们失去了"仓库自带可执行扩展"这一主流能力。

### 5.5 不做渠道/网关广度、不做云端 agent、不做多租户

OpenClaw 有 gateway/channels/nodes/fleet、Hermes 有 Discord/Telegram/Slack 网关与 cron；
Claude Code 有 cloud/Remote Control；Codex 有 Codex Web。
`TERMINAL-AGENT-CLI-BENCHMARK` §6："**不要在终端编码任务可靠之前复制 OpenClaw 的渠道/网关广度**"。
本线是**本地、单操作者、终端优先**。

### 5.6 不伪造成本

cost 恒 `UNKNOWN`，不写 `estimated_cost_usd = 0`。`GC-SUBAGENTS-AND-FANOUT` D6 明确判为**不引入定价源**。
代价：Crush 一类有单价注册表的工具在这项上更好看；我们选择不伪零。

### 5.7 不做"时间旅行 rewind"

`GC-CHECKPOINT-REWIND-2026-09-18.md`（PR #72）的核心判断：
`D-A 回合游标 / D-B 任务序列 / D-C 工作区文件` 三者的"回去"可以在明确声明下成立，
但 **`D-D 外部效果`永远不能回退**（收据与 reservation 是 insert-only，`UNKNOWN` 是终局）。
因此本线主张做 **"追加式 checkpoint + 前向 restore"**，不做"状态回滚/时间旅行 rewind"；
给操作者的承诺必须写成可验伪的一句话（例如"restore 只回退被枚举的文件集合的 digest；
它不会、也不能撤销任何已 dispatch 的动作；未解 UNKNOWN 会阻止 restore"）。

### 5.8 不主张 parity，更不主张超越

本文全部内容都在 §6 的声明边界内。若某天要主张 parity，需要的是
`AGENT-PRODUCT-DESIGN-SOURCE-STUDY-2026-07-10.md` §10 那张表的**运行结果**
（Verified Success / Review Time / Recovery Rate / Duplicate-effect Rate …），
而不是本文这种逐项对位。

## 6. 声明分级（本文件自身）

`specified: 本文件` / `implemented: NO` / `tested: NO` / `integrated: NO` / `verified: NO` / `released: NO`。

本文件**未**新增任何实现、**未**运行任何 live provider 调用、**未**起任何 daemon、
**未**运行任何 pty 脚本、**未**运行 `scripts/e2e.sh` 或 `scripts/install_smoke.sh`、**未**读 `~/.agent-os/`、
**未**修改任何被测文件、**未**修改 `docs/CURRENT_STATE.yaml`。

## 7. 未核实清单（诚实列出）

**我方的未核实**

1. **模型编码能力**：无 provider 凭据，`NOT_MET`。任何"我们的 agent 写代码行不行"都没有测量。
2. **15 个 `pty_*.py` 的行为证据**：脚本存在（`ls apps/cli-ts/scripts/pty_*.py | wc -l` → 15），
   但它们会起 hermetic daemon，本次任务禁止起 daemon，**我一个都没跑**。
   因此 §2.2/§2.3/§2.4 里凡是只由 pty 脚本支撑的行为断言，都是**转引** `TUI-PARITY-CHECKLIST` 与
   `CURRENT_STATE` 的 live_pins，不是本次实测。
3. **`scripts/e2e.sh` / `scripts/install_smoke.sh`**：未运行（同上）。
4. **pyright**：未跑（耗时长且需要 clean baseline）。`CURRENT_STATE` 记"156 个既存错误"，未复核。
5. **真实 provider 相关的任何行为**（限流、429 冷却、原生流式的真实厂商端点）：
   开发记录明确写着"只在 hermetic stub 上验证过"。
6. **多会话并发资源上界**：`surface_runtime` 的锁表增长、内存、连接数**未测量**。
7. **`tests/product_eval`**：本次只跑 `tests/product`；`product_eval` 有既存的顺序依赖缺陷未修。

**他方的未核实 / 已丢弃**

1. **Codex CLI 的交互 UX 与非交互 `exec` 细节**：`developers.openai.com` 从本机返回 **HTTP 403**
   （`/codex/cli/`、`/codex/security` 均不可取），仓库内 `docs/sandbox.md`、`docs/slash_commands.md`、
   `docs/skills.md`、`docs/agents_md.md`、`docs/execpolicy.md` **全是跳转到该 403 站的占位**。
   所以本文对 Codex 只用了 README（安装通道）+ **固定 commit 源码里的枚举**。
   它的**审批交互、沙箱的 OS 机制、exec policy 语法**本文**不做断言**。
2. **Web 搜索不可用**（配额 HTTP 403）：**没有做独立第三方核查**，
   也没有对厂商主张做交叉验证。所有他方事实都是官方文档或官方源码。
3. **`docs.openclaw.ai/agent-loop` 抓取返回 "Redirecting"**（空壳），所以 OpenClaw 的 agent loop 形态
   本文不引用。
4. **厂商文档描述的是意图**：`[vendor-doc]` 级别一律不得被读成"该功能可靠/已达生产"。
   本文已按 §1.2 分级，但读者仍需自行承担这一层不确定性。
5. **Pi 的博客理由文（"For the full rationale, read the blog post"）未取**，
   所以"Pi 故意不做 MCP/sub-agents/权限弹窗"这条本文只引官方 usage 文档的原话。

## 8. 推荐（**仅为建议，不授权任何事**）

按"影响 × 今天就绪度"排序。每条都标出 **blocked on founder decision** 还是 **merely unbuilt**。

**R1（最高）——把已经做完且 CI 绿的 in-flight 能力真正发货。**
理由：本图的"我们有"一栏在 `main` 上比实际实现**明显更差**，
因为停止会话、DENY 可见、限流/指标、编码语料、自更新、trace 全都在未合并分支上。
一个不发货的产品无法被测量，也无法被使用，"离主流多远"这个问题就被**人为放大**了。
顺序见 `MERGE-CONVERGENCE-PLAN-2026-09-18.md`（PR #84，同样未合并）。
**注意**：#75 在被合并前必须先修 PR #81 复核复现的阻断项（历史 DENY 污染当前回合）。
**性质**：**blocked on founder decision**（合并是 founder gate，`AGENTS.md` §16）。

**R2——把终端线的编码 eval 变成可跑出数字的东西。**
理由：`product_evals/terminal_agent_eval` 在 `main` 上只有 `l1_basic.json`（2 任务）与
`e3_live_basic.json`（2 任务）；`coding_v1.json`（6 任务）与 `coding_harness` 都在 PR #74 上。
更重要的是：今天**没有任何 live arm 的观测**（无凭据 → `NOT_MET`），
而 MCP 的前置门、subagents 的 B 形态、checkpoint 的立项全部**都卡在这个测量**上。
不解决它，后面三个能力决定只能靠直觉做。
**性质**：**merely unbuilt**（需要一个 provider 凭据与预算决定，不是架构授权）。

**R3——收敛"操作者看到的真相"，这条比观感重要。**
理由：本图里最刺眼的不是缺功能，而是**已经发现且未修的谎报类缺陷**：
`main` 上权限 DENY 完全不可见而 headless 报 success（`DENY_BY_RULE` 不产 `ACTION_PROPOSED`）；
`--output-format json` 对失败的工具运行仍报 `success / exit 0`（读码结论，§2.8）；
`formatToolDetail` 实现且有测试但**没有任何视图调用点**
（`controller.ts:231-233` 的 NOTE 原文 "no view calls this yet — the Ctrl-O panel was never wired,
and the `/keys` card no longer advertises a binding for it"——即**帮助文本被改成不再宣称该键，
而不是把面板接上**），于是 `resultSummary` 这个唯一带 error_code/exit 的面板在交互面上不可达。
这些直接损害"可核对"这一核心价值，而且是**低成本**修复。
**性质**：**merely unbuilt**（其中 DENY 可见性已在 #75，需先修阻断项）。

**R4——决定 checkpoint/pause 共享地基的那个最小切片。**
理由：`GC-CHECKPOINT-REWIND` 的 D2 建议先做"回合级只读 checkpoint 投影 + 有权限的优雅中止"，
它自身不引入新授权，且是多会话/子代理（A 形态 §5 表格第 2 行"单独停掉一个"）的**先决条件**。
**性质**：**blocked on founder decision**（GC 的 D1/D2 未决）。

**R5——可扩展性按已写好的顺序推进，不要跳步。**
理由：hooks 的第一阶段（配置 + 只读 observer，返回值一律 `None`）是**类型层面**就够不到权威的，
风险最低；MCP 必须等 R2 的前置门有数字；subagents 的 A 形态只差治理与可观测收尾，
B 形态**必须另立 ADR + C6/C7 保持证明**。
**性质**：hooks / A 形态 **blocked on founder decision**（CTO gate 未开）；B 形态 **blocked on ADR**；
MCP **blocked on R2 的测量**。

**R6——分发面的两个可工程化部分。**
理由：平台矩阵（`compile.ts` 无 `--target`）、把 15 个 pty 脚本与 `e2e.sh` 纳入 CI、
以及"装完之后需要 Bun"这件事的明示，都是**不需要发布授权**的。
**性质**：工程侧可推进；registry 发布、自更新、付费 **blocked on founder decision**。

**明确不建议做的**（与 §5 一致）：为了"看起来对等"而加 YOLO 模式、
加 workspace 内可执行 hook、加 MCP server、伪造成本、或复制渠道/网关广度。

## 9. 复现命令清单（本节所有命令均于 2026-09-18 在 `03ac66b5` 上跑过）

```console
# 基线与工作树
git rev-parse HEAD                                            # 03ac66b563e689fd3c87d38eed2aae400989f6d5
git status --short                                            # （空）

# 我方：产品基门（本文件最重要的两个数字）
PYTHONPATH=packages/contracts/src:packages/os_core/src:. uv run --extra product-test \
  python -m pytest tests/product -q                           # 2753 passed, 1 skipped, exit 0
uv run --extra product-test ruff check apps packages/contracts/src packages/os_core/src tests/product
                                                              # All checks passed!
cd apps/cli-ts && bun install --frozen-lockfile && npm run test:ci && npm run typecheck
                                                              # 34 files / 235 tests / 235 pass / 0 fail / exit 0

# 我方：未实现能力的存在性证明
rg -il mcp apps packages/contracts/src packages/os_core/src domain_packs            # 2 (仅信封解析)
rg -n -i "rewind" apps packages/contracts/src packages/os_core/src domain_packs      # （无输出, exit 1）
rg -n -i "checkpoint" apps                                                          # （无输出, exit 1）
rg -n -i "self.?update|selfupdate|auto.?update" apps/cli-ts/src apps/cli-ts/test apps/cli-ts/scripts
                                                                                    # （无输出, exit 1）
rg -n "rate_limit|throttle" packages/os_core/src packages/contracts/src apps         # （无输出, exit 1）
rg -n -i "rate_limit" packages/os_core/src packages/contracts/src                   # 仅 RATE_LIMITED 失败码 5 处
                                                                                    # （provider.py:970,985,1002,1012;
                                                                                    #   contracts/provider.py:53）

# 我方：入口与契约
sed -n '15,30p' apps/cli-ts/package.json                      # bin: noem/agentos/agent-os/agent-os-ts
sed -n '22,29p' apps/cli-ts/src/headless.ts                   # OK0/ERROR1/APPROVAL_REQUIRED2/NOT_COMPLETED3
grep -n "PermissionMode = Literal" packages/contracts/src/agent_os_contracts/surface.py
rg -n -A9 "^CHAT_CAPABILITY_IDS" packages/os_core/src/agent_os_core/agent_loop.py

# 我方：CI 接线
grep -nE "run:|timeout-minutes" .github/workflows/ci.yml | head -20

# 我方：eval 语料（main 上只有两个 2 任务 manifest）
git ls-tree -r --name-only origin/main -- product_evals/terminal_agent_eval

# 我方：环境（确认无从测量模型能力）
for v in AGENT_OS_PROVIDER_KEY ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY; do
  [ -n "${!v}" ] && echo "$v SET" || echo "$v unset"; done   # 四个均 unset

# 他方：来源（2026-09-18）
#   https://code.claude.com/docs/en/how-claude-code-works
#   https://code.claude.com/docs/en/hooks
#   https://raw.githubusercontent.com/openai/codex/main/README.md
#   gh api repos/openai/codex/commits/main --jq .sha          # 7498521d288b9b3b96ffba4eedf089d8d6e06a84
#   gh api repos/openai/codex/contents/codex-rs/protocol/src/protocol.rs   # AskForApproval / SandboxPolicy
#   gh api repos/openai/codex/contents/codex-rs/tui/src/slash_command.rs   # slash command 枚举
#   https://hermes-agent.nousresearch.com/docs/user-guide/cli
#   https://docs.openclaw.ai/cli
#   https://docs.openclaw.ai/tools/exec-approvals
#   https://pi.dev/docs/latest/usage
```

## 10. 给协调者的 `docs/CURRENT_STATE.yaml` 建议文本（本文**不修改**该文件）

以下为**建议**，是否写入由协调者决定。措辞已按该文件的既有风格（双引号标量，内部引号已转义）。

字段 `live_pins` 下建议新增一个键：

```yaml
  terminal_parity_map_2026_09_18: "Terminal capability map produced 2026-09-18 on main 03ac66b5 (PR #69 merge): docs/product/TERMINAL-PARITY-MAP-2026-09-18.md. Status DOCS_ONLY / MEASURED_ON_MAIN / RECOMMEND_ONLY / NO_IMPLEMENTATION_AUTHORITY. Measured on main at that HEAD: tests/product 2753 passed / 1 skipped / exit 0 and ruff clean (the file's older \"23 pre-existing failures\" wording is stale); apps/cli-ts 34 test files / 235 tests / 235 pass / 0 fail, typecheck exit 0. 21 PRs are OPEN against 03ac66b5 and NONE is merged, so every capability on those branches (DENY visibility, single-session stop, client rate limit + /metrics, terminal coding eval corpus, self-update, /trace, TUI resume) is implemented on an unmerged branch and is NOT the product. DESIGN_ONLY and unchanged: MCP is PARK (only the non-authorizing envelope parser at protocol_ingress.py:46-47), subagents/fan-out and typed hooks exist only as Gating Cards on unmerged PR #70, and checkpoint/rewind does not exist (GC only, unmerged PR #72). The terminal line's model-capability number is NOT_MET: no live provider credential is present and no live call was made. This pin records a measurement; it authorizes no merge, release, publish or parity claim."
```

对该文件**既有字段**的两处建议（均已由同日 `STATE-FRESHNESS-AUDIT`（PR #71）提出，本文复核方向一致）：

1. pin `tui_ink_deleted_slice_k_2026_09_17` 的 "it is NOT in origin/main" 与
   "what is missing is the merge into main, not the push" 在 `03ac66b5` 上已不成立（PR #69 已合并）。
   建议改为指向 PR #69 的 merge receipt。
2. pin `remaining_work_map_and_review_boundary_2026_09_18` 末句
   "the terminal line's own coding eval is the missing piece" 需要收紧：
   **`main` 上已有** `product_evals/terminal_agent_eval`（含 `l1_basic.json` 2 任务与
   `e3_live_basic.json` 2 任务、`l1_harness`/`live_harness`/`product_executor`），
   缺的是**规模与 live arm 的数字**——`coding_v1.json`（6 任务）与 `coding_harness` 在 PR #74 上，
   而任何 live arm 因为无凭据恒为 `NOT_MET`。

**本文不主张**：不得据本文声称 parity、超越、自主、产品就绪或任何市场结论；
不得据本文声称任何未合并分支上的能力"已经可用"。
