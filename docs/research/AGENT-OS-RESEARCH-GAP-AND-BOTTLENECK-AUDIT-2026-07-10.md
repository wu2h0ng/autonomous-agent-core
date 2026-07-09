# Agent OS Research Gap and Bottleneck Audit

> Date: 2026-07-10
> Status: DESIGN-APPROVED / DOCS-ONLY / NO EXPERIMENT RUN AUTHORIZED
> Founder decision: Option B — history-preserving product migration plus modular monolith
> Product authority: `docs/AGENT-OS-PRODUCT-BLUEPRINT-V1.md`
> Machine-readable queue: `docs/research/AGENT-OS-PRODUCT-GROUNDED-EXPERIMENT-MATRIX.yaml`

## 0. Decision

现有研究不是无效，而是**证据范围窄、系统外部效度不足、产品消费路径缺失**。它已经形成可利用的机制候选和反自欺纪律，但尚不能支撑完整 Agent OS、通用自主人工智能或市场超越主张。

本审计作出五项组合决策：

1. 保留 modular cognition、typed action、external correction、belief provenance 和 honest falsification。
2. 修正 deterministic disposer、C7 unmodelable、CWM universal brain、full-set no-narrowing 等过强架构命题。
3. 将现有 `src/aac/product_*`、`production_entry.py`、`execution_bridge.py` 视为 Research Track 演示代码，不作为 Product Track 基础。
4. 在 `SPINE-E2E-1` 之前不再开启脱离真实产品任务的新机制 r-final；先建立可运行的产品脊柱作为下一阶段实验仪器。
5. 后续研究必须绑定一个产品失败、一个稳定消费 contract、一个 cheap/current-product baseline 和一个 stop condition。

以上不改写任何历史 `MET`、`NOT_MET`、`NULL`、`RED`、`PARK` 或 `INSUFFICIENT_DATA_HONEST_NEGATIVE` verdict。

## 1. Fresh evidence boundary

本审计交叉读取：

- 本仓 `docs/CURRENT_STATE.yaml` 与 2026-07-10 reconcile baseline；
- `docs/AGENT-OS-PRODUCT-BLUEPRINT-V1.md`；
- 父级 `docs/GOAL-BLUEPRINT.md`、`PROGRAM-PANORAMA-END-TO-END-2026-07-10.md`、RR-0036、RR-0047、RR-0050、RR-0051；
- `ai-native-business-data-agent-os/docs/CURRENT_STATE.yaml` 和其真实 Agent Runtime、checkpoint、policy、approval、tenant、trace、persistence 路径；
- 本仓实际 `governed_loop.py`、`belief_ledger.py`、`planner.py`、`execution_bridge.py`、`product_api.py` 与 `production_entry.py`。

证据等级继续采用 Blueprint 的 E0–E5：理论/文档、单元/玩具、控制模拟、离线真实数据、shadow/pilot、生产结果。当前 core 研究主要处于 E1–E3；Data Agent 产品有真实 runtime 和内部走查，但尚不能反向证明通用自主性。

## 2. Existing research: what is actually supported

