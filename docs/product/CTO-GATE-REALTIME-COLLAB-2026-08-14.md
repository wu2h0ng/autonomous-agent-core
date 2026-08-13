# CTO Gate — Realtime Collaboration Fence

> Date: 2026-08-14
> Gate: CTO implementation authorization
> Target: `docs/product/GC-REALTIME-COLLAB-NATIVE-SURFACE-2026-08-14.md` + 配套 Context Pack + Architecture Brief
> Exact base: `1e479093820d888de6ea17bc61be09ba6746d815`（main，canonical head `f4266cfd` 的 no-ff merge 结果）
> Spec branch: `spec/realtime-collab-fence-20260814`
> Original verdict head: `ad83b855b00f1174d5c9c34e80a05bb9988d1374`
> Reviewer: Codex CTO review session, independent read-only review of the submitted spec commit

## Initial verdict

`CTO_REVISE_TO_SPEC：三项 route choice 批准；关闭 REPLAN dispatch、required-preflight fail-closed、single effect truth、exact-base provenance 四项 P1 后，重新提交 implementation authorization。当前仍为 SPECIFIED_ONLY，不授权实现、合并、push 或 release。`

## 三项 route choice（批准）

1. **Preflight 构造注入**：不改 `CapabilityBroker.invoke(...)` 唯一签名；动态 `lease/event_batch`
   不由 caller 经 invoke 参数传入，preflight port 依据 `ActionContract + execution_claim` 从
   权威 coordination store 读取；`None` 只允许非协作型 capability，collaboration-required 写
   能力缺失 preflight 必须 fail-closed。
2. **WorkLease 独立 contract + 同源校验**：`ExecutionLease` 承载物理执行 ownership/fence；
   `WorkLease` 只承载资源范围/版本/cursor/协作假设，不产生权限，须绑定同一
   `run/task/tenant/workspace/owner` 及 exact execution-claim fence/digest。
3. **Surface file-level 起步**：首版只交付文件级冲突可见、来源/provenance 和
   REPLAN/CONFLICT 操作；contract 保留 selector 扩展，symbol-level 不进首版。

## P1 关闭记录

| # | P1 | 关闭 |
|---|---|---|
| 1 | REPLAN 也必须阻止当前 action（零 reservation、零 connector 调用） | 已改 Architecture Brief §1/§2.2/§4、Goal Card 最小纵切、Context Pack §3.3 |
| 2 | fence 不持有外部效果真相，删除 PREPARED/COMMITTED/UNKNOWN | 已改 Architecture Brief §2.3、Goal Card、Context Pack §3.4 |
| 3 | collaboration-required 的 fail-closed 选择机制 | 已改 Architecture Brief §2.2（`CapabilitySpec.collaboration_required`） |
| 4 | exact-base provenance（三件套落 main@1e479093 干净 spec 分支） | 本分支 `spec/realtime-collab-fence-20260814` 即为关闭动作 |

## 下一步

关闭 4 P1 后重新提交 implementation authorization。实现最小纵切仍需 failing/bypass-detecting
测试先行、独立 exact-head review（builder≠reviewer）、CTO gate 通过后才可合并。

## Re-submission review（2026-08-14）

### Reviewed evidence

- exact spec head `ad83b855b00f1174d5c9c34e80a05bb9988d1374`，parent 精确为
  `main@1e479093820d888de6ea17bc61be09ba6746d815`；
- 提交仅含本 Gate、Goal Card、Context Pack、Architecture Brief 四个规格制品；
- live ADR-0059 broker 顺序为 claim/permit/C7 → deterministic preflight → reserve → guarded
  connector dispatch → broker seal，存在不新增第二 authority path 的合法插入点；
- Founder 2026-08-14 route cast 明确选择 realtime-collab 为下一 active Product 工作，并要求挂载
  ADR-0059 唯一 spine；
- 四项原 P1 均已在三份规格中交叉关闭。

### Binding implementation interpretations

1. `REPLAN` 必须由 broker **raise typed `ReplanRequired`**，由 orchestration 捕获并形成新计划；
   不得返回成功 `CapabilityResult`、不得 reserve、不得调用 connector。
2. `CapabilitySpec.collaboration_required` 必须来自 connector/registry 的可信 capability registry；
   不得由 `ActionContract.arguments_json`、模型输出或调用者覆盖。
3. collaboration preflight 在现行 replay 之后、connector preflight/reservation 之前执行。已封存的
   replay outcome 仍由 broker 验证并返回；preflight 不得改写既有 outcome truth。
4. 本实现只交付单机、file-level 可见冲突纵切；跨主机、watcher、CRDT、语义 merge 与
   exactly-once 外部效果不进入完成声明。

### Findings

- P0：0
- P1：0
- P2：2 个实现期验证债，不阻塞启动：
  - 为可信 capability registry 增加 bypass test，证明 caller 不能降级
    `collaboration_required=true`；
  - 为 replay-before-collaboration-preflight 增加回归测试，证明已封存 outcome 不被新协作事件
    反向改写，同时新 action 仍受 fence。

## Final verdict

`CTO_IMPLEMENTATION_AUTHORIZED / SPEC_APPROVED / P0=0 / P1=0 / P2=2_TEST_DEBTS`

授权从 exact reviewed spec head `ad83b855` 创建实现分支，执行最小纵切的本地 TDD 实现与验证。
此裁决不授权直接复制旧 dirty M1、不授权第二 broker、不授权 merge、push、release、生产激活或
产品完成声明。实现完成门仍为：bypass-detecting tests、全 Product 回归零新增失败、Ruff/Pyright、
独立 exact-head review（builder != reviewer）以及单独 CTO merge gate。
