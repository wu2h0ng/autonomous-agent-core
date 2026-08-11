# Customer POC Readiness Brief

> 日期：2026-06-06  
> 用途：判断一个客户是否适合进入首批 POC，以及 POC 如何避免变成免费咨询。

## POC 进入条件

| 条件 | 必须满足 |
|---|---|
| 业务 owner | 有明确经营指标压力 |
| 预算 owner | 能参与 W6 转付费讨论 |
| 数据 owner | 能提供数据源、字段说明和权限边界 |
| 场景 | 单一高频业务闭环，不是泛平台建设；必须能产生 DataProduct candidate、EvidenceChain、ActionProposal、Feedback/Trace 或 KnowledgeAsset candidate |
| 成功标准 | 能量化节省时间、减少损失、提升响应速度或发现异常 |
| 安全边界 | 不要求绕过 SQL Safety、EvidenceChain、Approval 或审计 |

## 首发 POC 推荐场景

优先：

- 投放 ROI 异常诊断。
- GMV / 转化漏斗异常解释。
- 内容 / 达人 / 商品效率分析。
- 库存周转风险预警。

暂缓：

- 全渠道完整数据中台。
- 全自动业务执行。
- 完整 BI 替代。
- 高风险写操作。
- 客户专属重型定制。

## POC 计划

| 周期 | 目标 |
|---|---|
| W0 | 确认 owner、数据、场景、成功标准、退出规则 |
| W1-W2 | 建立 MetricContract、SQL Safety、golden query |
| W3-W4 | 跑通 EvidenceChain、首个 ActionProposal 和 Feedback/Trace |
| W5 | 业务 owner 复盘答案可信度和行动可用性 |
| W6 | 进入付费转换讨论 |
| W7-W8 | 固化 Domain Pack / KnowledgeAsset candidate、复盘 ROI、决定续约或停止 |

## Kill Criteria

- 无预算 owner。
- 数据 owner 无法配合。
- 客户不断扩大到平台级需求。
- 成功标准无法量化。
- 客户拒绝 W6 付费讨论。
- 必须绕过安全、证据链或审批才能演示价值。

## CEO 承诺边界

可以承诺：

- 在限定场景内验证可信问数和行动提案。
- 明确记录证据链、口径、数据来源和限制。
- 用 POC 产物沉淀可复用 Domain Pack。

不能承诺：

- 自动执行高风险业务动作。
- 全量连接器覆盖。
- 替代客户数仓、BI、Data Fabric 或 NoETL。
- 保证 ROI。
- 未经 CTO/Security/Legal 审批的生产上线。
