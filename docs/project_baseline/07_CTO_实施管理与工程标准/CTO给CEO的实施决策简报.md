# CTO 给 CEO 的实施决策简报

> 日期：2026-06-01  
> 项目：AI Native Business Data OS  
> 汇报人：CTO  
> 用途：供 CEO 做阶段投入、首发场景、组织资源和风险边界决策。

## 1. 执行结论

长期方向成立，但第一版必须收敛。当前方案不应按“完整商业数据操作系统”一次性研发，也不应过早承诺 Marketplace、全私有化、全自动 Business Agent、全量 MCP Gateway、复杂工作流和跨行业通用。

第一阶段建议定位为：

**可信业务生产闭环工作台。**

它解决的是企业业务团队最先愿意付费的问题：

- 提数和诊断从数天/数周降到小时级。
- 指标口径有 owner、有契约、有证据。
- AI 输出可追溯、可复盘、可评测。
- 洞察能转成行动提案、审批单或任务，而不是停在回答文本。
- 失败样本能进入回归评测，系统越用越稳。

CEO 需要批准的核心边界是：**第一版只做可信闭环，不做高风险自动执行业务写操作。**

## 2. 战略判断

现有文档中的长期产品北极星是正确的：

```text
Business Intent
  -> Data Agent
  -> Trusted Data Product / EvidenceChain
  -> Business Agent
  -> Governed Business Operation
  -> Operational Feedback
```

这个方向的价值不在“少写 SQL”，而在把数据从被动报表变成业务生产系统的可信输入。

但商业化起点不能是“OS”。客户早期买的是可感知结果：

| 客户痛点 | 第一阶段产品表达 |
|---|---|
| 数据需求排期慢 | 自然语言问数 + 可复现查询 |
| 指标口径反复争议 | MetricContract + 口径 owner |
| AI 回答不可信 | EvidenceChain + 质量检查 |
| 看板只展示不行动 | ActionProposal + 审批建议 |
| Agent 项目难上线 | SQL Safety + Eval + Trace |

## 3. 推荐首发场景

建议首发场景选择 **内容电商经营 / 投放效率诊断**，理由如下：

- 已有 30 个高频业务问题样本。
- 已有 20 条 golden SQL 查询模板。
- 已有 3 条 golden business loop。
- ROI、GMV、CAC、转化率、库存周转等指标可量化。
- 行动建议可以先以提案、审批单、任务形式落地，避免高风险自动执行。

首发业务闭环优先级：

1. 投放效率诊断：ROI 下降、低效计划识别、预算调整建议。
2. 爆款内容挖掘：内容排行、标签/达人/发布时间特征、策略建议。
3. 日报全景扫描：GMV、ROI、转化率、异常指标、下钻诊断。

## 4. 12 个月实施路线

| 阶段 | 周期 | 目标 | CEO 关注点 |
|---|---:|---|---|
| 阶段 0：场景和数据准备 | 2-4 周 | 确认首发业务域、指标、数据源、owner、golden cases | 是否具备真实落地条件 |
| 阶段 1：可信业务生产闭环 MVP | 1-3 个月 | BusinessIntent -> DataProduct candidate -> EvidenceChain -> ActionProposal -> Approval lite -> Feedback/Trace -> KnowledgeAsset candidate | 是否能让业务 owner 持续使用并沉淀可复用资产 |
| 阶段 2：DataProduct v1 | 3-6 个月 | 高频数据需求沉淀为可复用数据产品 | 是否减少重复数据开发 |
| 阶段 3：提案型 Business Agent | 6-9 个月 | 洞察 -> 行动提案 -> 审批/任务 -> 反馈 | 是否从分析进入业务动作 |
| 阶段 4：Domain Pack 产品化 | 9-12 个月 | 首发场景可复制到第二业务域 | 是否具备产品化和销售复制能力 |

阶段推进采用门槛制，不按日历自动进入下一阶段。

## 5. MVP 范围

P0 必须交付：

