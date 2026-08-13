# CTO Gate — Realtime Collaboration Fence (REVISE_TO_SPEC)

> Date: 2026-08-14
> Gate: CTO implementation authorization
> Target: `docs/product/GC-REALTIME-COLLAB-NATIVE-SURFACE-2026-08-14.md` + 配套 Context Pack + Architecture Brief
> Exact base: `1e479093820d888de6ea17bc61be09ba6746d815`（main，canonical head `f4266cfd` 的 no-ff merge 结果）
> Spec branch: `spec/realtime-collab-fence-20260814`

## Verdict

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
