# Code Agent 开源辅助项目选型

> 日期：2026-06-01  
> 角色：CTO / Code Agent Governance  
> 范围：辅助 Code Agent 开发、评测、上下文管理、技能复用、代码审查、安全和工程质量  
> 结论级别：推荐工具栈，不是强制依赖锁定  

## 1. CTO 结论

本项目的 Code Agent 工具栈应围绕 6 件事建设：

```text
上下文准确
  -> 执行隔离
  -> 指令标准化
  -> 自动评测
  -> PR 审查
  -> 安全和成本可控
```

不建议一上来堆多个 coding agent。并且需要区分两件事：

- 产品 Agent OS / Agent Runtime：必须 100% 自研，开源 Agent OS 只能参考。
- Code Agent 开发辅助工具：可以审慎使用开源工具提高研发效率，但不能替代项目工程治理。

最优策略是：

1. 当前主 Agent：继续用 Codex。
2. 上下文增强：引入 Repomix / GitMCP / Context7 这类工具，但必须走白名单。
3. 隔离执行：重点评估 Dagger `container-use`，让多个 Agent 在独立容器和分支里工作。
4. 指令标准：采用 `AGENTS.md` + 项目内 `skills/`，不要直接安装未知社区 skill。
5. 评测体系：用 SWE-bench / Vexp SWE-bench / promptfoo 的思想做本项目自己的 coding-agent eval。
6. PR 安全：用 reviewdog、Semgrep、Gitleaks、TruffleHog、Ruff、Pyright 等确定性工具先兜底，再让 AI Review 做第二层。

硬边界：

- OpenHands、SWE-agent、Goose、Cline、Aider、OpenCode、Gemini CLI、BMAD、SuperClaude 等只能用于调研、对标、个人辅助或流程参考。
- 不允许把任何开源 coding agent / Agent OS 项目作为本项目产品内核。
- 不允许复制外部项目 prompt、skill、orchestration runtime、权限策略或核心代码进入 OS Core。
- 本项目自建 `skills/`、`AgentRuntime`、`ToolRegistry`、`AgentRun`、`AgentEval`、`AgentMemory`。

## 2. 直接推荐进入项目治理的项目

### 2.1 AGENTS.md / Agent 指令标准

| 项目 | 地址 | 价值 | 建议 |
|---|---|---|---|
| AGENT.md standard | https://github.com/agentmd/agent.md | 统一不同 coding agent 的仓库级上下文规则 | 参考，并继续维护本项目 `.agent` / 后续 `AGENTS.md` |
| OpenAI Codex AGENTS.md docs | https://github.com/openai/codex/blob/main/docs/agents_md.md | Codex 对 AGENTS.md 的作用域和优先级说明 | 必读，后续迁移到实现仓库 |
| GitHub Awesome Copilot | https://github.com/github/awesome-copilot | instructions、agents、skills、hooks、workflows 集合 | 参考，不直接批量安装 |

CTO 规则：

- 项目实现仓库创建后必须有 `AGENTS.md`。
- `.agent` 是当前资料包规则；代码仓库阶段应迁移为 `AGENTS.md` + `.github/copilot-instructions.md` 可选。
- 指令文件必须短、硬、可验证，不能堆愿望清单。

### 2.2 Codebase Context / 文档上下文增强

| 项目 | 地址 | 价值 | 建议 |
|---|---|---|---|
| Repomix | https://github.com/yamadashy/repomix | 将代码库打包成 LLM 友好的上下文文件，支持 MCP/插件生态 | P0 试点，用于架构审查和跨文件理解 |
| GitIngest | https://github.com/cyclotruc/gitingest | 将 GitHub 仓库转换为便于 LLM 阅读的文本上下文 | P1 参考，适合外部 repo 快速阅读 |
| GitMCP | https://github.com/idosal/git-mcp | 为任意 GitHub 项目提供远程 MCP 文档/代码上下文 | P1 试点，仅白名单 repo |
| Context7 | https://github.com/upstash/context7 | 给 coding agent 提供最新库文档和代码示例 | P1 试点，避免模型用过期 API |
| GitHub MCP Server | https://github.com/github/github-mcp-server | GitHub 官方 MCP server，用于 repo/issue/PR 操作 | P1/P2，权限必须最小化 |

CTO 规则：

- 外部 repo 上下文工具只允许读，不允许写。
- 所有 MCP server 进入白名单前必须审查权限、传输方式、token scope。
- 不允许把 `.env`、凭证、客户数据打包进上下文。

### 2.3 Agent 执行隔离 / 并行开发环境

| 项目 | 地址 | 价值 | 建议 |
|---|---|---|---|
| Dagger Container Use | https://github.com/dagger/container-use | 为 coding agent 提供隔离容器、独立 git branch、命令日志 | P0/P1 重点评估 |
| SWE-ReX | https://github.com/SWE-agent/SWE-ReX | SWE-agent 的 sandboxed code execution engine | 参考隔离执行架构 |
| Dev Containers | https://github.com/devcontainers/spec | 标准化开发容器 | 实现仓库建议采用 |

