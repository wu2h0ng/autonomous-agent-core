# Architecture Brief — Surface Conflict Projection + Event Producer (M1b)

> 配套 Goal Card: `docs/product/GC-REALTIME-COLLAB-SURFACE-M1B-2026-08-14.md`
> 配套 Context Pack: `docs/product/CP-REALTIME-COLLAB-SURFACE-M1B-2026-08-14.md`
> Date: 2026-08-14
> Status: `DRAFT / FOR_CTO_GATE`
> Primary class: `P`（产品能力）

## 1. 目标架构

M1b 在 M1a 的 fence seam 之上补两个正交能力：**事件生产者**（关 P2 #3）与**冲突投影**（Surface 可见）。

```
外部写（编辑器 / 另一 Agent / watcher）
  └─ WorkspaceEventProducer.record(external_write)
       → 构造 WorkspaceEvent(scope, MUTATION, version+1)
       → fence.append_event(event)          # 推进 coordination 状态，不授权

Agent dispatch（workspace.edit/apply_patch）
  └─ CapabilityBroker.invoke
       └─ collaboration preflight (M1a)
            → 非 CONTINUE: WorkspaceWriteRejected / ReplanRequired
                 └─ SurfaceConflictProjection.from_decision(decision)
                      └─ Surface files/diff 面板渲染 scope+来源+disposition
```

## 2. 组件与边界

### 2.1 事件生产者（`domain_packs/developer_agent`，关 P2 #3）

- `WorkspaceEventProducer`：把「外部文件变更」转成 `WorkspaceEvent` 并 `append_event`。
- 只记录 coordination 状态，不授权、不 dispatch、不写效果真相。
- scope 派生与 M1a 一致（`file:///ws/{path}`）；version 单调推进。
- **cursor 语义**：`_install_run_work_lease` 不再硬编码 `event_cursor=0`，改读 fence 当前
  high-water；重规划后的新 run 从最新 cursor 起，解除「冲突永久阻断」。

### 2.2 冲突投影 contract（`agent_os_contracts`）

- `SurfaceConflictProjection`：从 `WorkspaceWriteDecision` 派生 typed 视图：
  - `action_id` / `lease_id`
  - `disposition`（REPLAN / CONFLICT / CANCEL）
  - `reason`
  - `write_scopes` + `relevant_event_ids`
  - `suggested_action`（`REPLAN` / `REVIEW_DIFF` / `NONE`）
- 保持只读投影：不改 authority、不改 fence 状态。

### 2.3 Surface 渲染（`apps/macos/renderer`）

- files/diff 面板在冲突时显示 scope + 来源 + disposition + suggested_action，不静默覆盖。
- 复用 wave2 已有 panel 骨架；不引入 CRDT、语义 merge、跨进程事件总线。

## 3. 边界（Authority / Domain）

- 事件生产者与投影都不持有执行权威；deny 仍由 broker 唯一承载。
- Core 不新增 workspace/文件解析语义；projection contract 是 domain-independent 视图。
- 无第二个 broker、无第二个授权来源。

## 4. 验证策略

- 事件生产者：外部写 → fence 产生完整 batch；cursor 推进；重规划后新 lease 从最新 cursor 起，
  不再永久阻断。
- 冲突投影：`from_decision` 对 REPLAN/CONFLICT/CANCEL 各自产生正确 suggested_action。
- Surface：冲突时面板显示来源+scope，不静默覆盖；正常路径渲染不回归。
- 全 Product 回归零新增失败；Ruff/Pyright 干净；独立 review + CTO gate。

## 5. 非目标

跨进程事件总线、watcher 实时推送、CRDT、语义 merge、多主机、自动 replan、release、自主性声明。

## 6. CTO gate 待决

1. 事件生产者触发模型：显式写入钩子（推荐首版）vs 文件 watcher。
2. cursor 语义：新 lease 取 fence high-water（推荐）。
3. 冲突粒度：file-level 起步（推荐）。