| Line | Honest evidence | Product relevance | Current limit | Decision |
|---|---|---|---|---|
| Corrigibility shell / gate isolation | deterministic and process-isolation tests; pause/deny invariants | very high | not yet an external product security boundary; no policy-epoch race proof across all side effects | HARVEST principles; rebuild in Product Track |
| G10 confidence-gated policy | narrow synthetic fresh-seed positive result, trap-complete in its family | high for act/ask/retry | no real task, provider or human-intervention validation | REVALIDATE on product tasks |
| CWM discovery / intervention | controlled simulation, Sachs/public-data and adapter loops with scoped positives/negatives | high in identifiable intervention domains | oracle dependence remains in important cases; no production actuator or delayed business outcome | CONTINUE selectively through applicability gate |
| BeliefLedger / failure attribution | provenance classes, conflict flags, demotion and poisoning guards | foundational | in-memory, claim-id-centric, no tenant/time/evidence-object lifecycle, no product correction UX | PROMOTE contract ideas; redesign storage model |
| Goal formation | bounded leverage-based and recursive toy mechanisms | medium | confuses principal objective, instrumental subgoal and discovered leverage; no user negotiation or commitment semantics | RECAST under Goal/Commitment compiler |
| Planner / Temporal Options | proposal-form finite-action planner; Temporal Options remains PRE_SPEC_DRAFT | critical | no dependency graph, waiting, replanning, compensation, durable state or demonstrated capability gain | PRODUCT-PRESSURE PRIORITY |
| Online adaptation / regime shift | controlled environment and CWM maintenance evidence | high | no contamination, forgetting, rollback or multi-tenant product stream evidence | REVALIDATE after durable belief/outcome substrate |
| LLM bounded organ | useful broad prior and typed proposal experiments; hang/refusal guards | essential | provider reliability, prompt injection, tool-result poisoning and cost behavior not system-tested | PRODUCTIZE behind Provider/Capability contracts |
| RAP / swarm / MoE | RAP core route NOT_MET; MoE assessed as capacity-only | optional | no matched-budget product ROI | PARK as intelligence thesis; test only as workflow optimization |
| Viability/endogeneity/G-Eco/autonomy-axis | useful negative-result map; multiple cheap baselines absorbed candidates | low near-term | route became ontology-heavy and product-light | HARVEST budget/surprise lessons; PARK axis search |
| Strong-locus/open-world discovery | certified harnesses plus honest insufficient-data/negative boundaries | long horizon | data adequacy and non-oracle discovery remain open | BOUNDED OPTION; milestone budget only |
| Evolution/self-modification | L0–L3 external candidate boundary is useful | medium future | no evidence for runtime core self-modification; safety substrate rewrite remains unacceptable | Evolution Lab candidates only; L4/L5 forbidden |
| Research governance | preregistration, locks, baselines, negative-result maps | high internal value | prior artifact drift and narrative-ledger gaps show enforcement is not uniformly complete | KEEP and automate; never market as product capability |

## 3. Material research deficiencies

### 3.1 No whole-system baseline

大部分实验比较一个候选机制与局部 cheap baseline，尚未回答：

```text
Does the complete Agent OS produce more verified outcomes per unit of human attention,
time and cost than a strong model-plus-tools baseline?
```

缺少这一层，局部机制即使 `MET` 也可能只增加系统复杂度。

### 3.2 External validity is too low

当前主要结果来自有限 action space、短 horizon、已知变量、免费/同步干预或离线数据。真实产品面对：

- provider/tool failure and nondeterminism;
- partial observability and changing permissions;
- irreversible or delayed consequences;
- ambiguous goals and evolving acceptance criteria;
- multiple users, tenants and conflicting corrections;
- cost, latency, rate limits and secret boundaries;
- long waits, process restarts and repeated work.

这些不是工程杂项，而是自主系统的主要环境。

### 3.3 Temporal agency remains unproven

现有 `CWMPlanner` 本质是有限 action 的一次排序。Temporal Options 仍是 PRE_SPEC_DRAFT，且其 synthetic sequence task 即使通过，也只能说明 bounded macro 优于 schedules，不能证明真实长程规划。

缺失的机制对象是：

- persistent task state;
- dependency and temporal constraints;
- event/wait semantics;
- bounded replanning;
- compensation and rollback;
- deadline/resource conflict resolution;
- recovery after interrupted execution.

### 3.4 Belief is not yet product memory

当前 BeliefLedger 的 lattice/provenance 思路合理，但尚缺：

- tenant/workspace/task scope;
- valid-time and transaction-time;
- evidence/artifact references;
- supersession and correction actor;
- confidence calibration by claim class;
- retrieval policy and access control;
- deletion/retention and privacy propagation;
- rollback of a learned artifact and downstream dependency invalidation.

向量检索或 reranking 不能替代这些语义。

### 3.5 Outcome learning lacks causal and operational credit assignment

现有 outcome feedback 多数是即时 scalar、self-report 或“成功则 remember”。真实任务需要区分：

- action executed vs acknowledged vs observed;
- expected outcome vs measured outcome;
- local completion vs business effect;
- causal contribution vs temporal correlation;
- delayed effect vs unrelated regime change;
- failed action vs failed verifier vs failed provider;
- partial success and compensation.

没有这一层，governed outcome learning 会把叙述当事实并扩大错误。

### 3.6 CWM has no eligibility discipline

当前路线有 fit notes，但产品还没有机器可执行的 CWM eligibility decision。必须明确：