CTO 规则：

- 多 Agent 并行写代码前，必须有隔离环境。
- Agent 不应直接污染开发者当前工作树。
- 每个 Agent run 要保留命令日志、diff、测试结果、失败原因。

### 2.4 Coding Agent / 自主修复参考实现

| 项目 | 地址 | 价值 | 建议 |
|---|---|---|---|
| SWE-agent | https://github.com/SWE-agent/SWE-agent | GitHub issue -> 自动修复，含 Agent-Computer Interface 思路 | 参考，适合研究自动修复闭环 |
| OpenHands | https://github.com/OpenHands/OpenHands | AI software developer platform，shell/browser/editor sandbox | 参考，不直接作为主开发工具 |
| Goose | https://github.com/block/goose | 本地开源 AI agent，CLI/Desktop/API，MCP 扩展 | 可试用，但不进入主线标准 |
| Aider | https://github.com/aider-ai/aider | terminal AI pair programmer，Git-first | 工程师个人工具，不作为团队唯一标准 |
| Cline | https://github.com/cline/cline | IDE/CLI autonomous coding agent，MCP 支持 | IDE 辅助工具，权限受控 |
| OpenCode | https://github.com/opencode-ai/opencode | terminal coding agent | 参考 skills/agent 配置 |
| Gemini CLI | https://github.com/google-gemini/gemini-cli | Google 开源 terminal agent | 备用对比工具 |

CTO 规则：

- 这些是参考或备用，不替代当前 Codex 主工作流。
- 任何 Agent 生成代码必须经过同一套 CI、Review、Eval。
- 不允许不同 Agent 各自维护一套项目规则。

### 2.5 Skills / Prompt / Agent 工作流资产

| 项目 | 地址 | 价值 | 建议 |
|---|---|---|---|
| Anthropic Skills | https://github.com/anthropics/skills | Agent Skills reference，复杂 skill 结构参考 | 参考；source-available，不直接当开源依赖 |
| Langfuse Skills | https://github.com/langfuse/skills | Langfuse eval/observability skill 示例 | 参考 eval skill 组织 |
| BMAD-METHOD | https://github.com/bmad-code-org/BMAD-METHOD | AI-native 开发流程、角色、工作流 | P1 参考 PM/BA/Dev/QA agent 流程 |
| SuperClaude Framework | https://github.com/SuperClaude-Org/SuperClaude_Framework | commands、personas、skills、agent 编排 | 参考，不直接套用 |
| Awesome Copilot Agents | https://github.com/Code-and-Sorts/awesome-copilot-agents | instructions、prompts、skills、MCP、agent markdown 收集 | 参考库，需逐个审查 |
| Agent Skills Awesome | https://github.com/scienceaix/agentskills | skills 生态索引 | 参考生态，不直接安装 |

本项目内部应优先自建以下 skills：

```text
skills/architecture-review/
skills/contract-first-development/
skills/sql-safety-review/
skills/evidencechain-review/
skills/eval-regression/
skills/security-risk-review/
skills/test-generation/
skills/github-pr-review/
skills/ci-failure-debug/
skills/release-checklist/
skills/product-prd-breakdown/
skills/project-backlog-planning/
```

每个 skill 必须有：

```text
SKILL.md
适用条件
输入材料
输出格式
禁止行为
验证步骤
安全边界
示例任务
```

### 2.6 Coding Agent 评测 / Benchmark

| 项目 | 地址 | 价值 | 建议 |
|---|---|---|---|
| SWE-bench | https://github.com/swe-bench/SWE-bench | 真实 GitHub issue 修复评测标准 | 参考，不直接作为业务唯一指标 |
| SWE-agent | https://github.com/SWE-agent/SWE-agent | 自主修复和 benchmark harness | 可借鉴 eval harness |
| Vexp SWE-bench | https://github.com/Vexp-ai/vexp-swe-bench | 对比 coding agent 成本、速度、解决率 | 参考 Agent ROI 评估 |
| Augment SWE-bench Agent | https://github.com/augmentcode/augment-swebench-agent | 简洁 SWE-bench docker harness | 参考轻量评测 harness |
| promptfoo | https://github.com/promptfoo/promptfoo | prompt/agent/RAG eval、red-team、CI | P0：用于项目 Agent prompt 回归 |

本项目不需要完全复刻 SWE-bench。应该建立自己的 `Project SWE Eval`：

```text
eval/code_agent/
  contract_change_tasks/
  sql_safety_tasks/
  evidence_chain_tasks/
  regression_bugfix_tasks/
  frontend_smoke_tasks/
  documentation_update_tasks/
```

评测指标：

- 是否读了正确上下文。
- 是否遵守架构边界。
- 是否修改了不该改的文件。
- 是否通过测试。
- 是否新增必要测试。
- 是否 hallucinate 不存在的 API。
- token 成本。
- 修复轮次。
- reviewer 返工率。

