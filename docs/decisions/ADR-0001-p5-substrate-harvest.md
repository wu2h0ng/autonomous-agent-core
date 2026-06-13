# ADR-0001: P5 — 收割已验证的通用核基底进企业 OS

- Status: **Accepted as contract**(founder 2026-06-13 "都做" 批准跨仓 P5;代码分任务落地,各带测试)
- Date: 2026-06-13
- 对侧 ADR:`autonomous-agent-core/docs/adr/ADR-0018`(P5 投影契约)。本 ADR 是企业仓这一侧的落地配套。
- 边界:**模式移植,非代码搬运**。不 import `autonomous-agent-core`(RR-0004 §4 跨仓边界:只经规格)。
  只收割**已验证**的(原型主张 1/3/4);不收割已封存机制(claim-2/RAP/学习器官——未验证,无可收割)。

## 1. Context

原型(`autonomous-agent-core`)的 G0–G5 证伪程序立住了**安全基底**(主张 1 利害 / 3 可纠正 / 4 器官非主体),
而"聪明"机制未立(RR-0005)。P5 把这三条基底属性移植进部署层企业 OS,作为通用核的降级投影落地变现。

## 2. 三个收割映射(每条 = 一个已验证主张)

### P5.1 主张1 利害 = 不可绕过的强制中介(**第一任务,前置**)
企业版"输不起的东西" = 错误数据/越权行动的业务后果。把 Trusted Loop 升格为"绕不过的中介":
- **前置债务(RR-0002):分离 feedback 自写放水通道。** 现状 `TrustedLoopRuntime.record_outcome`
  (`trusted_loop.py`)由运行时**自写** `FeedbackStore`——未来任何自进化机制可伪造采纳信号给自己喂食。
  收割"不可绕过中介"前必须先分离:**外部实现价值(采纳/业务结果)经独立 ingest 通道(独立凭证/写路径)
  入账,运行时只持只读端口;`record_outcome` 的"运行时自报"与"外部采集价值"在 schema 上分离、永不混算。**
- 之后:把"正式数据答复 / R4-R5 行动**必过** SQL Safety + EvidenceChain"从**约定**(现 CLAUDE.md 硬规则)
  升格为**强制不变量**(旁路即测试失败)。

### P5.2 主张3 可纠正 = 移植硬化罩
企业 OS 现有 `approval_lite`/`snapshot_store`/`operation_trace`,但缺原型的硬化罩。移植:
- 能力视图隔离(operator `op_*` 主权面与运行时分离,镜像原型 `ShellView`);
- 只增哈希链审计(对照原型 `AuditLog`,可 `verify()`);
- 主权三分(罩=永恒 / 人主权层 / 系统过门);
- 可纠正性演练(定期真实触发 pause/rollback,零抵抗签名)。

### P5.3 主张4 器官非主体 = 既成事实,形式化
企业 OS 已是 Trusted Loop 为主体、`model_gateway` 为器官。把"模型只 advisory、不持真相、不掌控流程"
升格为可测不变量(对照原型 belief-only 器官 + strict parser:LLM 输出不可信、只能影响建议)。

## 3. 验收(预注册)

```text
P5-1 不可绕过中介:任何"业务意图→数据/行动"旁路 Trusted Loop 的尝试 = 测试失败(强制不变量)。
P5-2 硬化可纠正:operator pause/rollback/tighten 对运行时零越界;审计哈希链 verify;演练零抵抗。
P5-3 器官非主体:正式答复/真相在 data/evidence 路径;LLM/模型仅 advisory,旁路不可产出正式答复。
```

## 4. 任务序(各带测试 + 走本仓 AR/ADR 流程)

| 任务 | 范围 | 验收 |
|---|---|---|
| **P5.1a** | feedback 自写通道分离(独立 ingest + 运行时只读端口) | 守卫测试:运行时代码路径不可伪造外部采纳;自报与外部价值 schema 分离 |
| P5.1b | 正式答复/R4-R5 必过 SQL Safety+EvidenceChain 升为强制不变量 | 旁路尝试 = 测试失败 |
| P5.2 | 硬化罩移植(能力视图 + 哈希链审计 + 演练) | pause/rollback/tighten 零越界;audit verify;演练零抵抗 |
| P5.3 | 器官非主体形式化(model_gateway advisory 不变量) | 旁路不可产出正式答复 |

## 5. 边界

- 不 import 通用核;模式移植。claim-2/RAP/学习器官不投影。
- 触碰 SQL Safety/EvidenceChain/Feedback/Approval 行为的每个任务,按本仓 CLAUDE.md 走 AR/ADR + 测试。
- Customer-0 现金流路径不可破坏;P5.1a feedback 分离向后兼容(record_outcome 自报类别保留,仅价值采集外移)。
