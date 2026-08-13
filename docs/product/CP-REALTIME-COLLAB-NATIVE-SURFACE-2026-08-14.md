# Context Pack — Realtime Collaboration → Native Surface 重构

> 配套 Goal Card: `docs/product/GC-REALTIME-COLLAB-NATIVE-SURFACE-2026-08-14.md`
> Date: 2026-08-14
> Status: `DRAFT / FOR_CTO_GATE`

## 1. 现状与分叉根因

旧 M1 在 `codex/realtime-collab-runtime-m1-20260809 @ 7c9ddaf5` 上以 dirty 未提交状态存在
（6 个文件：contracts/workspace_collaboration.py、os_core/workspace_collaboration.py、
__init__.py ×2、PM 文档、test_workspace_collaboration.py）。

分叉点：`CollaborativeCapabilityBroker` 自己定义了一个 `invoke(action, permit, *, lease,
event_batch, write_scopes, now, attempt)` 入口，把 `WorkLease` 作为平行于 `ExecutionLease`
的第二个 lease 概念，并在 fence 内 `dispatch=lambda: downstream.invoke(...)`。

这与 ADR-0059 的唯一 spine 冲突：

- ADR-0059 明确「Option 2 (wave spine wins) rejected: 两个执行路径 = 一个 spine 的 bypass 风险」。
- `CollaborativeCapabilityBroker` 恰好再造了一个第二入口，即使它委托 downstream，也引入了
  两套 claim/lease 校验语义，且其签名没有 `execution_claim` 强制绑定。

## 2. 权威输入

- `docs/adr/ADR-0059-merged-capability-execution-authority.md`（唯一 dispatch 路径、execution
  claim 强制、preflight→reserve→guarded dispatch→seal、UNKNOWN fail-closed）
- `docs/adr/ADR-0054-one-time-data-agent-history-migration.md`（domain pack 边界）
- `docs/GOAL-BLUEPRINT.md` M2（人/Agent 同空间并发）
- `docs/research/founder-decision-2026-08-14-post-convergence-route-cast.md` §2
- 旧 M1 契约文档 `docs/product/PM-REALTIME-WORKSPACE-COLLABORATION-M1-2026-08-09.md`（donor 语义）

## 3. 关键架构问题与回答（供 Architecture Brief 展开）

1. **seam 放哪？** 放 `CapabilityBroker.invoke` 内部，作为 `execution_claim` 绑定校验之后、
   `connector.preflight` 之前的一个可注入 collaboration preflight。preflight 不接收 caller
   传入的 lease/event_batch，依据 `action + claim` 从权威 coordination store 读取。
   collaboration-required 写能力在 preflight 缺失时 fail-closed；非协作型能力默认 no-op。
   这样不新增 broker、不改变唯一签名。

2. **WorkLease vs ExecutionLease 关系？** `ExecutionLease`（`run_id/owner/fence/expires_at`）
   是 dispatch 的 claim；`WorkLease` 的 collaboration 维度（scopes/cursor/version）是**写前
   资源协调**语义。二者是独立 contract，但必须同源：`run/task/tenant/workspace/owner` 相同，
   且绑定 exact execution-claim fence/digest，不能独立授权。

3. **deterministic deny 边界？** collaboration preflight 的**任何非 CONTINUE 决策**（
   `CONFLICT/CANCEL/REPLAN`）都必须在 reserve 之前阻止 dispatch（零 reservation、零 connector
   调用）。`CONFLICT/CANCEL` raise fail-closed；`REPLAN` 同样阻止并返回 typed
   `ReplanRequired` 信号，不放行原 action。

4. **外部效果真相归谁？** 只归 ADR-0059 的 `DurableActionOutcomeRepository +
   CapabilityBroker`。coordination fence 只保存 lease/event/cursor/decision，不持有
   PREPARED/COMMITTED/UNKNOWN 状态；崩溃后的效果未知由 `CapabilityEffectUnknown` 承载。

5. **Surface 出口？** wave2 已有 panel/canvas 骨架与本地 runtime daemon。最小纵切只做
   file-level「可见冲突」：同一文件并发写触发 `CONFLICT` 时，Surface 面板显示 scope + 来源 +
   不可静默覆盖，不引入 watcher/CRDT/网络。

6. **旧 M1 测试迁移？** 7 条语义（跨进程不双发、覆盖禁止、lease 过期取消、无关 scope 不锁、
   允许写仍过 broker、进程死亡 PREPARED→UNKNOWN）在新 seam 下重写为「唯一 broker」路径的
   断言，删除任何假设 `CollaborativeCapabilityBroker` 是独立入口的用例，并删除 fence 自产的
   效果状态断言（改为 broker 的 UNKNOWN 语义）。

## 4. 风险与边界

- 风险：若 collaboration preflight 误绑定独立授权，会复活「第二 authority」bypass。缓解：
  必须证明 deny 时 connector 零调用 + 复用 `execution_claim` 校验 + 独立 review。
- 边界：不做分布式、不做 watcher、不做语义 merge、不做 exactly-once 外部效果、不 release。
- 证据边界：这是 Product Track 能力（P/U），不是研究证据（R）。

## 5. 待 CTO 确认点

- 已锁定：preflight 构造注入；WorkLease 独立 contract + 同源校验；file-level Surface。
- 已关闭 P1：REPLAN 不放行、required-preflight fail-closed、单一效果真相、exact-base
  provenance（三件套 + CTO verdict 已落 `spec/realtime-collab-fence-20260814`，base
  `main@1e479093820d888de6ea17bc61be09ba6746d815`）。
