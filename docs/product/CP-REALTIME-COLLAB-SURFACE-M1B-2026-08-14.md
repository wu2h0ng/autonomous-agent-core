# Context Pack — Realtime Collaboration Surface Conflict Projection (M1b)

> 配套 Goal Card: `docs/product/GC-REALTIME-COLLAB-SURFACE-M1B-2026-08-14.md`
> Date: 2026-08-14
> Status: `DRAFT / FOR_CTO_GATE`

## 1. 现状

M1a（已合入 main `1ea99cab`）交付了生产 runtime fence：
- `workspace.edit`/`workspace.apply_patch` 标记 collaboration-required；
- `AgentOSApplication` 注入权威 fence/preflight，`start_run` 装 run-bound lease；
- 非 CONTINUE 决策（CONFLICT/REPLAN/CANCEL）在 reservation 前 fail-closed。

遗留（M1a carry-forward P2）：
- **P2 #3**：fence 的 `append_event` 仅测试调用；生产没有事件生产者，`event_cursor` 永不前进。
  后果：一旦冲突事件写入，重叠 scope 的写入被永久阻断，直到重装 lease，且无法区分「无事件」
  与「有事件但未读取」。
- **P2 #5 部分**：`WorkspaceEventImpact.PLAN_INVALIDATED` 落入 REPLAN 分支（已补测试），但
  生产无任何事件源产生它。

## 2. 权威输入

- `docs/adr/ADR-0059-merged-capability-execution-authority.md`（唯一 dispatch spine）
- `docs/product/GC-REALTIME-COLLAB-NATIVE-SURFACE-2026-08-14.md`（M1a 已交付）
- `docs/architecture/T-P-REALTIME-COLLAB-FENCE-2026-08-14.md`（fence seam 架构）
- `docs/product/CTO-GATE-REALTIME-COLLAB-2026-08-14.md`
- `packages/contracts/src/agent_os_contracts/workspace_collaboration.py`（contract）
- `domain_packs/developer_agent/workspace_collaboration.py`（fence 实现）
- Surface：`packages/contracts/src/agent_os_contracts/surface.py`、
  `packages/os_core/src/agent_os_core/surface_runtime.py`、`apps/macos/renderer/src/panels/*`

## 3. 关键架构问题与回答

1. **事件生产者放哪？** 作为 `domain_packs/developer_agent` 的一个 seam，紧邻 fence：
   `WorkspaceEventProducer`，把「同一 workspace 的文件变更」转成 `WorkspaceEvent` 并
   `fence.append_event(...)`。它不授权、不 dispatch，只推进 coordination 状态。写入来源
   （本地编辑器 / 另一 Agent 经 fence 的写 / 显式 watcher）都通过同一 producer。

2. **event 的 scope 怎么定？** file-level 起步：`ResourceScope(resource_uri=f"file:///ws/{path}")`，
   与 M1a 的 `_file_scope_from_action` 一致。version 用 `base_version`/`resulting_version`
   单调推进（可先用内容 digest 派生，后续再换真实版本号）。

3. **cursor 如何推进？** 事件 append 后，`event_cursor` 属于 lease；重规划后新 run 装新 lease
   时以当前 high-water 为新 `event_cursor`，从而「冲突 → 重规划 → 新 lease 从最新 cursor 起」
   解除永久阻断。这需要 `_install_run_work_lease` 读取 fence 当前 high-water 而不是硬编码 0。

4. **冲突投影 contract？** `SurfaceConflictProjection`：从 `WorkspaceWriteDecision` 派生
   （scope + disposition + reason + relevant event ids），作为 Surface 可见 typed 视图。
   `REPLAN` → 建议重规划；`CONFLICT` → 建议查看差异 / 显式确认覆盖。

5. **Surface 渲染落点？** `apps/macos/renderer/src/panels/files.ts` / `diff.ts`：当 dispatch
   返回冲突时，面板显示冲突标记（scope + 来源 + disposition），不静默覆盖。复用 wave2 已有
   panel 骨架，不引入 CRDT/语义 merge。

## 4. 风险与边界

- 风险：事件生产者若误把「自身写」也当冲突，会自锁。缓解：producer 绑定 run/principal，
  只记录「外部」变更（不同 holder 或非 fence 路径的写）。
- 边界：不做跨进程事件总线、不做 watcher 的实时推送（先做显式/轮询级），不 release。
- 证据边界：Product Track（P/U），非研究证据（R）。

## 5. 待 CTO 确认点

- 事件生产者的触发模型：显式写入钩子 vs 文件 watcher vs 两者？
- cursor 推进语义：新 lease 的 `event_cursor` 取 fence high-water（推荐）vs 其他？
- Surface 冲突粒度：file-level 起步（推荐，与 M1a 一致）vs symbol-level？
