# AI 全自动编码工作流编排：最优落地方案

> 日期：2026-06-01  
> 面向项目：AI Native Business Data OS  
> 角色视角：CTO  
> 结论：本项目采用“Agent Runner + GitHub Actions + n8n 外层编排”的混合方案，而不是纯脚本、纯 n8n 或纯 CI/CD。

## 1. 最优选择

对本项目，最优编排不是单一模式，而是三层架构：

```text
开发执行层：Codex / Cursor Agent + Python Agent Runner
质量门禁层：GitHub Actions / 本地同构 CI
外层调度层：n8n 只做触发、通知、报表、人工审批编排
```

一句话原则：

**代码生成和修复在隔离分支/工作区里跑；质量判断必须由 CI 和 eval 决定；n8n 不直接掌握任意代码执行权。**

## 2. 为什么不采用单一方案

| 方案 | 适合 | 不适合 | 本项目结论 |
|---|---|---|---|
| 纯 Python/Shell 脚本 | 快速跑通 AI 生成、测试、修复闭环 | 权限、审计、分支、多人协作、可视化较弱 | 用作开发执行层，不单独承担治理 |
| 纯 n8n | 多系统联动、定时、通知、人工审批、报告 | 直接改代码、执行 shell、复杂 diff/review 权限中心 | 只做外层编排，不做核心代码执行器 |
| 纯 GitHub Actions/Jenkins | 工程化 CI/CD、PR gate、审计、团队协作 | 本地探索、多轮修复、上下文压缩不灵活 | 作为质量门禁和发布入口 |
| Prefect/Dagster/Airflow | 数据/批处理/可观测任务流 | 代码 Agent 交互式开发体验较重 | 后续用于数据产品编译/评测调度，不作为第一阶段主编排 |

## 3. 推荐总体架构

```text
需求 / Issue / Goal Card
  -> n8n 或 GitHub Issue 触发
  -> Agent Runner 创建隔离分支 / worktree
  -> Context Pack 生成
  -> Codex / Cursor Agent 执行计划、编码、测试、修复
  -> 本地质量门禁
  -> 自动创建 PR
  -> GitHub Actions 跑完整 CI / Eval / Security
  -> Agent Review + Human Review
  -> 合并
  -> Release / Report / Memory Update
```

核心责任分工：

| 层 | 负责什么 | 不负责什么 |
|---|---|---|
| Agent Runner | 任务拆解、上下文打包、调用 Code Agent、执行白名单命令、重试 | 最终合并、生产部署、高风险授权 |
| GitHub Actions | CI、eval、secret scan、dependency scan、构建、release gate | 自由生成大面积代码 |
| n8n | 定时触发、Webhook、飞书/钉钉/邮件通知、审批流、结果看板 | 直接执行任意 shell 改仓库 |
| 人类 reviewer | 产品边界、架构、安全、最终 merge | 重复机械修复 |

## 4. 自动化等级

本项目按风险分阶段开放自动化。

| 等级 | 自动化范围 | 当前建议 |
|---|---|---|
| L0 | Agent 只读分析，输出计划 | 立即启用 |
| L1 | Agent 在本地/分支生成代码并跑测试 | 立即启用 |
| L2 | Agent 自动创建 PR，但不自动合并 | 第一阶段主模式 |
| L3 | 低风险变更自动合并，如文档、测试样本、格式化 | 试点后启用 |
| L4 | 自动部署到测试环境 | CI 稳定后启用 |
| L5 | 自动生产发布 | 本项目第一阶段禁止 |

第一阶段最高开放到 L2。L3 只允许 docs/test-only，且必须 CI 全绿。

## 5. 标准交互接口

所有工具、AI、CI、n8n 之间只传标准 JSON/Markdown 产物，减少幻觉和粘连。

```text
.agent_runs/{run_id}/
  goal_card.md
  context_pack.json
  plan.md
  patch_manifest.json
  tool_results.json
  quality_report.md
  review_report.md
  retry_log.json
```

### 5.1 Goal Card

```json
{
  "objective": "实现 EvidenceChain completeness test",
  "scope": ["business_data_os/evidence_chain", "tests/evidence_chain"],
  "non_goals": ["不改 SQL runtime", "不改 UI"],
  "risk_level": "R2",
  "required_checks": ["unit", "schema", "evidence_eval"],
  "owner": "backend_lead",
  "max_retries": 2
}
```

### 5.2 Tool Result

```json
{
  "command": "pytest tests/evidence_chain -q",
  "exit_code": 1,
  "stdout_path": ".agent_runs/run_001/logs/pytest.out",
  "stderr_path": ".agent_runs/run_001/logs/pytest.err",
  "classification": "unit_test_failure",
  "retryable": true
}
```

### 5.3 Patch Manifest

