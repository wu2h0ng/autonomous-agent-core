# Code Agent 全面开发治理方案

> 日期：2026-06-01  
> 角色视角：CTO  
> 适用范围：AI Native Business Data OS 第一阶段及后续平台化研发  
> 目标：在全面使用 Code Agent 的前提下，最大化交付质量、降低幻觉和返工、控制 token 成本，并形成可持续的软件工程管理体系。

## 1. 总体结论

全面使用 Code Agent 可行，但不能把 Code Agent 当成“自由开发者”。正确方式是把它们纳入标准软件工程系统：

```text
Goal Card
  -> Context Pack
  -> Agent Role
  -> Contract / Test / Eval
  -> Implementation
  -> Automated Gate
  -> Human Review
  -> Release
  -> Project Memory
```

第一原则：

- Agent 不直接决定产品边界。
- Agent 不绕过 Contract、测试、评测和审计。
- Agent 不在同一任务中无边界修改大面积代码。
- Agent 不靠模型自信替代事实来源。
- 人类 owner 对 PR 和生产发布负责。

## 2. 推荐工具组合

### 2.1 主组合

| 用途 | 推荐 | 定位 |
|---|---|---|
| 主力异步开发 Agent | OpenAI Codex / Codex CLI | 复杂功能、跨文件修改、重构、测试修复、PR 准备 |
| 日常 AI IDE | Cursor | 人类工程师主工作台，适合 Ask/Agent/Manual/Custom 模式切换 |
| GitHub 任务型 Agent | GitHub Copilot cloud agent | 适合从 issue/PR 触发小到中等任务，借助 GitHub Actions 临时环境跑测试 |
| 第二意见 / 深度审查 | Claude Code | 用于架构复核、安全复核、复杂重构前第二意见，不作为唯一实现路径 |
| 全托管长任务试点 | Devin | 仅用于隔离实验、低风险 backlog、长任务探索，不进入核心路径默认值 |
| IDE 备用 | VS Code + GitHub Copilot | 团队成员不使用 Cursor 时的兼容路径 |

### 2.2 为什么这样选

OpenAI Codex 适合作为主力，因为它定位为可以完成真实工程任务的 coding agent，覆盖功能开发、复杂重构和迁移。Cursor 作为 IDE 适合日常人机协作，并且支持 Agent、Ask、Manual、Custom 等模式；其中 Ask 适合只读理解，Agent 适合复杂改动，Manual 适合精确编辑。GitHub Copilot cloud agent 的优势在于 GitHub Actions 临时环境和 issue/PR 工作流集成。Claude Code 与 Devin 作为第二路径，重点用于复核、试验和补充能力，避免形成多套主流程。

## 3. 模型选择和路由

### 3.1 模型分层

| 场景 | 推荐模型/能力 | 成本策略 |
|---|---|---|
| 架构设计、复杂跨模块重构、安全关键 review | GPT-5.5 或当前最高质量 reasoning/coding model | 高成本可接受，要求输出设计依据和验证计划 |
| 主力代码实现、测试修复、PR 准备 | Codex 当前默认/最新 coding model | 作为主开发路径，按任务拆分控制上下文 |
| 普通 bugfix、脚手架、文档、局部测试 | 当前 mini/低成本 coding 或 general model | 使用较低 reasoning effort，必须跑测试 |
| 只读代码解释、检索、摘要 | 低成本模型 + repo 检索 | 不允许直接修改代码 |
| Prompt/Skill 草拟、测试样本生成 | 低成本模型初稿，高质量模型抽检 | 用 eval 和 reviewer 防止样本污染 |
| 安全和权限高风险判断 | 高质量模型 + 人类安全 reviewer | 模型只给建议，不做最终授权 |
| 项目记忆检索 | embedding + 低成本摘要模型 | 只注入相关片段，不喂全仓库 |

### 3.2 OpenAI API 模型建议

若需要在自研工具链、评测平台或内部 Agent Gateway 中直接调用模型：

- 默认高质量推理：`gpt-5.5`。
- 高风险架构和安全审查：`gpt-5.5`，reasoning effort 使用 `high` 或 `xhigh`。
- 普通 structured output、文档、低风险代码辅助：优先使用当前 mini 级模型。
- 嵌入和项目记忆：`text-embedding-3-small` 作为默认成本优先，`text-embedding-3-large` 用于高召回质量要求。
- 不在业务代码中硬编码模型名，通过 `Model Gateway` 做模型路由、预算、日志和回退。