- BusinessIntent。
- SemanticObject lite。
- MetricContract。
- ProviderContract lite。
- DataProduct candidate。
- SQL Template / SQL Safety。
- EvidenceChain。
- Golden query eval。
- Intent / metric eval。
- ActionProposal。
- Approval lite。
- Trace lite。
- 业务反馈表。
- KnowledgeAsset candidate。
- Intent Workspace、DataProduct View、EvidenceChain Viewer、ActionProposal Panel 和 KnowledgeAsset Review。

P1 轻实现：

- OperationContract lite。
- PolicyEngine 抽象。
- RiskLevel 规则。
- OperationTrace lite。
- Model Gateway 最小调用日志。

P2 延后：

- Marketplace。
- 完整 Domain Pack SDK。
- 完整 MCP Gateway。
- Temporal 全量工作流。
- OPA 全量策略引擎。
- OpenLineage 全量接入。
- 完整私有化和 Air-gapped。
- 高风险业务写操作自动执行。

## 6. 成功指标

MVP 不以“功能数量”验收，以可信闭环验收。

| 指标 | 阶段目标 |
|---|---:|
| 高频问题覆盖率 | 60%-70% |
| golden query 正确率 | >= 85% |
| 核心指标口径命中率 | >= 90% |
| 正式答案 EvidenceChain 覆盖率 | 100% |
| SQL 写操作拦截率 | 100% |
| 非白名单 schema 拦截率 | 100% |
| 行动提案证据引用覆盖率 | 100% |
| 失败样本进入 eval 比例 | >= 90% |
| 端到端 trace 可回放率 | 100% |
| 相似问题交付时间 | 较人工方式降低 50% 以上 |

## 7. 组织和资源建议

最小可执行团队：

| 角色 | 人数 | 关键职责 |
|---|---:|---|
| Product Owner | 1 | 首发场景、业务优先级、验收口径 |
| Domain Expert | 1 | 指标解释、业务问题、行动建议校验 |
| Data Engineer | 1 | 数据源、SQL 模板、数据质量、golden query |
| Backend / Platform Engineer | 1-2 | API、契约、SQL Safety、Trace、权限 |
| AI / Agent Engineer | 1 | Agent runtime、结构化输出、prompt/skill、Model Gateway |
| Frontend Engineer | 1 | Intent Workspace、DataProduct View、EvidenceChain、ActionProposal、KnowledgeAsset Review UI |
| QA / Eval Engineer | 1 | eval harness、回归集、CI gates |
| Security / Governance Reviewer | 兼职 | 风险分级、权限、审计、凭证、数据出域 |
| Solution Engineer | 兼职 | 业务试点、反馈、交付材料 |

建议前 90 天采用小队制，研发负责人直接向 CTO 汇报，业务 owner 每周参与评测会。

## 8. 关键风险和控制

| 风险 | 表现 | 控制策略 |
|---|---|---|
| MVP 过载 | 平台模块很多，业务价值不尖 | 所有需求按 P0/P1/P2 分层，P2 不进主路径 |
| AI 输出不可信 | 回答正确率不稳定，无法上线 | EvidenceChain、golden eval、失败样本回归 |
| SQL 和数据安全风险 | 越权查询、写操作、敏感字段泄露 | 只读 SQL、白名单 schema、参数绑定、脱敏、审计 |
| 指标口径冲突 | 业务方不信结果 | MetricContract、owner、版本和口径 review |
| 过早业务写操作 | Agent 误操作预算/库存/客户数据 | 第一版只提案，R4/R5 强审批且不自动执行 |
| 连接器泥潭 | 被大量平台 API 适配拖慢 | 只接首发闭环必要 Provider 和 Action |
| 私有化承诺过早 | 交付和运维成本失控 | 先做 SaaS/Hybrid 边界，不承诺 Air-gapped |
| 团队流程失控 | Code Agent 快速生成但不可维护 | Contract-first、PR checklist、eval gate、review gate |

## 9. CEO 需要决策

