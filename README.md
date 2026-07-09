# autonomous-agent-core

> Historical repository name. This repository now evolves directly into the complete **Agent OS** product monorepo.

## Product Authority

Read `docs/AGENT-OS-PRODUCT-BLUEPRINT-V1.md` for the final product definition and `docs/CURRENT_STATE.yaml` for live implementation/research truth.

Agent OS is a persistent, governed work operating system for individuals, independent developers and enterprises. Its primary surface is a Codex-style Task Workspace; workflows share one typed graph across natural-language generation, visual drag-and-drop editing and structured configuration. Data Agent is the first official enterprise domain pack.

The repository uses a **dual-track layered monorepo** model:

- **Product Track:** Task Workspace, workflow, runtime, providers/BYOK, tools/plugins, knowledge/RAG, agents/subagents, governance, eval, SDK and domain packs.
- **Research Track:** CWM, belief/action mechanisms, belief ledger, outcome learning, corrigibility, formal models, preregistered experiments and negative-result maps.

The current tree remains research-heavy. Finalizing the blueprint does not claim that the Agent OS runtime or market-parity layer is already delivered, and no research result becomes a product claim by proximity.

## Current State

Read `docs/CURRENT_STATE.yaml` first. It is the live handoff anchor for the current branch, stage, next task, latest tests, latest ADRs, and known drift risks.

As of 2026-07-10, the product-blueprint worktree records `1237 tests OK (16 skipped)`: 13 intentional sentinels plus 3 optional Replogle preprocessing tests skipped because `anndata/numpy` are not installed in this environment. `G10` remains a narrow positive result; `G13` and `G-ECO-REOPEN-1` remain `NOT_MET`; the strong-locus Stage 4 result remains `INSUFFICIENT_DATA_HONEST_NEGATIVE`; CWM hard-form evidence remains limited to its preregistered channel. See `docs/CURRENT_STATE.yaml` for exact authority and do not infer product delivery from this suite.

## Research Track: historical four claims

1. **利害是真的** — 代谢预算会耗尽;没有任务奖励,"好/坏"只由"预算是否越过死亡线"定义。规范性内生,非手调。
2. **相关性实现 / 重新框定** — 规则突变→预测误差骤升→相关性场摆向探索→重定位新最优。
3. **可纠正且不抵抗** — 外部可观测(哈希链审计)/暂停/回滚/收紧;智能体无自解除手段。
4. **器官非主体** — 控制回路是确定性的生存力+推理;LLM 不在控制路径(v0 不接)。

These are research hypotheses and guards. They are not the Agent OS product acceptance criteria; product, moat and superiority gates are defined in the Blueprint.

## Current research layout

```text
src/aac/
  viability.py      ViabilityCore   本质变量 + 代谢预算 + 压力
  world_model.py    ActionOutcomeModel  行动→奖励信念 + 不确定性
  relevance.py      RelevanceField  对立过程:surprise↔压力
  policy.py         PolicySelector  期望自由能味:pragmatic + epistemic
  shell.py          CorrigibilityShell  观测/暂停/回滚/收紧(op_* = 外部主权面)
  audit.py          AuditLog        只增 + 哈希链
  agent.py          Agent           缝合;每步过罩
src/envs/
  survival.py       GridlessSurvival  域无关微环境,规则周期突变
experiments/
  regime_shift.py   调制体 vs 消融体的存活对照(证伪测量)
tests/              确定性机制单元测试
```

## 运行

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python experiments/regime_shift.py
```

PowerShell:

```powershell
$env:PYTHONPATH="src"; python -m unittest discover -s tests -v
$env:PYTHONPATH="src"; python experiments/regime_shift.py
```

## 文档导航(agent 接力从这里开始)

| 文档 | 用途 |
|---|---|
| `AGENTS.md` / `CLAUDE.md` | agent 工作指令(宪法约束、流程、完成门) |
| `docs/AGENT-OS-PRODUCT-BLUEPRINT-V1.md` | **唯一产品定义**: Agent OS、双轨分层 monorepo、产品/研究边界、研究组合审计 |
| `docs/PROJECT_PLAN.md` | **接力主文档**:任务卡、founder 决策倾向、授权边界 |
| `docs/PRD.md` | Research Track 历史需求与证伪门；不得替代产品 Blueprint |
| `ROADMAP.md` | Product 路线入口 + Research Track 历史阶段与门 |
| `ENGINEERING.md` | 技术栈、规范、实验纪律 |
| `docs/adr/` | ADR-0001 引导;ADR-0002 硬相关性环境+G1;ADR-0003 自主决策协议 |
| `codebase_index.md` | 模块索引与当前状态 |

## 设计依据

- `../docs/research/RR-0001-unified-autonomous-agent-architecture.md`(架构与七承诺)
- `../docs/research/RR-0003-autonomous-agent-prototype-design.md`(本原型设计,含 G0 证伪记录)
- `../docs/research/RR-0004-artifact-map.md`(历史三仓角色记录；产品身份已由 Blueprint v1 supersede，研究证据边界继续有效)

## Research v0 historical boundary

不接 LLM(留 hook);不做 RAP 多节点;不做 ρ 自调(人定常数);不做真实执行器
(纯仿真→罩最小化即够);不做世界模型学习残差。可纠正性罩的 `op_*` 面在 v0 以
约定+测试与智能体分离,真部署须落到 infra/账号层(智能体进程不可触达)。
