# ADR-0002: 治理动作—结果闭环 v0（Governed-Action Outcome Loop v0）

- Status: **Accepted — gate recorded 2026-06-22**（founder 批准 D2；CEO→Product→Architecture→CTO gate 签批已记录，可按 SPEC 起 Codex 实现：T1→T7，8 RED eval 红先行，T3/T4 走 claude-diff-review，T5 回滚演示需 CTO 验收）。**边界不变（见 §5）**：仅宣称 P5 治理 + 受治理可逆动作，**不**宣称 G-Eco 自主；`execute_approved_operation` **不得**新建任何 R4/R5 自动执行路径（proposal→approval→governed-execute 全程人审）。**保留 founder 门**：merge-to-main / 对外发布不随实现自动放行。
- Date: 2026-06-22
- Implementation status: local `main` implements the scoped lower-half and upper-half, including review hardening for connector risk ceilings, dry-run/snapshot fail-fast behavior, approved operation/action/evidence binding, approved-execution audit trace persistence, connector-local ACK-uncertain audit, typed connector execution-audit projection, and connector-declared execution semantics. AR-20260624 accepted and fast-forward merge completed on 2026-06-24; push authorized; no automatic R4/R5 execution, external release, external ACK confirmation, or external-system exactly-once claim.
- 对侧 ADR: ADR-0001（P5 substrate harvest）—— 本 ADR 构建在 P5.1a / P5.1b / P5.2a 已落地的底座之上，不重建。
- 边界: 仅宣称 **P5 治理 / 可审计 + 受治理动作（可验证回滚 + operator 独占结果通道）**；**不**宣称 G-Eco 自主（参见 `docs/research/founder-decision-2026-06-22-route-c-reset-and-geco-freeze.md`）。
- Risk class: R3（工程变更中高风险；范围内演示的业务动作为 R4 级，但**可逆**且**proposal→approval→governed-execute**全程受治理，MVP 不做 R4/R5 自动执行）。

## 1. Context

### 1.1 战略缘起（founder 判断，2026-06-22）
Founder 提出："我们强调可信太久了，可信只是基本要求，不是真正价值。" 经一轮文档全扫 + 对抗性批判综合，结论：**可信是收费站，不是高速公路**。护城河不是"可信"本身，而是可信**解锁**的、只读竞品在结构上进不来的两件事：

1. **闭合到可度量 P&L 结果的受治理生产动作**；
2. **随在客户处时间复利的、按结果加权的客户专属知识**。

"可信"拆开后定价不同：管控类=纯入场券（founder 对）；正确性保证类=会复利的护城河（今天被错归为 QA）；**行动许可类=被伪装成底线的赢单楔子（不可压平）**；构造式证明类（corrigibility / 不可绕过中介 / adoption-only 价值）=窄 ICP 溢价 SKU，非横向价值。

### 1.2 已落地、不得重建的底座（代码核对 2026-06-22）
P5.1a/P5.1b/P5.2a 已合入 main（315 单测 + 2 eval 通过，验证于 2026-06-15）。以下为**真实**实现，新工作必须复用而非重写：

| 能力 | 现状 | 锚点 |
|---|---|---|
| 不可绕过中介（grounding 不变量） | EXISTS | `_assert_grounded()` @ `trusted_loop.py:766`，调用点 `:444`；`GroundingInvariantViolation` @ `:66` |
| 自报通道结构隔离（防 wirehead） | EXISTS | `record_outcome()` builder 钉死 `RUNTIME_SELF_REPORT` @ `trusted_loop.py:171,643` |
| operator 独占结果通道 | EXISTS | `AdoptionIngest`（唯一写入者）/`AdoptionLedger`/`AdoptionLedgerView`（只读）@ `adoption/__init__.py:107/55/90`；运行时仅得只读视图 @ `trusted_loop.py:177` |
| 采纳→知识晋升（唯一路径） | EXISTS | `promote_from_adoption(trace_id)` @ `trusted_loop.py:687` |
| 动作治理 / 审批 lite / 操作 trace | EXISTS | `ActionGovernance.build_operation_contract()` @ `action_governance/__init__.py:18`；`ApprovalLiteRuntime` @ `approval_lite/__init__.py:51`（loop 调用 `trusted_loop.py:493`）；`OperationTraceBuilder` @ `operation_trace/__init__.py:8` |
| 真·可逆写连接器 | EXISTS | `ActionRecordConnector`（snapshot+execute+rollback）@ `action_connectors/action_record/connector.py:51`；运行时 `rollback()` @ `trusted_loop.py:730` |
| corrigibility 暂停壳 | EXISTS（P5.2a） | `ShellView`（只读）+ `BlockCode.PAUSED` |

