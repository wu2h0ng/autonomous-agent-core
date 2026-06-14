# CTO Approval: MVP Trusted Loop Architecture

> Architecture Review: `AR-20260601-mvp-trusted-loop-architecture`  
> Decision: Approved with conditions  
> Approver: CTO  
> Date: 2026-06-01  

## 1. 审批结论

批准该架构作为第一阶段实现基线，但有条件通过。

批准范围：

- 使用 `repo_scaffold/README.md` 定义的目标结构。
- 以可信业务生产闭环为第一阶段唯一工程主线。
- 优先实现 Contract、DataProduct candidate、SQL Safety、Query Runtime、EvidenceChain、ActionProposal、Approval lite、Feedback/Trace、KnowledgeAsset candidate、Eval、API、UI。
- Agent Runtime、ToolRegistry、AgentRunContext、Agent Trace、Agent 权限边界必须 100% 自研。OpenAI Agents SDK、LangGraph、CrewAI、AutoGen、OpenHands、Goose 等只允许作为参考，不允许作为产品 Core 运行时依赖。
- R4/R5 业务动作第一阶段只允许生成提案和审批建议，不允许自动执行。

不批准范围：

- 不批准完整 OS 平台化。
- 不批准 Marketplace。
- 不批准完整私有化或 Air-gapped。
- 不批准高风险业务写操作自动执行。
- 不批准绕过 SQL Safety 的查询执行路径。
- 不批准无 EvidenceChain 的正式业务答案。
- 不批准以任何开源 Agent OS / Agent framework 作为本项目 Agent OS 底座。

## 2. 必须满足的前置条件

进入 PR-01 之前，必须完成：

1. Product Manager Agent 产出：
   - `docs/product/PRD-MVP.md`
   - `docs/product/feature_map.md`
   - `docs/product/acceptance_criteria.md`
   - `docs/product/workflow_specs/roi_diagnosis.md`
   - `docs/product/workflow_specs/hit_content_discovery.md`
   - `docs/product/workflow_specs/daily_report.md`

2. Project Manager Agent 产出：
   - `docs/project/backlog.md`
   - `docs/project/roadmap_90d.md`
   - `docs/project/sprint_plan.md`
   - `docs/project/risk_register.md`
   - `docs/project/raci.md`

3. Contract Agent 准备：
   - P0 Contract 清单。
   - schema test plan。
   - migration policy。

## 3. Implementation Agents Approved

| Agent | Approved | Conditions |
|---|---|---|
| Product Manager Agent | yes | 必须先输出 MVP PRD 和验收标准 |
| Project Manager Agent | yes | 必须输出 backlog、roadmap、risk register |
| Contract Agent | yes | 只能在 PRD/backlog 完成后启动 |
| Backend Core Agent | yes | 只能实现 CTO 批准的 PR 范围 |
| Data Query Agent | yes | 所有查询路径必须走 SQL Safety |
| SQL Safety Agent | yes | P0 gate，不得延后 |
| AI Runtime Agent | yes | 必须通过 adapter，prompt 不承担权限逻辑 |
| EvidenceChain Agent | yes | P0 gate，不得延后 |
| Action Proposal Agent | yes | R4/R5 proposal-only |
| Frontend Workspace Agent | yes | 不得隐藏 evidence limitations |
| Eval Agent | yes | P0 gate，不得延后 |
| Security Governance Agent | yes | 必须审 SQL/model/provider/action/deployment 风险 |
| Code Review Agent | yes | PR findings first |

## 4. Required Gates

所有实现 PR 必须至少匹配相关门禁：

- unit tests
- schema tests
- SQL Safety tests
- golden query tests
- intent / metric eval
- EvidenceChain completeness tests
- action risk tests
- frontend smoke
- secret scan
- dependency scan

P0 gates：

```text
schema
sql safety
evidence completeness
eval
trace
action risk
```

## 5. PR 顺序批准

批准以下 PR 顺序：

1. Contracts。
2. SQL Safety。
3. Query Runtime + Provider。
4. EvidenceChain。
5. ActionProposal + Approval lite。
6. Eval Hub。
7. API Server。
8. Web Workspace。
9. Agent Runtime Adapter。

任何调整顺序都必须说明原因。不得把 SQL Safety、EvidenceChain、Eval 延后到最后补。

## 6. 风险接受

接受的风险：

- 第一阶段使用轻量 PolicyEngine，不直接引入 OPA。
- 第一阶段使用应用内 Trace + OpenTelemetry-compatible TelemetryEvent，不强制部署完整 OpenTelemetry 平台。
- 第一阶段只用一个首发 Domain Pack，不做完整 Domain Pack SDK。
- 第一阶段 pgvector 可选，不作为闭环阻塞项。

不接受的风险：

- Agent 生成 SQL 后直接执行。
- Prompt 负责权限判断。
- 无 eval 修改模型或 prompt。
- n8n 直接执行任意 shell 改代码或部署。
- 业务动作绕过人工审批。

## 7. Required Changes

架构进入实现前，需要补齐：

1. `docs/product/` 目录下的 MVP 产品拆解。
2. `docs/project/` 目录下的 90 天项目计划。
3. `docs/architecture_reviews/` 中针对 PR-01 Contracts 的更细 brief。
4. CI 最小门禁定义。

## 8. Notes

本审批不是批准立即大规模生成代码。它批准的是第一阶段架构基线和实现顺序。

下一步应由 Product Manager Agent 和 Project Manager Agent 先补齐开工输入，然后 Architecture Agent 为 PR-01 输出细化 brief，最后 Contract Agent 开始实现。
