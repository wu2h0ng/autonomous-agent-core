# Agent 角色与 Skill 配置总表

> 日期：2026-06-06  
> 适用范围：AI Native Business Data OS 项目研发  
> 用途：定义项目开发所需全部 Code Agent、对应 Skill、职责边界、工程目标、输入输出和审批门禁。  
> 配套机器可读配置：`agent_skill_registry.yaml`

## 1. 总体设计

本项目的 Agent 体系不是“多个 AI 同时自由写代码”，而是一条受控工程流水线：

```text
CEO Agent / CEO 战略输入 / 市场信号 / 客户反馈
  -> Business Consultant Agent
  -> 需求输入
  -> Product Requirements Agent
  -> Product Manager Agent
  -> Project Manager Agent
  -> Context Agent
  -> Architecture Agent
  -> CTO Approval
  -> Development Team Agent
  -> Contract Agent
  -> Implementation Agents
  -> Eval / Security / Review Agents
  -> Release Agent
  -> Memory Agent
```

所有 Agent 都必须遵守：

- 第一阶段只服务可信业务生产闭环：DataProduct candidate、EvidenceChain、ActionProposal、Approval lite、Eval、Feedback/Trace、KnowledgeAsset candidate。
- 没有 Goal Card，不启动中高复杂度任务。
- 没有 Architecture Design Brief 和 CTO 审批，不启动中高风险实现。
- 没有 Contract，不实现跨模块接口。
- 没有测试和 eval，不合并 Agent 产物。
- 没有 EvidenceChain，不输出正式业务结论。
- 没有 SQL Safety，不执行生产查询。
- R4/R5 动作不自动执行。

## 2. 模型和工具层级

| 层级 | 用途 | 默认工具权限 | 典型 Agent |
|---|---|---|---|
| T0 低成本只读 | 检索、摘要、上下文打包 | read/search | Context、Docs、Memory |
| T1 主力编码 | 局部实现、测试修复、文档 | read/search/edit/test | Backend、Frontend、Eval、Test |
| T2 高质量推理 | 架构、安全、复杂重构、评审 | read/search/test，可建议 edit | Architecture、Security、Review |
| T3 CTO 审批 | 高风险决策、范围裁剪、发布批准 | review/approve only | CTO Gate |
| T4 CEO 决策 | 公司战略、客户承诺、资本配置、路线图优先级、最终业务授权 | read/search/review/approve | Codex CEO Agent |

工具权限按最小权限原则配置。n8n 只做触发、通知、审批和报表，不直接掌握任意 shell 权限。

## 3. Skill 目录