1. 是否批准第一阶段定位为“可信业务生产闭环工作台”，而不是完整 OS。
2. 是否批准首发场景为“内容电商经营 / 投放效率诊断”。
3. 是否指定一个强业务 owner 和一个数据 owner 进入每周评测机制。
4. 是否批准第一版不做高风险自动写操作，只做 ActionProposal、审批建议和任务。
5. 是否批准 90 天最小小队资源配置。
6. 是否接受“没有 EvidenceChain 的输出不得进入正式业务决策”的产品原则。
7. 是否接受“没有 eval 的 Agent 能力不得进入生产”的工程原则。

## 10. CTO 建议

建议批准进入阶段 0 和阶段 1，预算和资源按 90 天小队配置执行。

90 天后只看六件事：

1. 业务 owner 是否每周持续使用。
2. 20 条 golden query 是否稳定。
3. 正式答案是否 100% 有 EvidenceChain。
4. 至少 5 个 DataProduct candidate 是否被复用或复核。
5. 行动提案是否真实被采纳或转成任务。
6. 至少 3 个 KnowledgeAsset candidate 是否进入人工 review。

如果这些条件达不到，不进入平台化；如果达标，再进入 DataProduct Compiler 和提案型 Business Agent 的产品化阶段。

---

## 11. 团队能力缺口分析与招聘优先级

> 补充来源：深度分析报告 — 组织层补充。

### 11.1 MVP阶段核心能力优先级

**P0 - 必须内部拥有（MVP阶段必须到位）**

| 角色 | 能力要求 | 人数 | 招聘优先级 |
|---|---|---|---|
| 数据语义建模 | 理解业务语义层、MetricContract设计、数据口径治理经验 | 1 | 最高 |
| AI工程 | Prompt工程、结构化输出、eval框架、模型评估 | 1-2 | 最高 |
| 后端架构 | FastAPI、Contract设计、异步任务、数据库 | 1-2 | 最高 |

**P1 - 早期可兼顾但需要规划专人**

| 角色 | 能力要求 | 人数 | 招聘时机 |
|---|---|---|---|
| 前端工程 | Intent Workspace、DataProduct View、EvidenceChain展示、ActionProposal、KnowledgeAsset Review、React/TypeScript | 1 | 阶段1后期 |
| 数据工程 | ProviderContract实现、SQL安全、查询执行优化 | 1 | 阶段1中期 |
| 产品设计 | 用户旅程、UX设计、商业化逻辑、客户访谈 | 1 | 阶段1初期 |

**P2 - 规模化后再建设**

| 角色 | 能力要求 | 招聘时机 |
|---|---|---|
| 安全合规 | 企业级RBAC、审计、部署安全、合规认证 | 阶段2 |
| 客户成功 | 参照客户阶段由创始团队承担 | 阶段2 |
| 销售 | 首批客户由创始人直售 | 阶段2 |

### 11.2 MVP最小团队配置（8-12人）

```text
创始人/CEO（兼产品方向决策 + 首批销售）
CTO（兼后端架构 + AI工程方向）
├── 后端工程师 x2（Core + API开发）
├── AI工程师 x2（Intent解析 + SQL生成 + Eval）
├── 前端工程师 x1（Workspace UI）
├── 数据工程师 x1（Provider + SQL Safety + 查询执行）
└── 产品设计师 x1（UX + 客户访谈 + 商业化）
```

### 11.3 AI伦理与负责任AI角色

随着产品从"回答问题"走向"驱动业务动作"，AI伦理不是可选项而是必要条件：

| 职责 | 归属 | 优先级 |
|---|---|---|
| 模型输出偏见监控 | AI工程师（阶段1）→ 专职伦理负责人（阶段2+） | P1 |
| ActionProposal公平性审查 | Policy Engine + 人工复核 | P1 |
| 数据隐私影响评估 | CTO（阶段1）→ 安全合规负责人（阶段2+） | P1 |
| 可解释性报告 | EvidenceChain自动生成 | P0 |
| 伦理审查委员会 | 阶段2+建立，含外部顾问 | P2 |

核心原则：
1. 不做"黑箱决策"：每个ActionProposal必须可追溯到EvidenceChain
2. 不做"算法歧视"：指标定义和阈值必须经过公平性审查
3. 不做"隐私侵犯"：数据使用必须在客户授权范围内