> **修正记录**：早期 RR-0002（2026-06-12）所列的 `record_outcome()` 自写 FeedbackStore 放水洞，**已由 P5.1a/P5.1b 关闭**。任何"修 wirehead"的提案到此为止——它不是本 ADR 的工作。

### 1.3 真正的缺口（价值捕获层，代码核对后）
| 缺口 | 现状 |
|---|---|
| 因果结果归因（pre-registered 业务指标 delta + holdout/反事实） | ABSENT —— 今天 feedback/adoption 仅 `outcome:str` + `metrics:dict`，无因果 |
| 一条**端到端闭合**的 R4 治理动作 loop | 零件齐备但**从未串起来端到端跑过一次**（动作→采纳→知识闭环未演示） |
| dry-run 执行路径 | ABSENT（`dry_run_required` 字段在 `architecture.py:109`，无执行逻辑） |
| 幂等键（防重试双写） | ABSENT |
| operator 结果摄入界面 | `POST /adoptions` 已真实接到 `AdoptionIngest` + `promote_from_adoption`；CLI `adopt` 缺；causal attribution typed payload 缺 |
| 审批后继续执行入口 | 缺。今天 `approval_required=True` 会停在 `AWAITING_APPROVAL`；`ApprovalLiteRuntime.approve()` 已存在，但 Trusted Loop 还没有 `approved -> dry_run/snapshot/execute` 的恢复入口 |
| 对 Snowflake Cortex Analyst / Databricks Genie 的可复现正确性 benchmark | ABSENT |
| 主动性 Monitor/Initiative、学习型 MetricContract、知识衰减 | ABSENT |

## 2. Decision

**v0 范围 = 在 Customer-0（FaSoLa）上把 _一条_ 可逆 R4 治理动作 loop 端到端闭合，并把 operator 独占的因果结果回灌成知识修订。** 不铺宽度。具体交付下列 D1–D6；D7 仅列为后续、**不在 v0 实现**（防范围蔓延）。

- **D1 因果结果归因（operator 侧）**：扩展 adoption 事件携带一个 _pre-registered 业务指标 delta_ + holdout/反事实引用；`promote_from_adoption` 按实现结果加权知识，而非二元成功。因果指标**经 operator 独占通道供给**，运行时不可写——保持 P5.1a 不变量。
- **D2 dry-run 执行路径**：为 `ActionRecordConnector` 实现 `dry_run`，遵循 `OperationContract.dry_run_required`；预览变更而不提交。挂在治理执行分支 `trusted_loop.py:522-558`。
- **D3 幂等键**：`ActionProposal`/`OperationContract` 增 `idempotency_key`，连接器 `execute()` 遵守；重试不双写。
- **D4 operator 结果界面**：保留已存在的 `POST /adoptions` operator 通道；新增 CLI `adopt`，并让 HTTP/CLI 共同接收 D1 的 causal attribution typed payload。`POST /outcomes` 继续只是 runtime self-report，不晋升知识。
- **D5 端到端 FaSoLa R4 loop**：补上审批后的恢复执行入口，使一个可逆动作走完 `grounding → operation contract → approval pending → operator approve → dry-run → snapshot → governed-execute(ActionRecordConnector) → OperationTrace → operator adoption 摄入因果结果 → promote_from_adoption → KnowledgeAsset 修订`，并演示一次真实 rollback。
- **D6 有区分度的 eval**：golden eval，满足下列任一即**失败**——(a) 动作在 EvidenceChain 不完整时执行；(b) 运行时自铸结果；(c) rollback 未还原快照；(d) 知识在无 adoption 事件时被晋升。
- **D7（仅列，不做）**：Monitor/Initiative 主动告警原语、学习型 MetricContract、知识衰减/去重、对 Genie/CAN 的正确性 benchmark。各自需独立 Goal Card。