- variables enumerable?;
- intervention legal and feasible?;
- outcome observable within a useful window?;
- confounding/latent structure within model assumptions?;
- sample and intervention budget sufficient?;
- action reversible enough for exploration?;
- observational/non-causal fallback available?

不满足时应 abstain/fallback，而不是强行输出 DAG。

### 3.7 Human governance has not been validated as cognition

Approval 可以成为真正的协同认知，也可以只是 rubber stamp。缺少对下列指标的真实评测：

- selection concentration;
- modify/revise/reject rate;
- approval latency and fatigue;
- evidence consulted before decision;
- correction quality and downstream recovery;
- whether alternatives are meaningful or strawman padding.

Data Agent P2-A 已提供正确的产品入口，应被纳入 Agent OS experiment matrix。

### 3.8 Security claims rely too much on structural absence

“agent object 没有某方法”或“模型类型不能写 C7”不足以构成部署安全。还需：

- separate identity/credential boundary;
- policy/correction epoch checked immediately before side effect;
- lease revocation and stale-worker denial;
- TOCTOU/race and replay tests;
- secret non-observability;
- plugin sandbox and egress policy;
- cross-tenant noninterference;
- signed/hashed approval-to-action binding.

## 4. Architecture assessment

### 4.1 Keep

- Agent is a persistent governed loop, not a model.
- Multiple model/world-model implementations behind typed ports.
- Capability-scoped tools and explicit side effects.
- Human/institutional correction outside model authority.
- Evidence, belief and outcome as separate objects.
- Research-to-product promotion through versioned manifests and product revalidation.
- One Task Workspace and one canonical WorkflowGraph IR.
- Data Agent as a domain pack, not OS core.

### 4.2 Revise

| Inherited proposition | Problem | Replacement |
|---|---|---|
| deterministic contentless disposer selects the winner | semantic selection is contentful; this covertly makes governance an intelligence oracle | advisory `DecisionPolicy` ranks; deterministic `PolicyKernel` admits/denies; executor uses an admitted, version-bound choice |
| C7 is unmodelable | observable enforcement can be modeled; security cannot depend on ignorance | C7/correction is non-writable, non-bypassable, externally authorized and epoch-checked |
| full choice set / no narrowing | impossible in open action spaces; encourages strawman padding | declare candidate-generation envelope, coverage evidence, excluded-class reasons and diversity/dominance checks |
| CWM is the planning brain | causal models are only one world-model family | `WorldModelPort` + machine-readable applicability/fallback decision |
| human is deployed C7 | conflates legitimate principal with enforcement substrate | human/principal issues approvals/corrections; `CorrectionAuthority` enforces them |
| τ-consistency proves boundaries lossless | formal vocabulary does not prove a concrete serializer/abstraction | contract-level semantic round-trip/counterexample tests; use τ-consistency only where mappings are formally specified |
| goal formation from leverage | means are mistaken for ends | principal Goal -> negotiated Commitment -> generated subgoals; leverage only proposes means |

### 4.3 Retire from product authority

- “arbitrary domains with zero rebuild” as a release criterion;
- “no separable autonomy axis” as a universal theorem;
- “unmodelable correction” as a security claim;
- “product-grade” labels on research-only causal-discovery entrypoints;
- LLM-generated API descriptions reported as successful execution;
- NoOp/proposal results reported as executed outcomes.

## 5. Code-truth quarantine

These files remain useful research evidence but are explicitly non-authoritative for Product Track:

| Path | Defect | Disposition |
|---|---|---|
| `src/aac/execution_bridge.py` | declared `gate` is not consumed by `execute_intervention`; LLM backend returns success without executing generated API call; NoOp returns success | quarantine; no product import |
| `src/aac/production_entry.py` | “production” entry runs with empty data and converts exceptions into status records | rename/retain as research harness later; no runtime reuse |
| `src/aac/product_api.py` | unauthenticated causal discovery server, no tenant/policy/credential boundary | research demo only |
| `src/aac/product_engine.py` | narrow causal engine labeled product-grade; assumptions and confidence are not a product contract | candidate CWM implementation behind future `WorldModelPort` only |
| `src/aac/planner.py` | finite ranking, no durable temporal execution | research proposal organ only |
| `src/aac/commitment_ledger.py` | action-score memory, not a user/principal Commitment ledger | retain research name/history; do not map directly to product `Commitment` |

