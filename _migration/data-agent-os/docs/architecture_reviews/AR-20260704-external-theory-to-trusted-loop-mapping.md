# AR-20260704: External theory scan — mapping A-level sources to the Trusted Loop contracts

- Status: **Accepted** (docs-only; no code change). **This AR requires no code change and introduces no runtime dependency.**
- Review identity: `builder-id: kimi-agent`, `reviewed-by: founder`
- Parent: `docs/decisions/ADR-0001-p5-substrate-harvest.md` (design-input candidate maintenance under P5)
- Trigger: `/Users/mima1234/Documents/AI-Agent-Projects/docs/research/external-theory-scan-2026-07-04.md` (workspace-root cross-repo research record). This file may not be present in every checkout; methodology and source list are therefore summarized inline below so the AR remains reviewable without it.
- Touches (requires AR per CLAUDE.md / AGENTS.md): `SemanticObject`, `MetricContract`, `ProviderContract`, `DataProductCandidate`, `OperationContract`, `EvidenceChain`, `ActionProposal`, `ApprovalRecord`, `RunTrace`/`OperationTrace`, governance boundaries. **No contract/schema change in this AR.**

> **Terminology notes for this AR**
> - **A-level sources**: sources judged in the trigger scan as "highly constructive" — directly mappable to a project contract or gate.
> - **C-level sources**: sources judged as useful only for market-direction validation (vendor blogs, product press releases).
> - **C7 / SD4**: object-layer concepts. C7 is the immutable correction boundary; SD4 (Self-Determination Depth 4) is the founder-reserved level at which an agent could revise or refuse its correction channel. These are referenced only as background; this AR does not propose any change to them.

## 1. Context

A scan of external papers, preprints, industry blogs and self-media reports was conducted (see trigger scan). The scan asked whether any source provides a **decisive** or **constructive** theory for the project. Its conclusion:

- No single external theory decides the project architecture.
- A small set of sources is **constructive** for the deployment-layer contract spine.
- A larger set of vendor/self-media “AI OS” claims is useful only as market-direction validation, not as engineering input.

This AR records how the constructive sources map onto the existing Trusted Loop design, so that future ADRs/feature work can cite a stable design input rather than ad-hoc web references.

### 1.1 Scan methodology (abbreviated)

Search terms covered: enterprise AI OS, data mesh / data product, semantic/context layer, LLM-based autonomous agents, agent capability contracts, governed multi-agent orchestration, causal world models, corrigibility, NIST/EU AI governance. Sources were graded A/B/C/D:

| Grade | Definition | Examples |
|-------|------------|----------|
| A | Directly mappable to a project contract/gate; provides reusable principles | Dehghani Data Mesh; CEAD/ACC; Queen-Bee/BeeSpec; Semantic/Context Layer; NIST/EU AI Act/CSA ATF |
| B | Theoretical motivation or research baseline; implementation must be project-specific | Corrigibility / Off-Switch Game; Ha & Schmidhuber World Models; causal reasoning literature |
| C | Market-direction validation only; not architecture evidence | SelfAI, GrayMatter, Datafi, DSW UnifyAI, Kingdee Lingee, LoQal AI, most 36kr/TechCrunch product posts |
| D | Interesting but outside current boundary (blockchain/DAO, TEE, general Data Fabric, embodied multimodal agents) | NetX contract-stack/DAO, some Data Fabric pitches, embodied GUI agents |

### 1.2 Sources explicitly considered and excluded from design input

- **Vendor “AI OS” marketing** (SelfAI, GrayMatter, Datafi, DSW UnifyAI, Kingdee Lingee, LoQal AI, AgileSoft Labs): all repeat the “enterprise AI operating system” framing but provide no contract, safety, eval, or trace specification. They validate demand, not design.
- **General Data Fabric / warehouse-native semantic layers**: the project boundary is to **ride existing data planes** through `ProviderContract`, not to build a new fabric. These sources are noted but not adopted.
- **Blockchain / DAO / TEE governance papers** (e.g., NetX contract-stack): outside MVP per the AGENTS.md hard boundary that privacy computing, blockchain, TEE, federated learning, etc. are future architecture capabilities only.
- **Embodied / multimodal agent surveys** (Agent AI: Surveying the Horizons of Multimodal Interaction): not relevant to the current business-data OS vertical.

