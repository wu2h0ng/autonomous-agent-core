# CEO Decision Map

> 日期：2026-06-06  
> 用途：记录公司级取舍、授权边界和交接对象。

## 决策总表

| 决策 | 当前结论 | Owner | 交接对象 |
|---|---|---|---|
| 公司核心产品 | AI Native Business Data Agent OS | CEO | 全部 Agent |
| 第一阶段范围 | 最小可信业务生产闭环，不做薄控制层，不做完整 Data Fabric | CEO + CTO | Product / PM / Engineering |
| 首发场景 | 内容电商 / DTC 经营分析和 ROI 异常 | CEO + Business Consultant | Product Requirements |
| 首个验收物 | Golden business loop + DataProduct candidate + EvidenceChain + Governed ActionProposal + Feedback / KnowledgeAsset candidate | CTO + Product | Eval / Backend / Frontend |
| 商业化路径 | Founder-led POC，6-8 周验证，W6 付费讨论 | CEO + Business Consultant | Sales / Solution |
| 技术边界 | OS Core 自研，外部 Agent 框架只作参考 | CTO | Engineering |
| 高风险动作 | R4/R5 只生成 proposal，不自动执行 | CEO + CTO + Security | Product / Engineering |
| 文档结构 | 不搬迁 source of truth，`docs/ceo/` 承担经营决策入口层 | CEO | Documentation Agent |
| 数据底座策略 | 借力数据 plane，不自建重型 Data Fabric / NoETL；抢 semantic / evidence / operation / knowledge contract spine | CEO + CTO | Product / Architecture |

## 继续推进条件

- 能用一个真实业务问题跑通最小可信业务生产闭环。
- DataProduct candidate 和 KnowledgeAsset candidate 都能在闭环中出现。
- EvidenceChain 能支撑业务 owner 判断答案可信。
- ActionProposal 能产生可讨论的业务动作，而不是泛泛建议。
- Eval 能覆盖 intent、metric、SQL、evidence、action 至少一条闭环。
- 客户访谈证明痛点和预算 owner 存在。

## 停止或降级条件

- 连续两轮客户访谈无法确认预算 owner。
- 客户只要免费咨询，不接受付费 POC 或转付费讨论。
- 需要先做重型 Data Fabric、NoETL、完整连接器市场或全量数仓替代才能产生价值。
- 工程闭环无法在 90 天内达到可信演示和 eval 覆盖。
- 关键能力只能靠硬编码 demo 支撑。

## 授权边界

CEO 可以授权：

- POC 目标客户优先级。
- 商业验证实验。
- 路线图优先级。
- 公司资源投入。
- 对外叙事边界。

CEO 不应绕过：

- CTO 的架构和实现真实性门禁。
- Security 的安全和数据边界。
- Legal 的合同和隐私条款。
- Finance 的正式定价和收入确认。
- Customer 的生产数据和上线批准。