### 3.3 模型路由规则

```yaml
model_router:
  architecture_review:
    model: frontier_reasoning
    effort: high
    require_human_review: true
  implementation:
    model: codex_default
    effort: medium
    require_tests: true
  local_bugfix:
    model: low_cost_coding
    effort: low
    require_tests: true
  docs_summary:
    model: low_cost_text
    effort: low
  security_review:
    model: frontier_reasoning
    effort: high
    require_security_owner: true
```

## 4. AI IDE 和本地规范

### 4.1 Cursor 作为主 IDE

建议统一使用 Cursor 作为主 AI IDE：

- Ask：只读理解、代码导览、影响面分析。
- Agent：复杂功能、跨文件修改、测试修复。
- Manual：已知文件的精确编辑。
- Custom：创建团队专用模式，如 Plan、Backend、Frontend、Eval、Security Review。

必须启用项目规则：

```text
.cursor/rules/
AGENTS.md
docs/agent-memory/
docs/decisions/
```

`.cursorrules` 仅作为 legacy 兼容，不作为新规范入口。

### 4.2 推荐 Cursor Custom Modes

| Mode | 工具权限 | 用途 |
|---|---|---|
| Plan | Read/Search/Terminal read-only | 生成实现计划，不改文件 |
| Implement | Read/Search/Edit/Terminal test | 实现已批准任务 |
| Refactor | Read/Search/Edit/Terminal test | 不加功能，只改结构和测试 |
| Eval | Read/Search/Edit/Terminal test | 增加或修复测试、eval cases |
| Review | Read/Search/Terminal read-only | 代码审查，不改文件 |
| Security | Read/Search/Terminal read-only | 权限、SQL、凭证、数据出域审查 |

### 4.3 AGENTS.md 标准结构

```markdown
# AGENTS.md

## Project Goal
本项目第一阶段只交付可信业务生产闭环：DataProduct candidate、EvidenceChain、ActionProposal、Approval lite、Eval、Feedback/Trace、KnowledgeAsset candidate。

## Non-goals
- 不做高风险业务动作自动执行。
- 不把内容电商逻辑写进 Core。
- 不绕过 SQL Safety。

## Engineering Rules
- Contract-first。
- Evidence-first。
- Eval-first。
- Trace-by-default。

## Required Checks
- unit tests
- schema tests
- sql safety tests
- golden query eval
- evidence completeness tests

## Change Boundaries
- Core 只依赖 contracts。
- Provider 放在 providers/。
- Domain logic 放在 domain_packs/。
```

## 5. Agent 角色设计

Agent 是“角色化工作流”，不是互相争抢仓库控制权的自治群。

| Agent | 输入 | 输出 | 禁止事项 |
|---|---|---|---|
| Product Architect Agent | PRD、Goal Card、现有架构 | 边界判断、模块归属、非目标 | 不直接写生产代码 |
| Context Agent | issue、代码搜索、文档 | Context Pack | 不总结未读过的文件 |
| Contract Agent | 业务对象、API 需求 | Pydantic/JSON schema、兼容性测试 | 不改实现绕过 schema |
| Backend Agent | 已批准计划、Contract | API、服务、持久化、单测 | 不直接改 prompt 或前端 |
| Frontend Agent | UI 需求、API contract | 页面、组件、交互、前端测试 | 不改后端契约 |
| Data Agent Engineer | SQL 模板、指标、数据源 | query runtime、质量检查 | 不绕过 SQL Safety |
| AI Runtime Agent | skills、tools、structured outputs | agent adapter、tool registry | 不做权限最终判定 |
| Eval Agent | bug、golden cases、失败样本 | eval case、回归报告 | 不把错误答案写成 golden truth |
| Security Agent | diff、工具、权限、数据流 | 风险清单、阻断建议 | 不修改业务逻辑 |
| Code Review Agent | PR diff、测试结果 | review findings | 不做大范围重写 |
| Release Agent | merged PR、CI、变更说明 | release note、rollback plan | 不跳过 gate 发布 |
| Memory Agent | ADR、复盘、已发布事实 | 项目记忆更新建议 | 不记录密钥、猜测和未审核结论 |

## 6. Goal Card：多 Agent 对齐核心

每个任务必须先有 Goal Card。没有 Goal Card，不允许多个 Agent 并行开发。