## 2. Decision — what this AR records

The following mappings are accepted as **design inputs** (not product claims, not runtime changes):

1. **Data Mesh / Data Product** (Dehghani 2019/2020) justifies the `DataProductCandidate` / `ProviderContract` decomposition: domain-owned, versioned, interface-bound data units consumed through typed contracts. `DataProductCompiler` is retained as an architectural target but is not yet a delivered runtime component.
2. **Semantic Layer + Context Layer** (Solix/Decube/Contextual AI 2026) justifies the co-existence of `MetricContract` (definition) and `EvidenceChain`/governance rules (usage context). A metric without evidence/usage policy is insufficient for agent action.
3. **CEAD / Agent Capability Contract** (arXiv:2605.08258, 2026) validates the contract-first decomposition already used in ADR-0002/0003/0004: purpose/non-purpose, autonomy level, tool scope, data classification, verification, human-approval triggers, eval evidence, observability, versioning. CEAD’s L0–L4 autonomy levels are **analogous to** but not identical to the project’s R0–R3 governed tier + R4/R5 proposal-only tier.
4. **Queen-Bee / BeeSpec** (arXiv:2606.06545, 2026) supports the **control-plane / execution-plane separation** and task-scoped least-privilege tool provisioning already present in the runtime/approval design. The project’s concrete artifact is `GovernanceDecisionClient` / `LocalGovernanceDecisionClient` at the governance gate, plus `AgentRunContext` and `ActionConnectorContract` scoping. “Disposer” is an architectural nickname in code comments, not a formal class.
5. **PARCER** (arXiv:2603.00856, 2026) provides operational-contract patterns (adaptive budget, fallback nets, deterministic checkpoints). The project already has `AgentRunContext` budget/timeout guards, checkpoint/fallback behavior, and `AgentTraceWriter`. The OTel-compatible trace bridge mentioned by PARCER is **not yet implemented** in the project.
6. **NIST AI RMF / EU AI Act / ISO 42001 / CSA Agentic Trust Framework** provide compliance framing for the R0-R3 autonomy tier, human oversight, audit, and risk-classification gates.

## 3. Mapping table

| External source | Core idea | Maps to project concept | Implication for design |
|-----------------|-----------|------------------------|------------------------|
| Dehghani, *Data Mesh* (2019) | Domain-oriented decentralized ownership; Data as a Product; self-serve platform; federated computational governance | `DataProductCandidate`, `ProviderContract`, `SemanticObject` (`DataProductCompiler` is an architectural target, not yet delivered) | Keep `ProviderContract` as the thin, domain-owned interface to existing data planes; do not rebuild a generic Data Fabric inside OS Core. |
| Solix / Decube / Contextual AI (2026) | Semantic layer = metric definitions; Context layer = governance rules, lineage, decision precedents, evidence | `MetricContract` + `EvidenceChain` | This mapping adopts only the **evidence/lineage/usage-policy** slice of the industry context-layer concept. Broader runtime auth/business-rule engines are not claimed to be inside `EvidenceChain`; every metric must still carry its definition and supporting evidence. |
| CEAD / Agent Capability Contract (arXiv:2605.08258) | 13-field contract: purpose, non-purpose, L0–L4 autonomy, I/O schema, tool scope, data class, memory design, verification, human interaction, eval evidence, observability, versioning | `OperationContract`, `ActionProposal`, `RuntimePolicyGate`, `ApprovalRecord`/`ApprovalLiteRuntime`, `RunTrace`/`OperationTrace` | See §3.1 for field-level coverage. In short: purpose, autonomy level, tool scope, data classification, verification, human-approval triggers, eval evidence, observability, and versioning map directly to existing contracts; memory design and non-purpose are **not yet** represented as first-class fields. CEAD L0–L4 ≠ project R0–R5. The project’s approval model is operator-only and stricter than CEAD’s generic "human interaction" field. |
| Queen-Bee / BeeSpec (arXiv:2606.06545) | Queen control plane compiles a scoped `BeeSpec` (role, allowed tools, tenant scope, policy profile, approval gate); Bee executes only within spec | `GovernanceDecisionClient` / `LocalGovernanceDecisionClient`, `AgentRunContext`, `ActionConnectorContract`, `RuntimePolicyGate` | Reinforce task-scoped least privilege and explicit approval gates; avoid monolithic broadly-privileged agents. Note: current governance gate is proposal-time; ADR-0004 execution-time recheck is a known gap (see §4). |
| PARCER (arXiv:2603.00856) | Operational contract with adaptive budget, fallback nets, deterministic checkpoints, OpenTelemetry-compatible trace | `AgentRunContext` budget/timeout guards, checkpoint/fallback, `AgentTraceWriter` | Budget/checkpoint/fallback concepts are aligned. PARCER’s OTel-compatible trace implies a **distributed telemetry architecture**; the project currently uses an in-process `AgentTraceWriter`, so the OTel bridge is an architectural gap, not just a missing hardening target. |
| NIST AI RMF / EU AI Act / ISO 42001 / CSA ATF | Risk-tiered governance, human oversight, immutable audit, least privilege, eval-as-release-gate | R0–R3/R4–R5 boundary, `ApprovalRecord`, `RunTrace`/`OperationTrace`, eval threshold report | Compliance requirements map onto existing R0–R3 gates and proposal-only R4/R5; no new runtime needed to satisfy framing. |