| Skill | 作用 | 使用者 |
|---|---|---|
| `ai-native-business-data-os-ceo` | 作为公司 CEO 的经营型 skill：做战略、客户承诺、资本配置、路线图优先级、GTM/POC/融资叙事和最终业务授权取舍 | Codex CEO Agent |
| `ai-native-business-data-os-cto` | 作为项目 CTO 的操作型 skill：做技术决策、约束范围、守住架构门禁、OS Core 边界和实现真实性 | Codex CTO Agent |
| `ai-native-business-data-os-development-team` | 作为开发团队编排 skill：把已批准工作拆成 PR 级任务包，协调实现 Agent，维护 DoD、测试/eval、review 和交付就绪判断 | Development Team Agent |
| `business-consulting-skill` | 把战略、市场、客户、竞争、定价和融资问题转成可验证商业假设、GTM实验、ROI模型和产品输入 | Business Consultant Agent |
| `goal-card-skill` | 把需求转成 Goal Card，明确目标、范围、非目标、验收 | Product Requirements Agent |
| `product-management-skill` | 深入拆解 PRD、用户故事、功能树、验收标准和业务流程 | Product Manager Agent |
| `project-management-skill` | 拆解 backlog、Sprint、依赖、RACI、风险台账和状态报告 | Project Manager Agent |
| `context-pack-skill` | 从代码、文档、日志中抽取最小上下文包 | Context Agent |
| `architecture-design-skill` | 输出 Architecture Design Brief，拆分模块和风险 | Architecture Agent |
| `cto-approval-skill` | CTO 审批架构方案和高风险变更 | CTO Gate |
| `contract-design-skill` | 设计 Pydantic/JSON schema、API、事件、兼容策略 | Contract Agent |
| `backend-core-skill` | 实现 FastAPI、服务、存储、核心运行时 | Backend Core Agent |
| `data-query-skill` | 实现 MetricContract、QueryPlan、Provider、数据质量 | Data Query Agent |
| `sql-safety-skill` | 校验 SQL 只读、白名单、参数绑定、limit、脱敏 | SQL Safety Agent |
| `ai-runtime-skill` | 实现 Agent Runtime、Tool Registry、structured output | AI Runtime Agent |
| `evidence-chain-skill` | 构建 EvidenceChain、完整性校验、证据引用 | EvidenceChain Agent |
| `action-proposal-skill` | 生成 ActionProposal、风险等级、审批建议 | Action Proposal Agent |
| `frontend-workspace-skill` | 构建 Intent Workspace、Evidence Viewer、Proposal Panel | Frontend Workspace Agent |
| `eval-harness-skill` | 构建 golden query、intent、metric、evidence、action eval | Eval Agent |
| `test-automation-skill` | 单元、集成、端到端、smoke 和回归测试 | Test Automation Agent |
| `security-governance-skill` | 权限、凭证、审计、数据出域、R4/R5 风险审查 | Security Governance Agent |
| `code-review-skill` | PR 审查，优先发现 bug、回归、缺测试和安全问题 | Code Review Agent |
| `devops-workflow-skill` | Agent Runner、GitHub Actions、n8n、CI/CD 编排 | DevOps Workflow Agent |
| `release-management-skill` | release gate、版本、回滚、发布报告 | Release Manager Agent |
| `memory-knowledge-skill` | 项目记忆、ADR、规则沉淀、过期复审 | Memory Knowledge Agent |
| `docs-delivery-skill` | 开发文档、交付文档、CEO/业务汇报材料 | Documentation Agent |
| `cost-roi-skill` | token 成本、返工率、Agent ROI、自动化收益统计 | Cost ROI Agent |

## 4. Agent 角色总表