```markdown
# Goal Card

## Objective
一句话描述要交付的用户价值。

## Scope
本次允许修改的模块、文件类型和接口。

## Non-goals
明确不做什么。

## Contracts
涉及的 schema、API、数据库表、事件。

## Acceptance Tests
必须通过的测试、eval、手工验收。

## Risk Level
R0-R5，说明数据、权限、写操作、模型风险。

## Context Pack
必须阅读的文件、文档、issue、决策记录。

## Token Budget
低/中/高。超过预算必须压缩上下文或升级人工决策。

## Owner
人类 owner 和 reviewer。
```

## 7. Context Pack：减少幻觉和 token 浪费

Agent 每次开始任务前只接收与任务相关的 Context Pack，而不是整个仓库。

Context Pack 应包含：

- 目标和非目标。
- 相关文件列表。
- 关键接口和 schema。
- 已知约束。
- 最近相关 ADR。
- 相关测试命令。
- 失败日志或 bug 复现步骤。
- 业务术语和指标口径。

禁止：

- 粘贴整份长文档。
- 粘贴无关目录。
- 用自然语言描述替代真实代码引用。
- 引用过期决策但不标日期。

## 8. 工作流编排

### 8.1 标准开发流

```text
Issue / PRD
  -> Goal Card
  -> Context Agent 生成 Context Pack
  -> Product Architect Agent 审边界
  -> Contract Agent 定契约和测试
  -> Implementation Agent 开发
  -> Eval Agent 补测试和回归
  -> Security Agent 审风险
  -> Code Review Agent 审 PR
  -> Human Reviewer 批准
  -> Release Agent 发布
  -> Memory Agent 沉淀决策
```

### 8.2 并行规则

允许并行：

- Backend Agent 和 Frontend Agent 在 Contract 冻结后并行。
- Eval Agent 与 Implementation Agent 在测试文件边界清楚时并行。
- Review Agent 与 Security Agent 对同一 PR 并行只读审查。

禁止并行：

- 两个 Agent 同时修改同一模块核心文件。
- Contract 未冻结时前后端并行实现。
- 多个 Agent 分别改 prompt、模型和 eval，但没有统一 owner。
- 安全高风险任务无人类 reviewer 时并行推进。

## 9. 最大程度减少模型幻觉

### 9.1 工程控制

1. 先读代码，再给方案。
2. 先列证据，再下结论。
3. API、库、框架、云服务、模型能力必须查官方文档或本地代码。
4. Agent 输出必须引用具体文件、函数、测试或文档。
5. 关键输出使用 structured output schema。
6. 任何“不确定”必须标记为 assumption。
7. 生成代码后必须运行相关测试或说明无法运行原因。
8. 高风险建议必须由第二 Agent 或人类 reviewer 复核。

### 9.2 Prompt 规则

所有角色 prompt 必须包含：

```text
If you have not read the source, say so.
If an API is uncertain, verify from official docs or local code.
Do not invent functions, tables, files, commands, or config keys.
Before editing, state the intended files and why.
After editing, report tests run and residual risk.
```

### 9.3 幻觉阻断门禁

以下情况 PR 直接退回：

- 引用了不存在的文件、函数、配置项。
- 伪造测试结果。
- 使用不存在的 API。
- 修改了非目标模块但未说明。
- 给出“已验证”但没有命令、测试或证据。
- 关键业务结论没有 EvidenceChain 或 eval。

## 10. Prompt / Skill 工程

### 10.1 Skill 目录建议

```text
skills/
  product_architect/
  contract_designer/
  backend_implementation/
  frontend_implementation/
  data_sql_safety/
  evidence_chain_builder/
  action_proposal_builder/
  eval_case_builder/
  security_reviewer/
  code_reviewer/
  release_manager/
  memory_librarian/
```

每个 skill 至少包含：

```text
SKILL.md
input_schema.json
output_schema.json
allowed_tools.md
positive_examples.jsonl
negative_examples.jsonl
eval_cases.jsonl
owner.md
```

### 10.2 通用 Agent Prompt 模板