### 2.7 PR Review / 静态分析 / 安全兜底

| 项目 | 地址 | 价值 | 建议 |
|---|---|---|---|
| reviewdog | https://github.com/reviewdog/reviewdog | 把 lint/static analysis 结果评论到 PR diff | P0/P1：接入 GitHub Actions |
| Semgrep | https://github.com/semgrep/semgrep | 多语言静态分析、安全规则 | P0/P1：安全扫描和架构规则 |
| Gitleaks | https://github.com/gitleaks/gitleaks | secret scanning | P0：防止 Agent 泄露凭证 |
| TruffleHog | https://github.com/trufflesecurity/trufflehog | secret scanning，验证型扫描 | P1：补充 Gitleaks |
| Claude Code Security Review | https://github.com/anthropics/claude-code-security-review | AI security review GitHub Action | 参考 AI review prompt，不作为唯一安全门 |
| Agent Verifier | https://github.com/aurite-ai/agent-verifier | 检查 hallucinated tools、无限循环、安全问题 | P1 试验，成熟度待验证 |

CTO 规则：

- AI review 不能替代确定性扫描。
- Secret scanning 必须在 Agent commit/PR 前运行。
- PR review 先看 bug、风险、测试缺口，再看风格。

### 2.8 工程质量基线

| 项目 | 地址 | 价值 | 建议 |
|---|---|---|---|
| uv | https://github.com/astral-sh/uv | Python 项目和依赖管理 | P0 |
| Ruff | https://github.com/astral-sh/ruff | Python lint/format | P0 |
| Pyright | https://github.com/microsoft/pyright | Python 类型检查 | P0/P1 |
| Biome | https://github.com/biomejs/biome | JS/TS formatter/linter | P0 for frontend |
| Playwright | https://github.com/microsoft/playwright | 浏览器自动化和 smoke test | P0/P1 for frontend |

## 3. 推荐落地组合

### 3.1 第一批立刻采用

```text
AGENTS.md / .agent:
  项目规则、边界、测试命令、禁止行为

Repomix:
  大上下文打包和架构审查辅助

promptfoo:
  prompt / agent 输出回归

reviewdog:
  PR 自动评论 deterministic findings

Gitleaks:
  Secret scanning

uv + ruff + pyright + pytest:
  Python 基线

Biome + TypeScript checks + Playwright:
  Frontend 基线
```

### 3.2 第二批试点

```text
Dagger container-use:
  多 Agent 并行隔离环境

Context7 / GitMCP:
  外部文档和 GitHub repo 最新上下文

Semgrep:
  安全规则和架构规则

Phoenix / Langfuse:
  Agent trace 和 eval observability

BMAD-METHOD / SuperClaude:
  参考角色、workflow、skills 组织方式
```

### 3.3 暂缓

```text
OpenHands / SWE-agent / Goose / Cline / Aider:
  作为研究和对比，不替代主开发工作流

Anthropic skills / Awesome skills:
  作为参考，不直接安装进项目

n8n:
  不用于 Code Agent 核心开发链路
```

## 4. 项目级 Code Agent 开发流程

建议标准流程：

```text
Issue / Goal Card
  -> Context Pack
  -> Architecture Agent brief
  -> CTO Gate
  -> Contract Agent
  -> Code Agent implementation in isolated branch/container
  -> deterministic checks
  -> eval regression
  -> AI review
  -> human review
  -> merge
  -> memory / skill update
```

每个 Agent Run 必须保存：

```text
task_id
goal
context_files
agent_name
model
tools_used
commands_run
files_changed
tests_run
eval_result
token_cost
review_findings
lessons
```

## 5. 风险清单

| 风险 | 控制 |
|---|---|
| Agent 修改错误文件 | container-use / branch isolation / diff review |
| 上下文污染或过期 | Repomix 配置、Context Pack、Context7 白名单 |
| 外部 MCP 过权 | MCP 白名单、只读 token、sandbox |
| Community skill 注入风险 | 禁止直接安装，必须源码审查 |
| 凭证泄露 | Gitleaks / TruffleHog / 禁止打包 `.env` |
| AI review 幻觉 | 必须引用文件行，确定性扫描优先 |
| 多 Agent 目标漂移 | Goal Card + Architecture Brief + CTO Gate |
| Token 成本失控 | Run log、cost report、上下文预算 |

## 6. CTO 决策

批准：

- 采用 `AGENTS.md` 思路作为代码仓库阶段的统一 Agent 指令标准。
- 评估 Repomix、promptfoo、reviewdog、Gitleaks、Dagger container-use。
- 建立项目内部 `skills/`，但不直接安装社区 skill。
- 建立项目级 Code Agent Eval，而不是只看 SWE-bench 排名。

不批准：

- 不批准让任意开源 coding agent 直接替代 Codex 主流程。
- 不批准外部 MCP server 获得写权限。
- 不批准未审查的 skill 进入项目主工作流。
- 不批准 AI review 替代安全扫描、测试和人工 review。