Quarantine means no deletion and no verdict change. It means Product Track may not depend on these paths until a `ResearchCandidateManifest` plus product reimplementation/revalidation exists.

## 6. Breakthrough bottleneck

### 6.1 Foundational bottleneck

The load-bearing research problem is:

```text
Can one governed system maintain and revise task-relevant state across long horizons,
choose when to act/ask/experiment, recover from failures, attribute delayed outcomes,
and improve future work across domains without increasing severe side effects or
corrupting its correction boundary?
```

CWM addresses a subset of state/action consequence modeling. BeliefLedger addresses a subset of revisable state. G10 addresses a subset of act/ask calibration. None currently establishes the integrated property.

### 6.2 Breakthrough criterion

A credible breakthrough requires all of:

1. same product core across at least developer, Data Agent and personal task families;
2. no core-code change for the second/third domain, only domain pack/tool/knowledge configuration;
3. verified outcome success above a strong model-plus-tools baseline on held-out tasks;
4. lower human intervention minutes after repeated tasks;
5. successful restart/recovery and stale-belief correction;
6. zero severe policy/correction/tenant violations;
7. explicit losses, cost and latency, not only successful traces.

This is an operating-envelope breakthrough, not a claim of universal AGI.

## 7. Product-grounded experiment program

The canonical queue is the adjacent YAML matrix. It contains twelve experiments in three waves.

### Wave P0 — make the spine a valid instrument

- `SPINE-E2E-1`: real Goal -> Commitment -> WorkflowGraph -> AgentRun -> ActionContract -> outcome path.
- `WFG-ROUNDTRIP-1`: NL/visual/structured views preserve one canonical IR.
- `CORRECTION-BOUNDARY-1`: epoch revocation and race/replay resistance.
- `PROVIDER-CHAOS-1`: timeout, malformed output, rate limit and fallback behavior.

### Wave P1 — attack the true autonomy bottleneck

- `LH-RECOVERY-1`: long-horizon continuity, interruption and replanning.
- `BELIEF-CORRECTION-1`: staleness, contradiction, contamination and tenant isolation.
- `OUTCOME-CREDIT-1`: delayed outcome and attribution quality.
- `HUMAN-GOV-1`: approval quality vs rubber-stamping.

### Wave P2 — decide which research mechanisms earn promotion

- `CWM-ELIGIBILITY-1`: selective use/fallback of causal modeling.
- `G10-PRODUCT-1`: real act/ask/retry calibration.
- `SUBAGENT-ROI-1`: matched-budget subagent value.
- `XDOMAIN-TRANSFER-1`: domain-pack transfer without core changes.

No experiment in the matrix is preregistered, frozen or authorized to run by this document. The architecture packet determines when its prerequisites exist.

## 8. Research admission and promotion gates

Every future mechanism route must provide:

```text
ProductFailureRef
CurrentProductBaselineRef
CheapBaselineRef
StableConsumptionContract
ResearchCandidateManifest
OperatingEnvelope
KillCondition
BudgetCap
SafetyAndCorrectionImpact
ProductRevalidationPlan
```

Promotion order:

```text
research candidate
  -> exact evidence manifest
  -> stable Product Track port
  -> baseline implementation
  -> product reimplementation/adapter
  -> held-out product comparison
  -> canary/shadow
  -> explicit promotion decision
```

Raw experiment imports and “same repository therefore trusted” shortcuts are forbidden.

## 9. Portfolio decision

Until Product Done alpha exists:

- 70% Product Track spine and real workflows;
- 20% translational work on temporal recovery, belief/outcome and CWM eligibility;
- 10% frontier options with explicit kill tests.

New autonomy-axis, endogeneity or self-modification routes default to `PARK` unless a production failure cannot be addressed by the existing experiment matrix.

## 10. Final verdict

```text
Research value: MATERIAL BUT INCOMPLETE
Architecture thesis: DIRECTIONALLY SOUND, REQUIRES AUTHORITY AND APPLICABILITY REFACTOR
Product readiness from research core: NOT MET
Next valid instrument: T-P-OS-SPINE-0
New standalone mechanism r-final before spine: NO_ACTION
```
