# CEO 决策入口

> 日期：2026-06-06  
> 用途：把完整资料包压缩成 CEO、创始团队、投资人沟通和首批客户 POC 决策可直接使用的入口层。  
> 原则：不替代原始 source of truth，不搬迁权威文档；只提供经营视角的摘要、取舍和下一步动作。

## 阅读顺序

1. `CEO_One_Page_Brief.md`
2. `CEO_Current_Product_Readiness_Brief_20260606.md`
3. `CEO_Decision_Map.md`
4. `Customer_POC_Readiness_Brief.md`
5. `Investor_Readiness_Brief.md`

## CEO 当前必须回答的 6 个问题

| 问题 | 当前判断 | 主要证据 |
|---|---|---|
| 这个产品到底是什么 | 面向企业 AI Agent 时代的业务生产操作系统，覆盖可信数据产品、证据链、受治理业务行动、反馈学习和知识资产沉淀；不是控制层、薄中间件或 Data Agent 子集 | `00_对话总结与阅读指南/项目定义与价值叙事基线.md`、`ai-native-business-data-agent-os/README.md` |
| 第一阶段卖什么 | DataProduct candidate + EvidenceChain + 受治理 ActionProposal + Feedback/Trace + KnowledgeAsset candidate 的首个业务生产闭环 | `docs/ceo/CEO_Current_Product_Readiness_Brief_20260606.md` |
| 先找谁 | 内容电商 / DTC / 有 ROI、GMV、库存、内容投放压力的业务 owner | `02_竞争格局与商业化/AI_Native_Business_Data_OS_90天客户发现计划.md` |
| 怎么验收 | Golden business loop、golden queries、POC 转付费指标 | `05_业务问题与评测样本/AI_Native_Business_Data_OS_首个业务闭环验证方案.md` |
| 为什么能赢 | 不自建重型数据物理 plane，而是抢 semantic / evidence / operation / knowledge contract spine；DataProduct Compiler、EvidenceChain、Governed Operation、KnowledgeAsset 在同一闭环内复利 | `MEMORY.md`、`docs/ceo/CEO_Current_Product_Readiness_Brief_20260606.md` |
| 现在不做什么 | 完整 Data Fabric / NoETL、完整连接器市场、R4/R5 自动执行、客户专属重型数据平台、未验证生产承诺 | `docs/decisions/` 与 `07_CTO_实施管理与工程标准/CTO给CEO的实施决策简报.md` |

## 使用规则

- CEO brief 用于快速决策，不替代 CTO、Product、Security、Legal、Finance 的正式门禁。
- 对外材料只能引用已经实现、已验证或明确标注为假设的能力。
- 客户 POC 必须有业务 owner、预算 owner、数据 owner、成功标准、转付费触发点和退出规则。
- 新增公司级决策后，应同步更新 `code_index.md`、`.agent`、`00_对话总结与阅读指南/CEO阅读入口.md` 和文件清单。