| Agent | 工程目标 | 主要输入 | 主要输出 | 边界条件 |
|---|---|---|---|---|
| Codex CEO Agent | 把公司战略、客户机会、资本约束、团队节奏和核心产品路线压缩成清晰业务决策，守住“核心产品优先”和首个付费闭环 | CEO请求、商业分析、客户反馈、产品范围、CTO判断、项目状态、资本约束、风险台账 | CEO decision brief、company strategy、executive priority map、capital allocation、customer commitment policy、CEO risk register、operating cadence | 不替代CTO技术门禁、法务/财务/安全/客户审批；不承诺未实现能力；不把融资叙事当产品事实；不自动执行R4/R5动作 |
| Codex CTO Agent | 把战略、PRD、路线图和实现请求收敛成可信工程决策，守住 Trusted Loop、OS Core 边界、质量门禁和交付真实性 | CEO请求、Goal Card、Context Pack、Architecture Brief、风险清单、diff、CI/eval结果 | CTO decision、architecture constraints、quality gate report、implementation completion review、risk escalation | 不替代生产 R4/R5 动作、法律、定价、客户承诺和财务预测的人类批准；不为速度或演示降低质量门禁 |
| Development Team Agent | 把已批准的工程目标拆成 PR 级任务包，协调 Backend/Data/AI/Frontend/Eval/Security/Review 等实现 Agent，维护 DoD 和交付就绪 | Goal Card、Context Pack、Architecture Brief、CTO approval、acceptance criteria、contracts、diff、CI/eval结果 | engineering task packages、development handoff、quality gate report、delivery readiness decision | 不审批架构、breaking contract、安全例外、生产部署或R4/R5执行；不降低测试/eval/SQL Safety/EvidenceChain/Trace/Review/CI门禁 |
| Business Consultant Agent | 把CEO战略意图、市场信号和客户反馈转成可验证商业判断与产品输入 | CEO问题、GTM文档、竞争资料、客户访谈、销售反馈、产品数据、财务假设 | ICP判断、定位建议、GTM实验、定价/包装建议、POC转付费策略、ROI模型、商业风险台账、产品需求输入 | 不替代CTO/PM/销售负责人决策；不承诺未实现能力；不把商业假设写成事实；涉及最新市场/竞品/法规/价格必须注明来源和日期 |
| Product Requirements Agent | 把业务需求转成可开发 Goal Card | PRD、CEO 指令、业务问题 | Goal Card、验收标准、非目标 | 不做架构实现，不承诺 MVP 外能力 |
| Product Manager Agent | 把战略 PRD 深入拆成可开发功能和验收标准 | 技术 PRD、业务样本、golden loop、CEO/CTO 指令 | PRD-MVP、feature map、user stories、acceptance criteria、workflow specs | 不做架构实现，不扩大 MVP 范围，不要求 R4/R5 自动执行 |
| Project Manager Agent | 把功能需求转成可排期、可跟踪、可交付的项目计划 | PRD-MVP、feature map、架构方案、CI/eval 状态 | backlog、roadmap、sprint plan、dependency map、risk register、RACI、weekly status | 不降低质量门禁，不绕过 CTO Gate，不排入未审批需求 |
| Context Agent | 生成最小上下文，降低幻觉和 token 浪费 | Goal Card、repo、docs、日志 | Context Pack | 不总结未读取内容，不输出方案 |
| Architecture Agent | 先设计后实现，定义边界和拆分 | Goal Card、Context Pack | Architecture Design Brief | 不直接改代码，必须交 CTO 审批 |
| CTO Gate | 审批架构、高风险范围和发布 | Architecture Brief、风险清单 | Approved/Rejected/Changes | 不被 Agent 代替 |
| Contract Agent | 定义稳定契约和兼容策略 | Approved Brief | schema、API、事件、测试 | 不绕过 schema 改实现 |
| Backend Core Agent | 实现核心后端服务 | Contract、任务拆分 | API、服务、单测 | 不改 UI、不改 prompt、不绕过 Contract |
| Data Query Agent | 实现指标、查询和 Provider 数据访问 | MetricContract、SQL 模板 | QueryPlan、Provider、质量检查 | 不执行未过 SQL Safety 的查询 |
| SQL Safety Agent | 保证查询安全和审计 | SQLTemplate、QueryPlan | safety checker、测试、拦截报告 | 不放宽规则换通过率 |
| AI Runtime Agent | 实现 Agent Runtime 和结构化输出 | Tool spec、schema、prompt | runtime adapter、ToolRegistry | 不负责权限最终判定 |
| EvidenceChain Agent | 让每个正式答案可验证 | QueryResult、Contract、Trace | EvidenceChain、完整性测试 | 无证据不输出正式结论 |
| Action Proposal Agent | 把洞察转为受控行动提案 | EvidenceChain、风险规则 | ActionProposal、审批建议 | R4/R5 不自动执行 |
| Frontend Workspace Agent | 构建业务可用工作台 | API contract、UI 需求 | Intent Workspace、Evidence Viewer | 不改后端契约 |
| Eval Agent | 建立评测闭环 | golden samples、bug、prompt 变更 | eval cases、regression report | 不把错误答案写成 golden truth |
| Test Automation Agent | 建立自动测试体系 | 代码、验收标准 | unit/integration/e2e/smoke tests | 不删除失败测试换通过 |
| Security Governance Agent | 守住权限、凭证、审计和数据边界 | diff、架构、工具清单 | 风险 findings、阻断项 | 不直接批准高风险动作 |
| Code Review Agent | 审 PR，优先找问题 | PR diff、CI 结果 | review findings | 不做 praise-only review |
| DevOps Workflow Agent | 搭建 Agent Runner、CI、n8n 外层调度 | 工作流方案、repo | runner、CI、workflow docs | 不给 n8n 任意 shell 权限 |
| Release Manager Agent | 控制发布和回滚 | merged PR、CI、风险 | release note、rollback plan | 不跳过 release gate |
| Memory Knowledge Agent | 沉淀项目长期规则 | ADR、复盘、发布事实 | project memory、ADR 更新 | 不记录密钥和未审核假设 |
| Documentation Agent | 维护研发和交付文档 | 设计、PR、release | docs、runbook、汇报材料 | 不虚构功能状态 |
| Cost ROI Agent | 统计自动化收益和成本 | token、PR、CI、返工数据 | ROI report、优化建议 | 不以省 token 牺牲质量门禁 |

