# CEO Current Product Readiness Brief

> 日期：2026-06-06  
> 角色：Codex as CEO  
> 用途：把 2026-06-06 的产品身份、实现进展、经营判断和下一步授权压缩成 CEO 可读的当前状态页。

## 1. CEO 当前结论

继续把 `ai-native-business-data-agent-os/` 作为公司的核心产品实现推进。

本项目已经不能再被描述为 Data Agent、BI 助手、控制层、薄中间件或数据管道。当前公司级定义应统一为：

```text
AI Native Business Data Agent OS 是把企业业务意图转化为可信数据产品、证据链、受治理业务行动、反馈学习和企业知识资产的业务生产操作系统。
```

第一阶段仍然收敛，但收敛对象不是“可信问答”，而是最小可信业务生产闭环：

```text
BusinessIntent
  -> SemanticObject lite
  -> MetricContract
  -> ProviderContract lite
  -> DataProduct candidate
  -> SQL Safety / Eval
  -> QueryResult
  -> EvidenceChain
  -> ActionProposal
  -> Approval lite
  -> Feedback / Trace
  -> KnowledgeAsset candidate
```

## 2. 这轮更新改变了什么

| 维度 | 2026-06-03 口径 | 2026-06-06 新口径 |
|---|---|---|
| 产品身份 | 完整 OS 愿景 + Trusted Loop 第一阶段 | 明确反薄控制层：实现目录就是完整产品，不是 subset / middleware |
| MVP 边界 | Trusted Loop，不做完整 OS | MVP lite 必须是真实可用闭环，不能降级成 skeleton / stub / trusted Q&A |
| 护城河重点 | EvidenceChain + Governed Action + KnowledgeAsset | DataProduct Compiler + EvidenceChain + Governed Operation + KnowledgeAsset 全链路 |
| 数据底座取舍 | 保留 AI-ready data foundation lite | 不自建 Data Fabric / NoETL，抢语义-证据-行动-知识 Contract Spine |
| 实现状态 | Scaffold + minimum loop | 已推进真实 SQLite 查询、治理门禁、反馈/知识资产、回滚和 API 入口 |

## 3. 当前实现事实

截至本简报阅读到的项目记忆和实现文档，当前分支 `feat/pr0-governance-gate` 已形成以下事实：

| 能力 | 当前状态 | CEO 解释 |
|---|---|---|
| Governance gate | Approval-required / R4 / R5 操作在副作用执行前停止 | 防止为了 demo 绕过治理 |
| Real query path | SQLiteQueryExecutor 可在 seeded Customer-0 数据上返回真实结果 | 从 fixture 走向真实数据访问 |
| Feedback loop | `record_outcome` 可记录反馈并驱动 KnowledgeAsset version | 开始形成复盘资产 |
| Operation trace | `TrustedLoopResult.operation_trace` 暴露动作轨迹 | 行动可审计，不只是建议文本 |
| Action connector | `action_record` connector 具备真实写入和 rollback 能力 | 受治理行动开始有可执行载体 |
| Snapshot / rollback | L3 snapshot store 和 runtime rollback 已有 in-memory 实现 | 回滚系统进入产品主线 |
| CLI / HTTP | CLI `query`、`record-outcome`，FastAPI `/runs`、`/outcomes`，`X-API-Key` auth | 产品入口不再只有内部测试 |
| SQL Safety hardening | `SELECT *` 绕过修复已在代码和测试中出现，AR 仍为 Proposed | 技术上已推进，治理上需要收口 |

## 4. CEO 战略取舍

### 4.1 选择

- 继续以内容电商 / DTC 高频经营问题作为首个 ICP 楔子。
- 第一阶段卖“可验收业务生产闭环”，不是卖平台愿景。
- 产品核心叙事统一为 DataProduct candidate + EvidenceChain + Governed ActionProposal + Feedback/Trace + KnowledgeAsset candidate。
- 数据物理 plane 采用借力策略；公司核心资源投入 semantic / evidence / operation / knowledge contract spine。

### 4.2 拒绝

- 拒绝把 `ai-native-business-data-agent-os/` 降级为控制层、编排层或薄 pipeline。
- 拒绝为了对外展示绕过 SQL Safety、EvidenceChain、Approval、Trace 或 Eval。
- 拒绝 P0 进入完整 Data Fabric、NoETL、全连接器市场、R4/R5 自动执行。
- 拒绝把 POC 做成免费咨询或客户专属重型数据平台。

## 5. 当前风险

| 风险 | 等级 | CEO 判断 | 下一动作 |
|---|---|---|---|
| in-memory feedback / knowledge / snapshot 不能支撑生产可信闭环 | 高 | 可作为 MVP 证明，但不能作为付费生产承诺 | CTO 提出 persistent store 决策，优先 PG JSONB / SnapshotStore |
| ActionProposal 到真实 connector 的路由尚未完全产品化 | 高 | 行动闭环仍处在“有载体但未完全自动编排”阶段 | Product + CTO 定义 ActionProposalBuilder 到 connector 的边界 |
| SQL Safety hardening 仍是 Proposed review | 中 | 代码已动，治理闭环未完成 | 完成 AR 审批或转 ADR |
| CEO / HTML 报告落后于实现状态 | 中 | 影响对内阅读和对外叙事一致性 | 本次文档收束更新 |
| 实现仓库有未提交/未跟踪变更 | 中 | 不能作为稳定 release 宣称 | 开发团队跑测试、整理 commit / PR |

## 6. 30 天 CEO 优先级

| 优先级 | 决策 | Owner | 成功标准 |
|---|---|---|---|
| P0 | 把 6 月 6 日实现状态固化为可审阅 PR | CTO + Development Team | 测试绿色，AR 状态明确，README / AGENTS / CLAUDE 对齐 |
| P0 | 确定 persistent store 最小方案 | CTO | Feedback、KnowledgeAsset、Snapshot 有持久化计划和迁移边界 |
| P0 | 完成首个业务闭环 Demo 叙事 | Product + CEO | 能展示从业务问题到 EvidenceChain、ActionProposal、Feedback、KnowledgeAsset |
| P1 | 更新 POC 材料 | Business Consultant + Product | POC 承诺不超过已实现 / 验证中能力 |
| P1 | 更新投资人 brief | CEO | 明确已实现、验证中、未来假设，不夸大自动执行 |

## 7. 对外表达边界

可以说：

```text
We are building an AI-native business data and operations OS that turns business intent into trusted data products, auditable evidence, governed action proposals, feedback traces, and enterprise knowledge assets.
```

必须标注为验证中：

- Persistent enterprise memory / knowledge store。
- Production-grade rollback and workflow compensation。
- Broad connector coverage。
- High-risk business action execution。

不能说：

- 已经替代 BI / 数仓 / 数据平台。
- 已经具备完整 Agent OS。
- 已经自动执行高风险业务动作。
- 已经验证规模化付费转化。

## 8. CEO 授权

批准本轮文档收束：

- 保留原始 source-of-truth 文档位置，不做大搬迁。
- `docs/ceo/` 作为经营决策入口层。
- `CEO_Current_Product_Readiness_Brief_20260606.md` 作为当前 CEO 状态页。
- `CEO_One_Page_Brief.md` 和 CEO 精简 HTML 同步为 6 月 6 日口径。
- 后续每次实现闭环或公司级策略变化，都优先更新 CEO 当前状态页，再决定是否同步投资人 / POC / CTO 文档。
