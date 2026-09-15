# GC/CP-AB — TUI 迁移到全屏渲染器（2026-09-15）

- **状态**：`DECIDED_FULLSCREEN / AWAITING_RUNTIME_DECISION / NOT_IMPLEMENTED`
- **Founder 决策**：**迁移到全屏渲染器**（alt-screen，多面板/独立滚动/动效可达）。
- **基座**：`main`（cli-ts = Ink 单滚动，Stage 1/2f 收敛完成）。

## 1. 为什么（与现状对照）

- 现 cli-ts = **Ink + `<Static>`**（`apps/cli-ts/src/App.tsx:623`）：finalized 追加一次、动态区按行重写。**SSH 稳定已达标**，但 **Ink 无 alt-screen/无区域定位** → 无法做多面板、独立滚动、拖拽、平滑动效。
- 全屏（alt-screen + 光标寻址）是 OpenCode/Crush 那类多面板/动效的前提。

## 2. 实测证据（2026-09-15，本机）

| 渲染器 | 版本 | Node 可用 | 结论 |
|---|---|---|---|
| `@opentui/react` | 0.5.11 | ❌ `OpenTUI native FFI is not available for this runtime` | **仅 Bun**（原生 darwin-arm64 预编译） |
| `neo-blessed` | 0.2.0 | ✅ 全屏 alt-screen、边框盒、状态栏实测通过 | Node 可用（纯 JS，imperative） |
| `blessed` / `terminal-kit` | 0.1.81 / 3.1.4 | 预计可用（纯 JS） | 备选 |

## 3. 运行时分叉（需 founder 决策）

**A. Bun + `@opentui/react`**（React + 原生 diff + 内置动效）
- 优点：保留 **React/TSX** 心智与现有组件迁移成本低；全屏 + 细粒度差分；动效/多面板最省力。
- 代价：**把客户端运行时从 Node 换成 Bun**（此前 Bun 仅批准为"打包备选"）；**每平台原生二进制**（darwin-arm64/x64、linux、win）；库 0.5.x 年轻；SSH 需验证。
- 影响：分发由 npm(需 Node) → Bun 单二进制/`bun install`；与既有"npm 维持"决策冲突，需你更新决策。

**B. Node + `neo-blessed`**（纯 JS 全屏）
- 优点：**维持 Node 运行时与 npm 分发**，零原生依赖；全屏 alt-screen、盒子、独立滚动（blessed 原生支持）成熟；SSH 友好。
- 代价：**非 React**，view 层需**命令式重写**（`App.tsx` 视图与组件），动效需自绘（blessed 无插值动效）；库较老（0.2.0，社区维护弱）。
- 影响：`SurfaceClient`/`TuiController`/协议**不动**（纯 view 替换），测试与 kernel 零改动。

**C. Node + `terminal-kit`**：现代 API、纯 JS，但面板/滚动/React 均需自建，工作量最大。

**建议**：若坚持"主流成熟 + 不引入新运行时"→ **B**（Node+blessed）；若接受"换 Bun 换更好的 DX/动效"→ **A**（opentui）。二者都必须在 **C7/permit/审批** 与 **一 session 一 turn** 冻结语义内。

## 4. 迁移分期（不变量：SurfaceClient/协议/审批/C7 不动）

```text
P0  spike：选定渲染器 + alt-screen 启动 + 首页/流式文本/状态栏/输入框最小闭环（pty 抓帧）
P1  view 移植：transcript（finalized/active）、工具卡、审批卡、palette/selector、composer、vim/mention
P2  全屏能力：多面板（transcript + files + diff）独立滚动、上下文锁定、动效开关(--no-animation)
P3  多Agent/任务树：需先扩展 surface 协议 + 解除一turn冻结（独立 GC + 安全评审，受 C7/permit）
```

每期退出条件：**功能对齐现 Ink 版**（回归清单）+ **SSH 度量**（见 §5）+ 独立评审 + CI 绿；P2/P3 各自独立 GC。

## 5. 验收度量（量化，替代"零抖动"口号）

- **SSH/稳定**：单帧写入字节数（p95）、全屏 clear 次数=0、`Ctrl-C`/resize 无乱屏、Tmux/Screen 正常。
- **交互**：p95 输入回显延迟；独立滚动不冲刷用户阅读位置（有测试）。
- **兼容**：CJK/宽字符、`--no-animation` 静态模式、no-color。
- **安全**：审批/权限面在前台可见；多面板不弱化 permit/approval。

## 6. 风险

- A：Bun 运行时/原生二进制/平台矩阵/库成熟度；B：imperative 重写量 + 老库维护。
- 过渡期"两套 view"维护成本 → 设截止点，对齐后**删除 Ink 版**（同 Stage 2f 方式）。
- 多Agent/任务树不是 UI 问题：**内核/协议先行**。

## 7. P0 spike 结果（2026-09-15，PASS）

- **决策确认**：**A = Bun + `@opentui/react`**（founder）。
- **实测**：`bun add @opentui/react@0.5.11 @opentui/core@0.5.11 ws react-devtools-core`（React 19 已兼容）；`bun run spike/fullscreen.tsx` 在 pty(90×24) 渲染出**真全屏**：alt-screen、`┌─ NOEM ─…┐` 边框盒、`message` 输入盒、`❯ ASK · deepseek-chat · /help` 状态栏。
- **落点**：spike 置于 `apps/cli-ts/spike/fullscreen.tsx`（不入 `src`/打包），脚本 `npm run spike:fullscreen`（Bun）。
- **影响/后续**：
  - 客户端运行时由 Node → **Bun**（此前"npm 维持"分发决策需更新为 Bun；单二进制可用 `bun build --compile`，与既有"Bun 备选"一致）。
  - P1：把 `SurfaceClient`/`TuiController`（协议/状态，**不动**）接到 @opentui 视图，移植 transcript/工具卡/审批卡/palette/composer。
  - P2：多面板 + 独立滚动 + `--no-animation`；P3：多Agent/任务树（内核/协议先行）。
  - `Ink` 依赖在视图对齐后删除（同 Stage 2f 处理）。
