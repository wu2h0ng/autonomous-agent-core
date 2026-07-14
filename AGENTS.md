# AGENTS.md — Agent OS Monorepo Instructions

> Status: `ACTIVE`
> Version: 2.0
> Updated: 2026-07-14
> Scope: `autonomous-agent-core/` Product Track 与 Research Track

## 1. Read current truth first

最小顺序：

1. `docs/CURRENT_STATE.yaml`
2. `docs/AGENT-OS-PRODUCT-BLUEPRINT.md`
3. `docs/PROJECT_PLAN.md`
4. `codebase_index.md`
5. 当前状态直接引用的 ADR/RR/spec/result/review 与相关代码

先比较 `CURRENT_STATE.updated`、live Git HEAD/working tree 和更新日期更晚的 durable decision。静态 README、计划和历史摘要不能覆盖 CURRENT_STATE；原始 prereg/result verdict 也不能被新叙事覆盖。

## 2. Repository identity

本仓是 Agent OS 产品主仓，采用隔离的双轨架构：

- Product Track：统一 Agent Surface、Ask/Work、Task Workspace、typed contracts、Runtime/authority/evidence/correction、provider、knowledge、eval、SDK 和 domain packs。
- Research Track：通用认知、世界模型、belief-action coupling、corrigibility、持续适应与核心演化候选的形式化、证伪和负结果。
- Agent Core：内部 Runtime/Kernel，不是产品名。
- Data Agent：第一个企业 domain pack；ADR-0054/SPINE-1 未执行前仍在外部 donor 仓物理独立运行。

双轨共仓不等于证据混合。产品代码不能直接 import 研究实验实现；研究结果必须经 `ResearchCandidateManifest`、稳定接口、held-out 产品门和独立 promotion decision 才可能晋升。

## 3. Non-negotiable boundaries

1. C7 是 non-writable、non-bypassable 的外部纠正权威；Agent 不得调用、模拟或清除 `op_*` 主权面。
2. LLM/learned component 只能提议、规划、生成或验证；高后果动作必须经过 typed contract、CapabilityBroker/policy/disposer、evidence/trace 和 C7。
3. OS Core 零 Data Agent 领域耦合；Metric、SemanticObject、DataProduct、SQL 和业务动作只进入 domain pack/adapter。
4. CWM 不是默认万能脑；只在变量、干预和结果可识别的任务中作为候选世界模型器官。
5. 外部 `Skill` 不是内核对象；先编译为 Capability、Procedure/Workflow candidate、Knowledge、Credential 与 Policy requirements。
6. Agent OS 的 task state、authority/disposer、evidence/outcome、correction 和 promotion core 必须自研，不能外包给 Agent framework。
7. 不得存储 secret、token、cookie、credential、敏感客户原始数据或让其进入模型可见记忆/日志。
8. 禁止跨仓 runtime import/copy。ADR-0054 只允许 G0-G7 通过后的单次 history-safe migration，不授权预先 import、双向同步、push 或 merge。
9. 产品、研究、开发流程和商业证据分别记账，禁止相互回填。
10. 不得用 module existence、mock、constant-return test、局部 fixture 或绿灯包装能力完成。

## 4. Product Track flow

```text
Goal/Context
  -> architecture/contract/security gate when applicable
  -> failing or bypass-detecting test
  -> implementation
  -> unit/integration/e2e/eval
  -> independent review
  -> release authorization
  -> CURRENT_STATE/index update
```

每项能力必须说明公共入口、typed contract、失败路径、集成点、Trace/Evidence/Outcome、权限、rollback/compensation 和证据等级。分别使用 `specified / implemented / tested / integrated / verified / released / generally validated`。

Product Track 可按 ADR 使用成熟 UI、数据库、队列、模型 SDK、身份和 observability 依赖，但不得削弱 authority spine 或把研究控制变量误当永久产品栈。

## 5. Research Track flow

先遵守根仓 `docs/OPERATING-TRACKS.md`、Paradigm Innovation Loop 和 RR-0029，再进入 ADR/formal/algorithm/prereg/implementation。

硬规则：

- freeze before result-bearing run；
- builder/reviewer 身份分离，review 必须绑定实际内容；
- 不为过门修改机制、门、baseline、环境、轴、指标或种子；
- post-hoc winner 只能在 disjoint fresh seeds/held-out tasks 上另立确认门；
- `NOT_MET`、`INVALID`、`INCONCLUSIVE` 原样保留；
- 无强 cheap baseline、消融、功效和失败分布时不得升级研究主张；
- 自主主张使用 `Autonomy(S,E,O,V,T)`，G10 等局部结果不等于自主。

当前核心演化边界：L0-L3 外部候选生成/隔离实现/训练/测试允许；L4 活跃 Runtime 自改关闭；L5 C7、权限、审计、评估和 promotion root 自改禁止。

## 6. Verification entry points

Research Track 基础门：

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

Product Track 基础门：

```bash
uv run --extra product-test pytest tests/product -q
uv run --extra product-test ruff check apps packages/contracts/src packages/os_core/src tests/product
uv run --extra product-test pyright apps packages/contracts/src packages/os_core/src tests/product
uv build --wheel --out-dir /tmp/agent-os-product-wheel packages/contracts
uv build --wheel --out-dir /tmp/agent-os-product-wheel packages/os_core
```

这些是基础门，不自动证明 production readiness、market parity、Blueprint completion、SPINE-1 或研究晋升。实际任务还需运行任务包/CI 指定的 integration、security、e2e 和 receipt 验证。

## 7. Founder-reserved decisions

Agent 可设计与建议，但以下事项不能自行授权：C1-C7/SD4 移动、预注册门变更、medium/high-risk 路线选择或复活、高后果权限开放、research-to-product promotion、Agent OS 产品身份变化、ADR-0054 执行/迁移、外部发布、付费和 merge/release。

## 8. Completion and Git

交付前：

- 运行目标验证并报告精确结果；
- 检查产品/研究/流程主张边界；
- 更新最小权威文档集；
- `git status --short`，区分本任务与既有改动；
- 报告未提交、提交、推送、PR 和 merge 状态。

未经明确授权不得推送 `main/master` 或合并。Runtime、contract、安全、研究门和跨仓变更默认走 feature branch + 独立 review。
