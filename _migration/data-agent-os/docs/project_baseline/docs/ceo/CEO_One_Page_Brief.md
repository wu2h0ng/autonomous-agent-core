# CEO One Page Brief

> 日期：2026-06-06  
> 决策对象：AI Native Business Data Agent OS 是否作为公司核心产品继续推进，以及第一阶段如何收敛。

## 一句话判断

继续推进，并把 `ai-native-business-data-agent-os/` 明确作为公司的完整核心产品实现，而不是 Data Agent 子集、控制层、薄中间件或 pipeline。第一阶段必须收敛为一个可付费、可复用、可验证的最小可信业务生产闭环：DataProduct candidate、EvidenceChain、Governed ActionProposal、Approval lite、Feedback / Trace、KnowledgeAsset candidate。

## 产品定义

AI Native Business Data Agent OS 是面向企业 AI Agent 时代的业务生产操作系统：它把业务意图编译为可信数据产品、证据链、受治理业务行动、反馈学习和知识资产。控制面是其中一部分，不是产品全部身份；语义理解、证据生产、行动治理和知识积累必须在产品内有真实能力。

它不是通用 ChatBI，不是传统 BI 报表系统，不是完整数仓替代，也不是第一天就自动执行业务动作的 Agent 平台。

## 第一阶段卖点

| 层级 | 对客户的表达 | 内部实现含义 |
|---|---|---|
| 数据产品候选 | 业务问题沉淀为可复用 DataProduct candidate，而不是一次性回答 | BusinessIntent、SemanticObject lite、MetricContract、ProviderContract lite、DataProduct Compiler lite |
| 可信问数 | 业务 owner 可以问清楚经营异常和 ROI 问题 | QueryPlan、SQL Safety、Eval、SQLite / provider executor |
| 证据链 | 每个答案能解释数据来源、口径、查询和限制 | EvidenceChain、Trace、ProviderContract |
| 行动提案 | 不只给结论，还给下一步受治理业务建议 | ActionProposal、OperationTrace、Approval lite、action connector |
| 复盘资产 | 每次问答、行动和反馈沉淀为可复用知识 | Feedback、Trace、KnowledgeAsset candidate |

## 首发 ICP

优先选择内容电商、DTC、直播电商或强投放驱动业务。必要条件：

- 有明确业务 owner 和预算 owner。
- 有 GMV、ROI、库存、内容、达人、投放或转化效率压力。
- 有可接入的数据源和数据 owner。
- 愿意用 6-8 周验证一个业务闭环。
- W6 前后能进入付费转换讨论。

## 当前最重要的取舍

| 选择 | CEO 判断 |
|---|---|
| 先做完整 OS 还是首个闭环 | 首个闭环，但不能把实现降级为薄控制层 |
| 先卖平台还是卖 POC 业务结果 | 卖可验收 POC 业务结果 |
| 先做自动执行还是行动提案 | 行动提案 |
| 先做全行业还是内容电商/DTC | 内容电商/DTC |
| 先扩连接器还是打通 Golden Loop | Golden Loop |
| 先自建数据底座还是抢 contract spine | 借力数据 plane，抢 semantic / evidence / operation / knowledge contract spine |

## 当前实现状态

| 已推进 | CEO 意义 |
|---|---|
| Governance gate 阻止 approval-required / R4 / R5 操作提前执行 | 可信行动边界开始成立 |
| SQLiteQueryExecutor 跑 Customer-0 seed 数据 | 从静态 fixture 走向真实数据路径 |
| `record_outcome` 驱动 Feedback / KnowledgeAsset version | 知识资产闭环开始落地 |
| `action_record` connector、snapshot、rollback | 受治理行动和回滚进入产品主线 |
| CLI `query` / `record-outcome` 与 FastAPI `/runs` / `/outcomes` | 有真实入口，不只是单元测试 |

## 90 天目标

1. 完成一个可演示、可评测、可审计的最小可信业务生产闭环。
2. 找到 5-10 个符合 ICP 的客户访谈对象。
3. 筛出 1-2 个 POC 候选客户。
4. 用 golden queries 和 golden business loop 验证真实业务价值。
5. 形成可复用 Domain Pack / KnowledgeAsset 初版。

## CEO 风险

| 风险 | 处理 |
|---|---|
| 叙事过大导致交付失焦 | 所有 P0 只服务最小可信业务生产闭环 |
| POC 变成免费咨询 | 必须设成功标准、转付费触发点和退出规则 |
| 客户要求重型 Data Fabric / NoETL / 数据平台 | staged-out，不进入 P0 |
| 工程为了 demo 降低可信度 | CTO gate 阻断 |
| 投资人叙事超过产品事实 | 所有能力区分已实现、验证中、假设 |
| 复盘/知识/回滚仍以内存为主 | 不能作为生产承诺，需 CTO 持久化方案 |

## 下一步授权

批准本轮 CEO 文档收束：新增 2026-06-06 当前产品就绪简报，更新 CEO 决策入口和 CEO 精简 HTML。原始资料保持不移动，继续作为 source of truth。
