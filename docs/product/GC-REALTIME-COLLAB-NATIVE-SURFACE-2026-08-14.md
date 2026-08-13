# Realtime Collaboration → Native Surface 重构 Goal Card

> Date: 2026-08-14
> Track: Product
> Status: **SPEC_APPROVED / CTO_IMPLEMENTATION_AUTHORIZED / NOT_IMPLEMENTED / NO_MERGE_PUSH_RELEASE_AUTHORITY**
> Exact base: `1e479093820d888de6ea17bc61be09ba6746d815`（main；spec branch `spec/realtime-collab-fence-20260814`）
> Authority: `docs/research/founder-decision-2026-08-14-post-convergence-route-cast.md` §2
> Requirement: GOAL-BLUEPRINT M2「人/Agent 同空间并发工作」真实产品需求
> Claim ceiling before review: `SPECIFIED_ONLY`
> Prior art: `codex/realtime-collab-runtime-m1-20260809` @ `7c9ddaf5`（dirty 未提交，donor/reference，不直接合入）

## Goal

把已实现但分叉的「Realtime Workspace Collaboration M1」重挂到 ADR-0059 唯一 capability
execution-authority spine 上，并给出 macOS Native Surface 的可见冲突/协作纵切。

用户可见结果（`U`）：在桌面 Surface 上，当一个人与一个 Agent（或两个 Agent）并发编辑同一
资源时，用户看到**明确的、可解释的冲突/重规划（REPLAN/CONFLICT）而非静默覆盖**，且任何被
拒绝的写入都不会调用下游 connector（零副作用）。

产品能力（`P`）：一个 collaboration fence seam，它作为 `CapabilityBroker.invoke` 的唯一
dispatch 路径上的**前置校验阶段**（不是第二个 broker），在 `execution_claim` 之外要求一个
绑定 lease + event-batch 的写前校验，决定 `CONTINUE / REPLAN / CONFLICT / CANCEL`。

## 为什么现在做（决策依据）

1. GOAL-BLUEPRINT M2 的并发协作是明确产品需求，但旧 M1 停在 isolated dirty 分支上未推进。
2. 旧 M1 的 `CollaborativeCapabilityBroker.invoke(action, permit, *, lease, event_batch,
   write_scopes, now, attempt)` 与 ADR-0059 唯一 spine 签名 `invoke(action, permit, attempt=1,
   *, execution_claim)` 分叉，形成第二个 pre-write 权威入口——这是 ADR-0059 明确禁止的
   bypass 风险（「两个执行路径 = 一个 spine 的 bypass 风险」）。
3. ADR-0059 已把 execution authority 重塑为「claim → preflight(确定性 deny) → reserve →
   guarded dispatch → seal」，collaboration 语义正是 preflight 阶段的一个自然扩展点。

## 核心重构决定

| 旧 M1（废弃） | 新（保留/重挂） |
|---|---|
| `CollaborativeCapabilityBroker` 作为独立 pre-write 入口 | 删除；collaboration fence 作为 `CapabilityBroker` 的 preflight seam |
| `invoke(..., lease, event_batch, write_scopes, now, attempt)` | `invoke(action, permit, attempt=1, *, execution_claim)` 唯一签名不变 |
| `WorkLease` 与 `ExecutionLease` 平行、语义重叠 | `WorkLease` 语义并入/对齐 `ExecutionLease`（`run_id/owner/fence/expires_at`），collaboration 维度（scopes/cursor）作为 claim 的附加绑定字段或独立 lease 但必须同源校验 |
| `CoordinationAuthorityContext` 独立 | 保留，但授权/principal 校验下沉到既有 `ActionPermit` + policy |
| `WorkspaceEvent/WorkspaceEventBatch/ResourceScope` | 保留（contract 层） |
| `CONFLICT/REPLAN/CANCEL` disposition | 保留，三种非 CONTINUE 态都阻止 dispatch（零 reservation、零 connector 调用） |
| `SQLiteWorkspaceCommitFence` | 保留为 node 级 adapter，但只存 lease/event/cursor/decision，不存外部效果真相，不自行 dispatch |

## 最小纵切（M1'）

1. **Contract**：`ResourceScope` / `WorkspaceEvent` / `WorkspaceEventBatch` / `WorkLease`
   （对齐 `ExecutionLease` 同源校验）迁入 `agent_os_contracts`。
2. **Seam**：`CapabilityBroker` 构造注入 collaboration preflight；`preflight(action, claim)`
   从权威 coordination store 读 lease/event/cursor（不接受 caller 传入参数），在
   `execution_claim` 校验之后、`connector.preflight` 之前执行写前判定；任何非 CONTINUE 决策
   都零 reservation、零 connector 调用。
3. **required fail-closed**：`CapabilitySpec.collaboration_required` 标记；required 写能力在
   broker 无 collaboration preflight 时必须拒绝 dispatch（非 no-op）。
4. **Decision**：`WorkspaceWriteDecision` 四态；`CONFLICT/CANCEL` fail-closed，
   `REPLAN` 同样阻止 dispatch 并返回 typed `ReplanRequired` 给 orchestration（非放行）。
5. **单一效果真相**：fence 不含 PREPARED/COMMITTED/UNKNOWN；外部效果状态只归
   `DurableActionOutcomeRepository + CapabilityBroker`。
6. **Surface**：Native Surface（wave2 面板）暴露 file-level 冲突可见流——同一文件并发写触发
   `CONFLICT` 时，UI 显示冲突来源与 scope，不允许静默覆盖。
7. **测试**：三态写前失败/覆盖保护/lease 过期/无关 scope 不锁/required fail-closed/connector
   零调用，全 Product 回归零新失败。

## 非目标（本次不做）

事件 watcher、CRDT、语义 merge、跨主机/网络分区分布式控制面、多 agent 调度、exactly-once
外部效果证明、训练、release、自主性声明。

## 验收形状

- 唯一 dispatch 路径不回归（bypass 测试：collaboration deny 时 connector 零调用）。
- 旧 M1 的 7 条跨进程/覆盖/冲突测试语义在新 seam 下通过，且不新增第二个 broker。
- Ruff clean / Pyright 0 / 全 Product 回归零新失败。
- 独立 exact-head review（builder≠reviewer）+ CTO gate 后才可合并。

## 下一步 gate

三项 route choice 已锁定（构造注入 / WorkLease 独立+同源校验 / file-level Surface），4 个
规格 P1 已关闭。2026-08-14 新 CTO gate 对 exact spec head `ad83b855` 返回
`CTO_IMPLEMENTATION_AUTHORIZED`：允许从该 head 开实现分支，按 failing/bypass-detecting 测试
先行实现最小纵切。此授权不包含 merge、push、release 或产品完成声明；实现仍须全 Product
回归零新增失败、独立 exact-head review 与单独 merge gate。