## 3. 失败 / 负路径（必须有测试）
- 输入不安全 / 未授权 / 缺审批 / 已暂停 → `TrustedLoopBlocked`（既有 `BlockCode`），动作不执行；
- 重复提交（同 idempotency_key）→ 幂等空操作，不二次写；
- rollback → 还原 snapshot，`ActionRecordStore` 回到执行前状态；
- adoption 缺失 → 知识不晋升（`promote_from_adoption` 无源即 no-op）；
- 运行时试图写 `EXTERNAL_ADOPTION` → 结构上不可能（builder 钉死），并有断言测试守护。

## 4. 验收标准（Engineering Reality Gates 对齐）
- **Entry point**：`TrustedLoopRuntime` 治理执行分支 + 新 operator `adopt` 界面（HTTP/CLI）。
- **Contract**：`OperationContract`（新增 `dry_run`、`idempotency_key`）、adoption 事件（新增因果指标 delta）。
- **Failure mode**：见 §3，每条对应负路径测试。
- **Test validity**：测试在以下情况必须 _失败_——grounding 被绕过、运行时自铸结果、rollback 空操作、知识无 adoption 而晋升、重复提交双写。（即 §2 D6。）
- **Integration**：接入 Trusted Loop、adoption ledger、knowledge store、eval harness；FaSoLa 闭环可端到端运行。
- **Boundary**：OS Core 保持域无关——FaSoLa 专属逻辑只落在 `examples/` / domain pack / connector，`os_core` 不 import 客户逻辑（ADR-0007）。
- **Observability**：`OperationTrace` + `RunTrace` + adoption ledger 均更新。

## 5. 声明边界（对外 / 对内一致）
可宣称："P5 治理 + 受治理动作，证据不全则动作在结构上无法执行，错误动作可一键回滚，且系统无法给自己记功（结果走 operator 独占通道）。"
**不可宣称**："自主 / autonomous / G-Eco"——G-Eco 从未冻结或运行，A14 corrigibility 虽 production-ready 但其所骑自主论点未验证。越界即最大信誉风险。依据 `founder-decision-2026-06-22-route-c-reset-and-geco-freeze.md`。

## 6. 任务序列（Claude=spec/裁决，Codex=核心代码）
| # | 任务 | Owner | 产物 | Gate |
|---|---|---|---|---|
| T1 | 本 ADR + Goal Card + SPEC（含 D1–D6 契约 delta） | Claude/Codex | ADR-0002 / goal_card / SPEC.md | Architecture/CTO Gate |
| T2 | D6 eval 先行（区分度测试，红） | Claude 设计 / Codex 落 | 失败的 golden eval | 测试先于实现 |
| T3 | D2 dry-run + D3 幂等键（契约 + 连接器 + 运行时分支） | Codex | 实现 + 测试转绿 | claude-diff-review |
| T4 | D1 因果结果归因 + D4 operator 界面 | Codex | 实现 + 测试 | claude-diff-review |
| T5 | D5 FaSoLa 端到端闭环 + 一次真实 rollback 演示 | Codex | 端到端 run + trace 产物 | CTO 验收 §4 |
| T6 | CURRENT_STATE.yaml / code_index.md / 本 ADR 状态更新 | Claude | 文档同步 | Memory Agent |

## 7. Boundaries
- 不在 `os_core` 引入任何 Agent 框架运行时依赖（边界 #7）；
- 不跨仓 import（边界 #19）；autonomous-core 的 G10 等结果**不得**被本 OS 直接宣称，须独立企业域验证；
- 不做 R4/R5 自动执行（边界 #4）——v0 全程 proposal→approval→governed-execute，人审仍在环；
- "lite" = 功能受限但真实（边界 #16）：v0 必须有真实入口、负路径、能因绕过 gate 而失败的测试、trace 产物——禁止 skeleton/stub。

---
*本 ADR 为 Accepted（gate recorded 2026-06-22）。scoped v0 当前实现已 fast-forward 合入本地 `main`；AR-20260624 已在 2026-06-24 获 CTO/founder gate 接受，push 已授权。不得据此宣称自动 R4/R5 执行、外部发布或 G-Eco/autonomy 结论。*
