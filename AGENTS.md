# AGENTS.md — Agent OS monorepo 智能体工作指令(权威版)

## 0. Current State First

Before broad reading, read `docs/CURRENT_STATE.yaml`. It is the live handoff anchor for branch, implementation state, research verdicts, test count, ADR status and next task. Then read `docs/AGENT-OS-PRODUCT-BLUEPRINT-V1.md` for product authority. Static state summaries elsewhere are non-authoritative.

Minimal read order for agent handoff:

1. `docs/CURRENT_STATE.yaml`
2. `docs/AGENT-OS-PRODUCT-BLUEPRINT-V1.md`
3. `docs/PROJECT_PLAN.md`
4. `codebase_index.md`
5. ADRs/tests/code named by those files

任何 AI agent(Claude 或其他)在本仓库工作前必须读完本文件。Claude Code 另见 `CLAUDE.md`(指回本文件并补充平台细节)。

## 1. 本仓库是什么

本仓库是完整 **Agent OS 产品主仓**，采用 Product Track + Research Track 的双轨分层 monorepo。历史目录目前主要承载通用智能机制研究；后续产品应用、包、domain packs 与研究候选在同仓演化，但有严格的真值和依赖边界。

- Product Track = Task Workspace、WorkflowGraph、运行时、provider/BYOK、插件、知识/RAG、agent/subagent、治理、eval、SDK 与 domain packs。
- Research Track = CWM、belief/action、belief ledger、outcome learning、corrigibility、形式化模型、预注册实验和负结果。
- `domain_packs/data_agent` = 目标中的首个企业垂直；现有外部 Data OS 仓只作
  ADR-0054 / SPINE-1 迁移来源。SPINE-0 不依赖 donor；任何阶段都禁止 runtime
  cross-import。
- `ai-agent-engineering-workflow` = 内部研发治理，不是产品运行时。

产品定义以 `docs/AGENT-OS-PRODUCT-BLUEPRINT-V1.md` 为准。研究宪法和历史证据仍由 baseline 工作区 RR 文档、本仓 ADR、结果文件及 `docs/CURRENT_STATE.yaml` 约束。Blueprint 不改写实验结论。

## 2. 不可协商约束(宪法,违反即返工)

1. **罩的分离**:`CorrigibilityShell` 的 `op_*` 方法是外部主权面。Agent/策略/环境代码路径**永不**调用 `op_*`;不得给 Agent 添加任何能清除暂停、放宽禁令、改写审计的方法。测试必须持续断言这一点。
2. **LLM 无无类型最终权限**:Product Track 可让 LLM 参与语义理解、规划、生成与验证，但模型输出必须通过 typed contract、capability policy 与 outcome/eval 路径；不得直接成为高后果命令。Research Track 已冻结实验继续遵守其原始 LLM 边界。
3. **OS Core 零领域耦合**:通用产品包不得内置指标、SQL、电商等领域语义；业务语义只能进入 `domain_packs/`、插件或连接器。
4. **无跨仓运行时 import**:外部仓库不能成为本产品运行时的隐式依赖。ADR-0054
   仅授权 SPINE-0 验收后的一次 history-safe Data Agent 迁移：full-history scan 必须
   在 import 前 `PASS`，否则 filtered mirror 或 `ABORT`。它不授权 runtime import、
   双向同步、push/merge 或任何其他跨仓搬运。Research Track 也不得被 Product Track
   直接 import；机制晋升必须经过 Blueprint 的 `ResearchCandidateManifest` 和产品复验。
5. **证伪纪律(Research Track 最高工程纪律)**:每个实验的通过门在跑之前预注册；**绝不**为让门变绿而调机制；负结果如实记录进 ADR/RR，与正结果同等待遇。Product Track 的功能测试不得反向证明研究主张。
6. **Stake-first 是研究约束,不是全产品效用公理**:受该承诺约束的历史机制必须保留推导链；产品层同时显式建模用户目标、政策、成本、SLO、风险与结果，不得强行把所有价值压成代谢变量。
7. **测试按轨分层**:确定性机制用单元测试，研究比较用冻结实验；产品能力必须有真实入口、失败路径、集成测试和端到端验收。任何一层的绿灯不得替代另一层。
8. **C7 靠隔离而非不可知**:更正/暂停/权限边界必须 non-writable、non-bypassable、可审计；不得把“agent 无法建模 C7”当安全假设。
9. **凭据和租户数据隔离**:API key、OAuth token、企业敏感数据不得进入 prompt、事件、日志或模型可见记忆；只通过受保护的 `CredentialRef`/broker 使用。

## 3. 命令

```bash
PYTHONPATH=src python -m unittest discover -s tests -v   # 全量测试(必须全绿才能提交)
PYTHONPATH=src python experiments/regime_shift.py         # 证伪测量(报告用)
```

PowerShell: `$env:PYTHONPATH="src"; python -m unittest discover -s tests -v`

## 4. 工程流程

```text
选 Product/Research Track → 读对应任务卡 → 写失败测试/验收 → 实现
→ 轨内验证 → 检查跨轨与产品/研究主张边界 → 更新 CURRENT_STATE/索引 → PR/评审
```

Research Track 涉及机制/门/边界时先写或更新 ADR，继续遵守 freeze-before-run。Product Track 涉及 contract、provider、credential、plugin、knowledge、policy、action 或 outcome 时必须做架构/安全评审。技术栈与当前研究编码规范见 `ENGINEERING.md`；总体顺序见 `ROADMAP.md`。

## 5. 自主决策协议(founder 已授权,见 ADR-0003)

路线级决策由 agent 辩论(可用 decision-referee / technical-architect 等子 agent 或结构化自我批判)→ 对照 founder 决策倾向画像(`docs/PROJECT_PLAN.md` §2)→ 自审 → 拍板 → 记录 ADR(含反方意见)。

**保留给 founder 的决策**(agent 只可建议,不可代拍):修改 C1–C7 或任何预注册门判据；改变 Blueprint 产品身份/双轨边界；开放新的高后果执行权限；修改更正/权限安全基底；跨仓迁移或依赖边界变更；花钱/对外发布；对任一核心研究主张下“最终失败”结论。Founder 已通过 ADR-0054 对一次 Data Agent 迁移给出窄授权，但执行、push 和 merge 仍受该 ADR 的独立门约束；任何扩张需新 founder ADR。

## 6. 完成门(任务交付前自查)

- 真实入口调用了新代码;有失败路径测试;全量测试绿。
- 机制变更有 ADR;实验结果(无论正负)已记录。
- codebase_index.md 已更新;罩分离断言未被削弱。
- 未为过门而调机制(自我声明写进 PR)。
- Product Track 变更说明用户入口、typed contract、权限/凭据、可观测性、outcome 验证和回滚路径。
- 结论明确标注为产品实现、研究结果或内部流程，禁止互相回填。