### 3.1 CEAD field-level coverage note

CEAD proposes 13 capability-contract fields. The following table shows the current project mapping status. A blank or "partial" cell means a future ADR must add or refine the field before claiming CEAD parity.

| CEAD field | Current project mapping | Status |
|---|---|---|
| purpose | `OperationContract.intent` / `ActionProposal.goal` | mapped |
| non-purpose | implicit in approval policy; no dedicated schema field | **not yet first-class** |
| autonomy level (L0–L4) | `RuntimePolicyGate` / R0–R5 tiering (R4/R5 proposal-only) | mapped |
| I/O schema | `OperationContract.input_schema` / `output_schema` | mapped |
| tool scope | `ActionConnectorContract` allowed tool set | mapped |
| data classification | `ProviderContract` / `DataProductCandidate` sensitivity tags | mapped |
| memory design | no dedicated memory-design field in current contracts | **not yet first-class** |
| verification | `EvidenceChain` validators + eval threshold report | mapped |
| human interaction / approval | `ApprovalRecord` / `ApprovalLiteRuntime`, operator-only | mapped, stricter than CEAD |
| eval evidence | eval threshold report + `RunTrace`/`OperationTrace` | mapped |
| observability | `AgentTraceWriter`, `RunTrace`, `OperationTrace` | mapped |
| versioning | `DataProductCandidate` / contract version fields | mapped |

## 4. Boundaries and non-decisions

This AR **does not** decide or authorize any of the following:

- **No new runtime code.** No new agents, connectors, MCP dependencies, blockchain/DAO components, or cross-repo imports.
- **No new product claim.** External “AI OS” marketing is not evidence that the project has delivered any capability.
- **No change to R4/R5 status.** R4/R5 remain proposal-only in MVP; the EU AI Act high-risk framing is acknowledged but does not authorize arming R4/R5 execution.
- **No change to C7/SD4.** Corrigibility/off-switch literature (object layer) is recorded as theoretical background only; any C7/SD4 design change requires a separate object-layer ADR/preregistration.
- **No endorsement of Data Mesh as a whole.** Only the “Data Product + interface contract + federated governance” slice is adopted; the project continues to **not** build a general-purpose federated data plane (per AGENTS.md hard boundary: do not rebuild Data Fabric or a general federated data plane).
- **No endorsement of MCP/A2A as Core dependencies.** Queen-Bee and CEAD mention MCP/A2A as interoperability channels; the project treats them as reference patterns, not runtime dependencies.
- **No claim of OTel trace integration.** PARCER’s OTel-compatible trace is noted as a pattern; the project’s OTel bridge is still pending a concrete collector target.
- **No execution-time governance recheck in this AR.** ADR-0004 states that approval-resume execution does not re-consult the governance seam in the current slice. Queen-Bee’s control-plane/execution-plane separation implies execution-time policy enforcement, which the project does not yet fully implement. Filling that gap requires a separate ADR (proposed as ADR-0005).

