# Architecture Brief — Realtime Collaboration Fence on the ADR-0059 Spine

> 配套 Goal Card: `docs/product/GC-REALTIME-COLLAB-NATIVE-SURFACE-2026-08-14.md`
> 配套 Context Pack: `docs/product/CP-REALTIME-COLLAB-NATIVE-SURFACE-2026-08-14.md`
> Date: 2026-08-14
> Status: `DRAFT / FOR_CTO_GATE`
> Primary class: `P/A`（产品能力 + authority 不变量）

## 1. 目标架构

协作语义作为 ADR-0059 唯一 dispatch 路径的 **preflight seam**，而不是第二个 broker。

```
CapabilityBroker.invoke(action, permit, attempt=1, *, execution_claim)
  │
  ├─ permit.matches(action)                       # 既有
  ├─ replay(action) → 命中即返回                  # 既有
  ├─ execution_claim.run_id/fence 绑定校验         # 既有（ADR-0059 P1）
  ├─ permit 过期 / correction halt / epoch         # 既有
  ├─ ★ collaboration_preflight(action, execution_claim)
  │      → WorkspaceWriteDecision{CONTINUE|REPLAN|CONFLICT|CANCEL}
  │      → 任何非 CONTINUE 的 disposition 都阻止当前 action：
  │          CONFLICT/CANCEL: raise WorkspaceWriteRejected（deterministic deny）
  │          REPLAN: 同样阻止 dispatch（零 reservation、零 connector 调用），
  │                  但作为 typed ReplanRequired 信号返回给 orchestration，
  │                  要求重规划，而非允许原 action 继续
  ├─ connector.preflight(...)                      # 既有（domain-pack 确定性 deny）
  ├─ outcomes.reserve(action, execution_lease=...) # 既有
  ├─ guard_unchanged → connector.execute → seal    # 既有
```

关键不变量：

1. **collaboration fence 自身不授权**。授权仍由 `ActionPermit` + policy + `execution_claim`
   唯一承载；fence 只做「资源协调假设是否仍成立」的写前校验。
2. **任何非 CONTINUE 决策都零副作用**：deny 时 connector 零调用，且不产生
   reservation/UNKNOWN 记录。REPLAN 不是「放行」，是「阻止 + 重规划信号」。
3. **preflight 端口不接收 caller 传入的 `lease/event_batch` 参数**。它依据
   `ActionContract + execution_claim` 从权威 coordination store（fence 的持久层）读取当前
   lease/event/cursor，避免调用者伪造 lease 假设。

## 2. 组件与边界

### 2.1 Contract（`agent_os_contracts`，domain-independent）

- `ResourceScope`：稳定资源 URI + domain-owned selector 维度；`overlaps()`/`covers()`
  保守且 selector-aware。Core 不解析具体文件/文档格式。
- `WorkspaceEvent` / `WorkspaceEventBatch`：有序 actor/provenance/version 变更 + affected
  scopes + impact；`_require_version_advance` 保证单调。
- `WorkLease`：task/run/tenant/workspace/holder/plan/cursor/time + scoped write 假设 +
  单调 `lease_version` + `fence_token`。**与 `ExecutionLease` 同源**：`run_id`/`owner`/`fence`
  必须匹配 `execution_claim`，否则 `ExecutionLeaseConflict`。
- `WorkspaceWriteDecision`：preflight 产物（action、lease、plan version、checked cursor、
  affected scopes、relevant event ids、authority digest、disposition、authorization result）。
- `CollaborationDisposition`：`CONTINUE / REPLAN / CONFLICT / CANCEL`。

### 2.2 Seam（`agent_os_core`，构造注入，required 语义 fail-closed）

- `CollaborationPreflightPort`：`preflight(action, claim) -> WorkspaceWriteDecision`。
  **不接收 caller 传入的 lease/event_batch**；port 从权威 coordination store 依据
  `action` + `claim` 读取当前 lease/event/cursor 后判定。
- `CapabilityBroker` 构造时接受可选的 `collaboration_preflight`。其 no-op 语义受
  **collaboration-required 标记**约束：
  - 对**非协作型** capability，`collaboration_preflight is None` 时走 no-op（100% 向后兼容）。
  - 对声明为 **collaboration-required** 的写 capability，`collaboration_preflight is None`
    必须 **fail-closed**（拒绝 dispatch，不产生 reservation），不能 no-op。
  - collaboration-required 标记来自 capability spec（如 `CapabilitySpec.collaboration_required:
    bool = False`），是 typed、可审计的选择机制，避免「默认 None」成为 workspace write 的
    绕过路径。
- deny（`CONFLICT/CANCEL/REPLAN`）在 `outcomes.reserve` 之前发生：
  - `CONFLICT/CANCEL`：raise `WorkspaceWriteRejected`（确定性拒绝）。
  - `REPLAN`：同样阻止 dispatch，raise 或返回 typed `ReplanRequired` 信号给 orchestration，
    绝不继续原 action。