```json
{
  "files_changed": [
    {
      "path": "business_data_os/evidence_chain/builder.py",
      "change_type": "modify",
      "reason": "add required field validation"
    }
  ],
  "contracts_changed": false,
  "tests_added": true,
  "risk_level": "R2"
}
```

## 6. Agent Runner 设计

Agent Runner 是本项目全自动开发的主控程序。建议用 Python 实现，跨 Windows/Linux/服务器一致运行。

### 6.1 目录结构

```text
scripts/
  agent_runner/
    runner.py
    config.yml
    command_whitelist.yml
    retry_policy.yml
    prompt_templates/
    adapters/
      codex.py
      cursor.py
      github.py
      openai_api.py
```

### 6.2 核心流程

```text
load goal_card
  -> create branch/worktree
  -> build context_pack
  -> ask agent for plan
  -> validate plan scope
  -> run implementation
  -> run format/lint/type/test/eval
  -> if fail and retryable: feed compact error to agent
  -> if pass: create PR and attach reports
  -> if fail after max retries: stop and escalate
```

### 6.3 命令白名单

Agent Runner 只能执行白名单命令。

```yaml
allowed_commands:
  - ["ruff", "check"]
  - ["ruff", "format"]
  - ["pytest"]
  - ["npm", "test"]
  - ["npm", "run", "lint"]
  - ["npm", "run", "typecheck"]
  - ["git", "diff"]
  - ["git", "status"]
  - ["git", "add"]
  - ["git", "commit"]
blocked_commands:
  - "rm"
  - "sudo"
  - "curl | sh"
  - "Invoke-Expression"
  - "docker system prune"
  - "kubectl delete"
```

高风险命令必须人工批准：

- 安装依赖。
- 数据库 migration。
- Docker build/push。
- 部署命令。
- 删除文件。
- 修改 secrets、权限、认证、模型路由。

## 7. GitHub Actions 门禁

GitHub Actions 是质量事实来源。Agent 本地跑过测试不等于可合并。

### 7.1 必跑流水线

```text
format
lint
typecheck
unit tests
contract schema tests
sql safety tests
golden query tests
intent / metric eval
evidence completeness tests
action risk tests
secret scan
dependency scan
frontend smoke
```

### 7.2 PR 规则

所有 Agent 改动必须走 PR：

- 自动 PR 标题带 `[agent]`。
- PR body 附 Goal Card、Patch Manifest、Quality Report。
- CODEOWNERS 自动请求 reviewer。
- CI 失败时 Agent 可最多修复 2 轮。
- 同类失败 2 次后停止自动修复，交给人。

### 7.3 禁止自动合并的变更

- Contract breaking change。
- SQL Safety。
- 权限、认证、密钥、审计。
- Agent prompt / model router。
- 数据库 migration。
- R4/R5 Action。
- 部署脚本。

## 8. n8n 的正确位置

n8n 适合作外层编排：

- 接收需求表单或 Webhook。
- 创建 GitHub Issue。
- 触发 Agent Runner。
- 监听 PR / CI 状态。
- 推送钉钉/飞书/邮件报告。
- 触发人工审批。
- 汇总每周 Agent ROI 报表。

n8n 不建议直接做：

- 任意 shell 执行。
- 直接写仓库。
- 直接修改生产环境。
- 保存明文 token。
- 直接执行 Docker/kubectl 高风险命令。

如果必须使用 n8n Execute Command，只能部署在隔离 runner 容器中，并且命令必须转发给 Agent Runner 白名单接口，而不是让 n8n 节点直接执行任意命令。

## 9. 错误修复循环

### 9.1 标准循环

```text
run checks
  -> classify failure
  -> extract minimal logs
  -> build fix prompt
  -> agent patch
  -> rerun related checks
  -> rerun full affected suite
  -> create report
```

### 9.2 失败分类

| 类型 | 自动修复 | 处理 |
|---|---|---|
| format/lint | 是 | 自动修复 2 轮 |
| unit test | 是 | 限定相关文件修复 |
| typecheck | 是 | 修复类型和接口 |
| contract schema | 谨慎 | 需 Contract Agent 复核 |
| golden query/eval | 谨慎 | 禁止为了过测试改低标准 |
| SQL safety | 否 | 安全 reviewer 介入 |
| secret scan | 否 | 立即阻断 |
| dependency vulnerability | 谨慎 | 人类批准升级 |
| deploy failure | 否 | 第一阶段不自动部署 |

### 9.3 重试策略

```yaml
max_total_retries: 2
max_same_error_retries: 1
stop_conditions:
  - secret_scan_failed
  - sql_safety_failed
  - contract_breaking_change
  - touched_out_of_scope_files
  - tests_removed_without_approval
```

## 10. 本项目推荐第一阶段落地流程

### 10.1 个人/本地开发

