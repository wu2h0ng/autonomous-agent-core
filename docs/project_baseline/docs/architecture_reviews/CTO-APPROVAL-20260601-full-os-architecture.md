# CTO Approval: Full OS Architecture

> Architecture Reviews:  
> - `AR-20260601-full-os-target-architecture`  
> - `AR-20260601-full-os-module-architecture`  
> - `AR-20260601-full-os-stage-architecture`  
> Decision: Approved with conditions  
> Approver: CTO  
> Date: 2026-06-01  

## 1. 审批结论

批准完整 OS 架构作为 AI Native Business Data OS 的长期目标架构和模块演进基线。

但本审批**不等于批准立即实现完整 OS**。当前工程实现仍以已批准的 `AR-20260601-mvp-trusted-loop-architecture` 为第一阶段主线。

批准范围：

- 完整 OS 的逻辑架构：Experience、Semantic、Data Product、Data Access、Evidence、Business Agent、Action Governance、Feedback、Eval、Knowledge、Extension、Control Plane。
- 完整 OS 的模块拆分和依赖方向。
- 完整 OS 的阶段演进路径 Stage 0 到 Stage 6。
- 将完整 OS 架构作为后续 ADR、repo scaffold 扩展、Agent 分工和 PR 拆分的上位依据。
- Agent OS Core、Agent Runtime、Tool Registry、Skill Registry、Agent Memory、Agent Eval、Agent Governance 必须 100% 自研；开源 Agent OS / Agent framework 仅可作为参考和对标。

不批准范围：

- 不批准一次性生成完整 OS 代码目录。
- 不批准在 Stage 1 实现完整 Data Product Compiler。
- 不批准在 Stage 1/2 自动执行业务写操作。
- 不批准在 Stage 4 前抽象通用 Domain Pack SDK。
- 不批准在 Stage 5 前承诺 Hybrid 企业部署。
- 不批准在 Stage 6 前承诺 Marketplace、完整 MCP Gateway 和完全自助生态。
- 不批准把 OpenAI Agents SDK、LangGraph、CrewAI、AutoGen、OpenHands、Goose、Cline、Aider 等作为产品 Agent OS 底座。

## 2. 强制条件

### 2.1 阶段边界

第一阶段仍按以下边界执行：

```text
BusinessQuestion
  -> BusinessIntent
  -> SemanticObject lite
  -> MetricContract
  -> ProviderContract lite
  -> DataProduct candidate
  -> SQLTemplate / QueryPlan
  -> SQLSafety
  -> QueryResult
  -> EvidenceChain
  -> Answer
  -> ActionProposal lite
  -> Approval lite
  -> Feedback / Trace
  -> KnowledgeAsset candidate
  -> Eval regression
```

任何超出上述链路的实现，必须单独提交 Architecture Design Brief。

### 2.1.1 Agent OS 自研边界

本项目可以阅读、对标和借鉴开源 Agent OS、Agent framework、coding agent、skills 项目的架构思想，但产品代码必须满足：

- 自研 AgentRuntime。
- 自研 ToolRegistry。
- 自研 SkillRegistry。
- 自研 AgentRun / Trace / Eval schema。
- 自研 Policy / Permission gate。
- 自研 Agent memory 和 project memory 规则。
- 不复制外部项目 prompt、orchestration runtime、权限模型或核心代码。
- 不让外部框架成为未来迁移不可替代的底座。

### 2.2 Contract-first

以下对象不得直接以临时代码形态散落实现：

- BusinessIntent。
- SemanticObject。
- MetricContract。
- DataRequirement。
- ProviderContract。
- DataProduct。
- EvidenceChain。
- ActionProposal。
- OperationContract。
- OperationTrace。
- FeedbackEvent。
- KnowledgeAsset。
- EvalCase。

进入对应阶段前，必须先由 Contract Agent 定义 schema、sample、compatibility tests。

### 2.3 Core 边界

OS Core 禁止依赖：

- `domain_packs/*`。
- 具体 Provider SDK。
- 具体 Action Connector SDK。
- 具体客户业务系统 SDK。
- 具体采集脚本。
- prompt 里的行业口径。

行业差异进入 Domain Pack；系统接入进入 Provider / Action Connector；客户差异进入 tenant config、pack override 或 workflow handoff。

### 2.4 风险控制

所有 R4/R5 动作必须满足：

- PolicyDecision。
- ApprovalDecision。
- OperationContract。
- dry-run 或不可 dry-run 声明。
- idempotency key。
- rollback 或 compensating action。
- OperationTrace。
- feedback metrics。

未满足这些条件时，只能生成 ActionProposal，不能执行。

### 2.5 Eval Gate

以下变化必须进入 eval：

- prompt 修改。
- 模型切换。
- SQL 模板修改。
- MetricContract 修改。
- EvidenceChain 生成逻辑修改。
- ActionProposal 或风险策略修改。
- Provider / Action Connector 行为变化。
- Domain Pack 新增或升级。

## 3. 阶段审批策略

| 阶段 | CTO 状态 | 实现策略 |
|---|---|---|
| Stage 0 | Approved | 立即可执行，产出业务问题、golden SQL、owner、风险清单 |
| Stage 1 | Approved with existing MVP conditions | 进入 PR-01 前需 PM/PM 输出 PRD、backlog、验收标准 |
| Stage 2 | Design approved, implementation gated | 需 Stage 1 的 DataProduct candidate、EvidenceChain、ActionProposal、Feedback/Trace 和 KnowledgeAsset candidate 指标达标后再开完整 DataProduct Compiler brief |
| Stage 3 | Design approved, implementation gated | 需 Stage 2 DataProduct 和 EvidenceChain v2 稳定 |
| Stage 4 | Design approved, implementation gated | 需至少第二业务域验证 Pack 复用 |
| Stage 5 | Design approved, implementation gated | 需企业试点需求和安全评审 |
| Stage 6 | Direction approved, not implementation approved | 需商业、生态、安全、运维成熟后重新审批 |

## 4. 批准启动的后续 Agent

允许启动：

- Product Manager Agent：补齐 MVP PRD、feature map、workflow specs。
- Project Manager Agent：补齐 backlog、roadmap、sprint plan、risk register。
- Contract Agent：准备 PR-01 Contracts brief。
- Eval Agent：整理 Stage 0/1 golden query 和 golden loop。
- Security Governance Agent：定义 R0-R5 风险等级和 Stage 1 安全红线。

暂不允许启动：

- Full Platform Implementation Agent。
- Marketplace Agent。
- Full MCP Gateway Agent。
- Full Private Deployment Agent。
- High-risk Action Execution Agent。

## 5. 必须更新的工程记忆

本审批后，项目记忆必须记录：

1. 完整 OS 是目标架构，不是第一阶段交付范围。
2. MVP Trusted Loop 已升级为最小业务生产闭环，是当前实现基线。
3. 后续每个阶段开启前必须过 CTO Gate。
4. Core / Domain Pack / Provider / Action Connector 的依赖边界不可破坏。
5. 无 EvidenceChain 的答案不能进入正式业务决策。
6. 无 OperationTrace 的动作不能进入自动执行。

## 6. 下一步

下一步不是写完整 OS 代码，而是：

1. Product Manager Agent 输出 Stage 1 PRD 和验收标准。
2. Project Manager Agent 输出 Stage 1 backlog 和 sprint plan。
3. Architecture Agent 针对 PR-01 Contracts 输出小范围实现 brief。
4. CTO 审批 PR-01 brief 后，才允许 Contract Agent 开始实现。