## 5. Engineering implications for future ADRs

When a future ADR proposes a new agent, connector, or action type, it should answer the questions implied by the mapping above:

- What is the `DataProductCandidate` / `ProviderContract` it consumes or produces?
- What `MetricContract` does it use, and what `EvidenceChain` backs each answer?
- What is its purpose/non-purpose, autonomy level, tool scope, and data classification?
- What deterministic validators, eval evidence, and approval triggers apply?
- What trace/audit events (`RunTrace`, `OperationTrace`, `AgentTraceWriter`) does it emit, and how does it fail closed?

These questions are already required by the existing engineering reality gates; this AR only adds external citations that support them.

## 6. Acceptance criteria (for this AR to be accepted)

```text
A-level external sources are mapped to existing Trusted Loop contracts in a stable,
reviewable document; no source is treated as decisive or as a product claim;
all non-decisions in §4 are preserved; type names and autonomy-tier distinctions
are accurate.
```

## 7. Review

- OpenCode external review: passed (ACCEPT with minor revision items, all addressed).
- CTO/founder acceptance: **accepted** by `founder` on 2026-07-04.
- Review identity: `builder-id: kimi-agent`, `reviewed-by: founder`.
- Once accepted, this AR becomes a parent design input for any future ADR that refines `DataProductCandidate`, `MetricContract`, `OperationContract`, or agent capability contracts.

## 8. References

### 8.1 Project records

- `/Users/mima1234/Documents/AI-Agent-Projects/docs/research/external-theory-scan-2026-07-04.md` (workspace-root cross-repo research record with full URLs and grading rationale)
- `docs/decisions/ADR-0001-p5-substrate-harvest.md`
- `docs/decisions/ADR-0002-governed-action-outcome-loop-v0.md`
- `docs/decisions/ADR-0003-agent-runtime-v0-trusted-substrate.md`
- `docs/decisions/ADR-0004-governed-decision-seam.md`
- `packages/contracts/src/agent_os_contracts/architecture.py` (`DataProductCandidate`, `OperationTrace`)
- `packages/contracts/src/agent_os_contracts/trusted_loop.py` (`RunTrace`)
- `packages/os_core/src/agent_os_core/approval_lite/__init__.py` (`ApprovalRecord`, `ApprovalLiteRuntime`)
- `packages/os_core/src/agent_os_core/governance_decision_seam/__init__.py` (`GovernanceDecisionClient`, `LocalGovernanceDecisionClient`)
- `packages/os_core/src/agent_os_core/agent_runtime.py` / runtime envelope code (`AgentTraceWriter`, `AgentRunContext`)

### 8.2 External sources

- Dehghani, Z. (2019). *How to Move Beyond a Monolithic Data Lake to a Distributed Data Mesh.*
- Dehghani, Z. (2020). *Data Mesh Principles and Logical Architecture.*
- Solix (2026). *Structured Context for AI: The Missing Operating System for Enterprise Intelligence.* https://www.solix.com/blog/structured-context-for-ai-the-missing-operating-system-for-enterprise-intelligence/
- Decube (2026). *Context Layer vs. Semantic Layer.* https://www.decube.io/post/context-layer-vs-semantic-layer
- Contextual AI (2026). *Semantic Layer vs. Context Layer.* https://contextual.ai/blog/semantic-layer-vs-context-layer
- Agentics Transformation (2026). *What Agentic-Ready Means.* https://agenticstransformation.com/briefings/what-agentic-ready-means.pdf
- CEAD / A Capability-Aligned Multi-Agent Architecture (arXiv:2605.08258, 2026). https://arxiv.org/html/2605.08258v1
- Queen-Bee Agents (arXiv:2606.06545, 2026). https://arxiv.org/html/2606.06545v1
- PARCER (arXiv:2603.00856, 2026). https://arxiv.org/html/2603.00856v1
- NIST AI Risk Management Framework. https://www.nist.gov/itl/ai-risk-management-framework
- EU AI Act (official texts).
- ISO/IEC 42001 AI Management Systems.
- CSA Agentic Trust Framework (Chinese overview): https://cheesecat.net/blog/2026-03-05-ai-agent-governance-zero-trust-zh-tw/