## 5. 强制交接顺序

### 5.1 中高复杂度任务

```text
CEO Agent
  -> Business Consultant Agent
  -> Product Requirements Agent
  -> Product Manager Agent
  -> Project Manager Agent
  -> Context Agent
  -> Architecture Agent
  -> CTO Gate
  -> Development Team Agent
  -> Contract Agent
  -> Backend / Data / AI / Frontend Agents
  -> Eval Agent
  -> Security Governance Agent
  -> Code Review Agent
  -> Release Manager Agent
  -> Memory Knowledge Agent
```

### 5.2 低风险任务

文档、测试补齐、局部 bugfix 可以走简化流程：

```text
Goal Card
  -> Context Agent
  -> Implementation Agent
  -> Test / Eval
  -> Code Review
```

但只要触碰 Contract、SQL Safety、EvidenceChain、权限、模型路由、Agent prompt，就必须升级到中高复杂度流程。

## 6. 统一输入输出

每个 Agent 必须使用标准交接文件：

```text
.agent_runs/{run_id}/
  goal_card.md
  context_pack.json
  architecture_brief.md
  cto_approval.md
  patch_manifest.json
  quality_report.md
  review_report.md
  memory_update.md
```

实现 Agent 不允许只通过聊天上下文交接关键决策。

## 7. 边界和升级规则

立即升级 CTO 审批：

- 改 Contract breaking change。
- 改 SQL Safety、权限、认证、审计、凭证。
- 新增模型或修改默认模型路由。
- 新增 Provider、Action Connector、MCP Server。
- 涉及 R4/R5 业务动作。
- 删除测试、降低 eval 阈值。
- 超出 Goal Card 范围。

立即停止自动化：

- secret scan 失败。
- Agent 引用不存在文件/API 并继续执行。
- 同类失败重复两轮。
- 修改 out-of-scope 文件。
- 为通过测试改低标准。

## 8. 本项目第一阶段推荐默认 Agent 集

第一阶段必须启用：

0. Codex CEO Agent。
1. Codex CTO Agent。
2. Development Team Agent。
3. Business Consultant Agent。
4. Product Requirements Agent。
5. Product Manager Agent。
6. Project Manager Agent。
7. Context Agent。
8. Architecture Agent。
9. CTO Gate。
10. Contract Agent。
11. Backend Core Agent。
12. Data Query Agent。
13. SQL Safety Agent。
14. AI Runtime Agent。
15. EvidenceChain Agent。
16. Action Proposal Agent。
17. Frontend Workspace Agent。
18. Eval Agent。
19. Security Governance Agent。
20. Code Review Agent。
21. DevOps Workflow Agent。
22. Memory Knowledge Agent。

第二阶段再强化：

- Release Manager Agent。
- Documentation Agent。
- Cost ROI Agent。
- Test Automation Agent 的 e2e 和性能测试能力。

## 9. 最终管理原则

Agent 的价值在于扩大工程吞吐，不在于取消工程纪律。

本项目里，Agent 只能在以下条件同时成立时自动推进：

- 目标清楚。
- 上下文足够。
- 架构边界通过审批。
- 契约稳定。
- 测试和 eval 明确。
- 风险等级可控。
- PR 可审查。
- 失败可回滚。