```text
Cursor/Codex
  -> Goal Card
  -> Agent Runner
  -> 本地 format/lint/test/eval
  -> 自动 PR
```

适合：

- 功能开发。
- bugfix。
- 测试补齐。
- 文档更新。
- 局部重构。

### 10.2 团队工程化

```text
GitHub Issue
  -> n8n 创建/同步任务
  -> Agent Runner 认领低风险任务
  -> PR
  -> GitHub Actions
  -> Agent Review
  -> Human Review
  -> Merge
```

适合：

- 多人协作。
- 可审计开发。
- 自动生成周报。
- 统一质量门禁。

### 10.3 试点部署

第一阶段不做自动生产部署。只允许：

- 自动部署到 ephemeral preview 环境。
- 手动批准后部署到 staging。
- 生产发布必须人工 release review。

## 11. 与本项目工程质量门禁绑定

本项目最重要的不是“AI 能写代码”，而是不能绕过以下门禁：

| 项目能力 | 必须门禁 |
|---|---|
| BusinessIntent | schema tests |
| MetricContract | metric eval |
| SQLTemplate / QueryPlan | SQL Safety tests |
| QueryResult | golden query result diff |
| EvidenceChain | completeness + consistency tests |
| ActionProposal | risk level + approval rule tests |
| Agent prompt | regression eval |
| Model routing | cost/logging/security review |
| UI | frontend smoke + accessibility baseline |

## 12. 跨环境一致性

为了兼容 Windows、Linux、本地和服务器：

- 优先使用 Dev Container / Docker Compose 定义工具链。
- Python 使用 `uv` 管理环境。
- Node 使用固定包管理器和 lockfile。
- 所有命令封装为 `just` / `nox` / `scripts`，避免手写平台差异命令。
- Agent Runner 只调用统一命令，不直接写平台分支。
- CI 与本地尽量同构。

推荐命令抽象：

```text
just format
just lint
just typecheck
just test
just eval
just ci-local
```

## 13. 最小可运行版本

第一版只实现 5 条链路：

1. 从 GitHub Issue 读取 Goal Card。
2. 生成 Context Pack。
3. 调用 Codex/Cursor Agent 执行代码修改。
4. 跑本地 `format/lint/test/eval`。
5. 创建 PR 并附带报告。

不做：

- 自动生产部署。
- 自动合并高风险 PR。
- 多 Agent 自由竞争。
- n8n 直接执行任意 shell。
- 跨多个仓库自动大迁移。

## 14. 推荐实施计划

### 第 1 周：跑通最小闭环

- 建立 Goal Card 模板。
- 建立 Context Pack 模板。
- 建立 Agent Runner 原型。
- 建立命令白名单。
- 跑通一个 docs/test-only PR。

### 第 2 周：接入质量门禁

- 接入 GitHub Actions。
- 接入 format/lint/unit/schema。
- 接入 SQL Safety 和 EvidenceChain eval 占位。
- 自动生成 Quality Report。

### 第 3-4 周：接入 n8n 外层编排

- n8n 监听 Issue/手动表单。
- n8n 触发 Agent Runner。
- n8n 接收 CI 状态。
- 推送飞书/钉钉/邮件报告。

### 第 5-8 周：扩大到低风险开发

- 默认把文档、测试、局部 bugfix 交给 Agent Runner。
- 建立 Agent ROI 报表。
- 建立失败样本沉淀机制。
- 限制核心模块仍需人工主导。

### 第 9-12 周：进入主开发流

- 将 30%-50% 普通开发任务交给 Agent。
- 高风险任务采用 Agent 初稿 + 人类实现/审核。
- 建立自动 review + 人类 review 双门禁。

## 15. 最终 CTO 决策

本项目采用以下最优方案：

```text
主开发：
  Codex / Cursor Agent + Python Agent Runner

主门禁：
  GitHub Actions

外层编排：
  n8n

部署策略：
  preview 可自动，staging 需批准，production 禁止全自动

自动化上限：
  第一阶段 L2，低风险 docs/test-only 可试点 L3
```

这个选择的收益是：

- 保留脚本方案的灵活和低成本。
- 保留 n8n 的可视化调度和多系统连接。
- 保留 GitHub Actions 的工程审计和质量门禁。
- 避免 n8n 或 AI Agent 直接变成高权限“自动改库/自动部署”中心。
- 与本项目 EvidenceChain、SQL Safety、Eval、Trace 的质量要求一致。

## 16. 参考资料

- n8n Execute Command node docs: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.executecommand/
- n8n workflow executions docs: https://docs.n8n.io/workflows/executions/
- GitHub Actions docs: https://docs.github.com/en/actions/learn-github-actions/understanding-github-actions
- OpenAI Codex product page: https://openai.com/codex/
- Cursor modes docs: https://docs.cursor.com/en/agent/modes