```markdown
You are the {{agent_role}} for this repository.

Goal:
{{goal_card.objective}}

Scope:
{{goal_card.scope}}

Non-goals:
{{goal_card.non_goals}}

Required context:
{{context_pack.files}}

Rules:
- Read relevant files before proposing edits.
- Keep changes inside scope.
- Preserve existing style and contracts.
- Add or update tests/evals for behavior changes.
- Do not invent APIs, files, tables, or command results.
- Report assumptions explicitly.

Output:
1. Findings or implementation plan.
2. Files changed or files to change.
3. Tests/evals to run.
4. Risks and follow-up.
```

### 10.3 Code Review Prompt 模板

```markdown
Review this PR as a senior engineer.

Prioritize:
1. Bugs and behavior regressions.
2. Security, permission, data leakage, SQL safety.
3. Contract and migration compatibility.
4. Missing tests or evals.
5. Maintainability and style only after correctness.

Return:
- Findings first, ordered by severity.
- Each finding must cite file and line.
- No praise-only review.
- If no issues, say so and list residual test gaps.
```

## 11. Code Review 体系

### 11.1 Review 分层

| 层级 | 内容 | 工具/责任人 |
|---|---|---|
| L0 自动检查 | lint、format、typecheck、unit、schema、eval | CI |
| L1 Agent Review | bug、测试缺口、契约不一致 | Code Review Agent |
| L2 专项 Review | SQL Safety、权限、前端、数据、AI runtime | 对应专家 Agent + 人类 reviewer |
| L3 架构/安全 Review | Contract breaking change、R4/R5、数据出域 | CTO / Security |
| L4 Release Review | 发布风险、回滚、迁移、试点影响 | Release owner |

### 11.2 PR 合并门槛

必须满足：

- L0 全绿。
- 无 P0/P1 review finding。
- Contract 变更有 migration 或兼容说明。
- Agent/prompt/model 变更有 eval 对比。
- SQL 变更有 safety test。
- EvidenceChain 相关变更有 completeness test。
- R4/R5 路径没有自动执行。

## 12. 代码风格统一

### 12.1 基线工具

| 技术栈 | 工具 |
|---|---|
| Python / FastAPI | ruff、black、mypy、pytest |
| TypeScript / Next.js | eslint、prettier、tsc、vitest/jest、playwright |
| SQL | sqlfluff 或内部 SQL template linter |
| Markdown | markdownlint |
| Git | conventional commits、PR template、CODEOWNERS |
| Secrets | secret scanning、pre-commit hook |

### 12.2 统一规则

- 所有格式化交给工具，不靠 Agent 风格。
- 所有公共 API 必须有类型。
- 所有 schema 变更必须有测试。
- 所有业务规则必须有 owner。
- 所有 prompt 必须版本化。
- 所有 migration 必须可回滚或有回滚说明。

## 13. 代码质量控制

### 13.1 CI 最小集

```text
format check
lint
typecheck
unit tests
contract schema tests
sql safety tests
golden query tests
intent / metric eval
evidence completeness tests
action risk tests
frontend smoke
secret scan
dependency scan
```

### 13.2 质量指标

| 指标 | 阈值 |
|---|---:|
| P0 CI 通过率 | 100% |
| SQL Safety 写操作拦截 | 100% |
| EvidenceChain 正式输出覆盖 | 100% |
| golden query 正确率 | >= 85% |
| 核心指标命中率 | >= 90% |
| 回归 bug 必有 regression case | >= 90% |
| PR 大小 | 默认 < 500 行核心 diff |
| 无 reviewer 直接合并 | 0 |

## 14. Token 经济化和 ROI

### 14.1 成本原则

1. 只把相关上下文给 Agent。
2. 用低成本模型做检索、摘要、草拟。
3. 用高质量模型做架构、安全、复杂 review。
4. 对稳定规范使用项目规则，不每次重复粘贴。
5. 对长文档先做结构化摘要，再按需展开。
6. 对重复任务使用 skill 和模板。
7. 对相似任务复用 Context Pack。
8. 对大 PR 拆小，减少每次 review 上下文。

### 14.2 Token 预算分级

| 任务 | Token 预算 | 策略 |
|---|---:|---|
| 单文件 bugfix | 低 | 只注入目标文件、失败日志、测试 |
| 小功能 | 中 | 注入相关模块、Contract、测试 |
| 跨模块功能 | 高 | 先 Plan，再分任务执行 |
| 架构决策 | 高 | 注入 PRD、ADR、关键代码摘要 |
| 全仓库迁移 | 分阶段 | 先生成迁移计划和脚本，不一次性喂全仓库 |

### 14.3 ROI 计算

每两周统计：