### 2.3 Fence 实现（`domain_packs/developer_agent` 或 node 级 adapter）

- `SQLiteWorkspaceCommitFence`：stdlib SQLite + POSIX `flock`，单主机跨进程协调。
- **fence 只保存 coordination 状态**：lease、event、cursor、decision。它**不保存任何外部效果
  真相**。
- **删除旧 M1 的 `PREPARED → COMMITTED/UNKNOWN` 外部效果状态机**。外部效果的
  reservation/outcome/UNKNOWN 只由 ADR-0059 的 `DurableActionOutcomeRepository +
  CapabilityBroker` 管理；coordination fence 不复制、不产生、不覆盖任何效果状态。
- 旧 M1 的 `dispatch=lambda: downstream.invoke(...)` 删除；fence 不自行 dispatch，dispatch
  唯一入口是 `CapabilityBroker.invoke`。
- 崩溃后的「效果未知」由 broker 的 `CapabilityEffectUnknown` 承载（`POST_DISPATCH_UNCERTAIN`），
  不是 fence 自产的状态。

### 2.4 边界（Authority / Domain）

- Core（`agent_os_core`）只含 generic preflight port + broker 注入点，**不含**任何
  workspace/文件格式/资源解析语义。
- `ResourceScope`/`WorkspaceEvent` 是 domain-independent contract；具体 selector 维度由
  domain pack 提供。
- 没有第二个 broker、没有第二个授权来源、没有绕过 `execution_claim` 的路径。

## 3. C7 / 安全 / 权威

- fence 不持有最终执行权威；deny 是确定性拒绝，不是授权。
- 无 untyped 模型输出直接成为 consequential 命令；collaboration 判定全部走 typed
  `WorkspaceWriteDecision`。
- correction/C7 仍由既有 `guard_unchanged` + `correction` 承载，fence 不复制。

## 4. 验证策略（bypass-detecting）

- 写前失败测试：`CONFLICT/CANCEL/REPLAN` 三态都断言 connector 调用计数 == 0，且无
  reservation 记录。
- **REPLAN 不放行**：REPLAN 决策下原 action 不进入 `connector.execute`，orchestration 收到
  typed `ReplanRequired`。
- **required-preflight fail-closed**：对 collaboration-required 写 capability，broker 无
  collaboration preflight 时拒绝 dispatch（非 no-op）。
- **单一效果真相**：静态/动态断言 fence 不含 `PREPARED/COMMITTED/UNKNOWN` 效果状态；外部
  效果状态只存在于 `DurableActionOutcomeRepository`。
- 覆盖保护：相关 scope 的并发写不静默覆盖。
- 无关 scope：不同 resource URI / 不同 symbol 不产生 workspace 全局锁。
- lease 过期 / 不完整 event read / 越界写 → 在 dispatch 前取消。
- 唯一入口回归：删除 `CollaborativeCapabilityBroker` 后，全 Product 回归零新失败；静态断言
  无第二个 `invoke` 权威入口。
- Surface：同一文件并发写触发 CONFLICT 时 UI 显示 scope + 来源，禁止静默覆盖。

## 5. 非目标

watcher、CRDT、语义 merge、跨主机/网络分区、多 agent 调度、exactly-once 外部效果、
训练、release、自主性声明。

## 6. CTO 决策（2026-08-14 锁定）

1. preflight 注入方式：**构造注入**。不改 `invoke` 唯一签名；动态 lease/event_batch 由
   port 从权威 coordination store 依据 `action + claim` 读取，不由 caller 传入。
2. `WorkLease`：**独立 contract + 同源校验**。`ExecutionLease` 承载物理执行
   ownership/fence；`WorkLease` 只承载资源范围/版本/cursor/协作假设，不产生权限，须绑定同一
   run/task/tenant/workspace/owner 与 exact execution-claim fence/digest。
3. Surface 最小冲突粒度：**file-level 起步**。symbol-level 保留 selector 扩展能力，不进首版
   实现与完成声明。

## 7. 实现前必须关闭的 P1（CTO_REVISE_TO_SPEC）

- [x] REPLAN 也必须阻止当前 action（零 reservation、零 connector 调用），是重规划信号非放行。
- [x] fence 不持有外部效果真相；删除 PREPARED/COMMITTED/UNKNOWN，效果状态只归
  `DurableActionOutcomeRepository + CapabilityBroker`。
- [x] collaboration-required capability 的 fail-closed 选择机制（`CapabilitySpec.
  collaboration_required`），避免「默认 None」绕过 workspace write。
- [x] exact-base provenance：三件套已落在 `main@1e479093` 干净 spec 分支
  `spec/realtime-collab-fence-20260814`（连同 CTO verdict 一并提交）。

## 8. 制品基线

三件套 + CTO verdict 已从误放的默认 checkout `e06ab992` 迁移到基于
`main@1e479093820d888de6ea17bc61be09ba6746d815` 的干净 spec 分支。实现 worktree 应从此 spec
分支开出。