```text
Agent ROI =
  (人工预估节省小时 * 人力小时成本 - 模型/工具成本 - 返工成本)
  / (模型/工具成本 + 返工成本)
```

必须同时记录：

- Agent 任务数。
- 自动完成率。
- 人工接管率。
- PR 返工率。
- 缺陷逃逸数。
- token 成本。
- CI 失败次数。
- review finding 数量。

如果某类任务返工率高于人工方式，降级为人类主导、Agent 辅助。

## 15. 项目开发记忆规则

### 15.1 记忆载体

```text
AGENTS.md
.cursor/rules/
docs/agent-memory/project-facts.md
docs/agent-memory/glossary.md
docs/agent-memory/model-router.md
docs/agent-memory/recent-decisions.md
docs/decisions/ADR-xxxx.md
docs/evals/
docs/release-notes/
```

### 15.2 什么可以记忆

- 已批准架构决策。
- 已发布 Contract。
- 指标口径和 owner。
- 模块边界。
- 测试和 eval 命令。
- 常见失败案例。
- 安全红线。
- 代码风格规则。
- 模型路由策略。

### 15.3 什么不得记忆

- 密钥、token、cookie、客户凭证。
- 未审核业务假设。
- 临时调试信息。
- 个人隐私。
- 客户敏感数据原文。
- 已被废弃但未标记状态的旧规则。

### 15.4 记忆晋升流程

```text
Raw note
  -> Candidate memory
  -> Owner review
  -> Published memory
  -> Agent rules / ADR / eval binding
  -> Periodic review or retirement
```

每条长期记忆必须有：

- 来源。
- 日期。
- owner。
- 适用范围。
- 过期或复审条件。

## 16. 开发安全边界

以下动作必须人工批准：

- 安装新依赖。
- 修改认证、权限、密钥、日志脱敏。
- 修改数据库 migration。
- 修改模型路由默认值。
- 修改 prompt/skill 且影响生产输出。
- 新增外部 API、MCP Server、Action Connector。
- 删除数据、迁移数据、改变 tenant 隔离。
- R4/R5 业务动作执行路径。

## 17. 落地计划

### 第 1 周

- 建立 `AGENTS.md`。
- 建立 `.cursor/rules/`。
- 建立 PR template 和 CODEOWNERS。
- 建立 Goal Card 模板。
- 建立 Context Pack 模板。
- 选定主 IDE 和主 Agent 工具。

### 第 2-3 周

- 建立 Contract Agent、Eval Agent、Security Agent、Review Agent prompt。
- 建立 CI 基线。
- 建立 SQL Safety 和 EvidenceChain 相关测试门禁。
- 选 3 个真实任务跑试点。

### 第 4-6 周

- 将 30%-50% 普通开发任务交给 Code Agent。
- 统计 token 成本、返工率、CI 失败率。
- 优化 Context Pack 和 rules。
- 固化项目记忆流程。

### 第 7-12 周

- 将低风险 backlog、测试补齐、文档、局部 bugfix 默认交给 Agent。
- 复杂架构和安全任务采用 Agent 初稿 + 人类主导。
- 建立每两周 Agent ROI 报告。

## 18. 不得突破的红线

1. 不得为了节省 token 省略测试和 eval。
2. 不得让 Agent 绕过 PR review 直接合并。
3. 不得让多个 Agent 无边界并行修改核心模块。
4. 不得把模型输出当成事实来源。
5. 不得记录或传播密钥和客户敏感数据。
6. 不得在没有 Goal Card 的情况下做大规模改动。
7. 不得在没有人类 owner 的情况下发布生产功能。

## 19. 参考资料

- OpenAI GPT-5.5 model docs: https://developers.openai.com/api/docs/models/gpt-5.5/
- OpenAI Codex product page: https://openai.com/codex/
- Cursor Agent modes and rules: https://docs.cursor.com/agent/custom-modes, https://docs.cursor.com/en/context
- GitHub Copilot cloud agent docs: https://docs.github.com/en/copilot/concepts/agents/cloud-agent/about-cloud-agent
- Claude Code CLI docs: https://code.claude.com/docs/en/cli-reference
- Windsurf Cascade and AGENTS.md docs: https://docs.windsurf.com/windsurf/cascade, https://codeium.mintlify.app/windsurf/cascade/agents-md
- Devin docs: https://docs.devin.ai/get-started/devin-intro
