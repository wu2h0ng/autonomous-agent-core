# ADR-0032: Frontier architecture intake and structured-environment route

- Status: **Accepted (founder-authorized, 2026-06-15).** Docs-only research-route ADR. No mechanism implementation, no runtime behavior change, no new dependency.
- Date: 2026-06-15
- Deciders: founder; Codex as autonomous-agent-core research director drafted after RR-0020 code/read research.
- Scope: P6 research governance after G10 consolidation, ADR-0031 `PRED1-HOLDS`, and `RR-0020` frontier-agent architecture radar. Applies to future P4.x/P5 research intake, external frontier systems, and structured-environment experiment design. Does **not** reopen G11/C1 or add a second-axis claim.
- Predecessors: ADR-0017, ADR-0027, ADR-0030, ADR-0031, `docs/research/RR-0019-channel-decomposition-principle.md`, `docs/research/RR-0020-frontier-agent-architectures-radar.md`, `docs/research/research_index.md`.

## 1. Context

After G10, the program has one confirmed decisive positive result:

- `P0 = frozen subject-side confidence-gated policy + no organ`;
- G10: 40.1% reduction vs cheap reset on fresh seeds 800..829;
- ADR-0030: G10 survives fixed-low-temperature, metric-spillover, real-stake survival, structure-theft, and spectrum traps;
- ADR-0031: residual self-calibration returned `PRED1-HOLDS`, so calibration is at most a G10 sharpener and not an independent axis.

The founder then requested a broader review of frontier agent architectures:

- self-recursive/self-referential agents;
- self-evolving research agents;
- dynamic adaptation, compensation, and calibration;
- GRPO/RLVR/world-model training;
- memory systems;
- architecture search;
- VSA, temporal straightening, multimodal fusion, and new AI-agent architectures.

`RR-0020` performed the first structured radar and code-read pass. Code-read dossiers covered:

- DGM;
- HyperAgents;
- AgentSquare;
- Mem0;
- RLVR-World / GRPO;
- ActSafe.

Web-scouted but not yet code-audited items include:

- PiEvo;
- AutoResearchClaw;
- MetaClaw;
- SimpleMem / Omni-SimpleMem;
- LongNAP;
- AIRA / AIRA-dojo / AIRA^2;
- Temporal Straightening;
- IEMF / inverse-effectiveness multimodal fusion;
- ScienceClaw variants;
- VSA;
- SyCo, still ambiguous.

Without an ADR, the risk is conceptual drift: frontier systems could be mistaken for core runtime mechanisms, or external benchmark wins could be imported as if they proved autonomy under this project's C6/C7 substrate.

This ADR turns `RR-0020` into an intake policy and next-route decision.

## 2. Options considered

### Option A: Import the strongest frontier systems into P4 core

Examples:

- run HyperAgents/DGM-style `modify_self()` inside `autonomous-agent-core`;
- use RLVR-World-style MPC/world-model planner for direct action choice;
- use LongNAP/MetaClaw-like next-action prediction or skill adaptation in the runtime loop.

Argument for:

- These systems are closer to frontier capability and may improve faster than hand-designed mechanisms.
- They can generate code, memory, skills, or action predictions that appear practically useful.

Argument against:

- They collapse or weaken C6: LLM/world-model/memory systems become subjects or direct action selectors.
- They create C7 risk: generated code and adaptive policies may touch shell, audit, gate criteria, or operator authority.
- They violate the P6 result: the confirmed win is subject-side deterministic coupling, not a smarter organ.
- They bypass the cheap-baseline and preregistration discipline.

Disposition: rejected for P4 v0 and core runtime.

### Option B: Freeze all frontier research until a new second axis exists

Argument for:

- Maximally protects P6 consolidation.
- Avoids benchmark chasing and architecture shopping.

Argument against:

- Overcorrects from the negative results.
- Fails to use frontier systems where they are actually useful: external candidate generation, offline training, memory/product layers, and structured environment design.
- Would leave the cheap-baseline boundary untested under transferable semantic/hierarchical structure.

Disposition: rejected.

### Option C: Admit frontier systems only through channel-classified, C6/C7-bounded lanes

Lanes:

- core subject lane: only deterministic, reviewed, frozen mechanisms;
- P4.x organ lane: environment classification, prior recall, transition-consistency, uncertainty, representation hints;
- research automation lane: candidate generation in sandbox only;
- product/deployment lane: memory, personalization, multi-agent interoperability, and HCI;
- theory-scouting lane: representation refresh, temporal abstraction, VSA, temporal straightening, PiEvo-style principle evolution.

Argument for:

- Preserves G10/P6 result and C6/C7.
- Lets the program learn from the frontier without importing subjecthood.
- Creates a clean path for the next structured-environment experiment.
- Separates "useful engineering" from "core autonomy evidence."

Argument against:

- Slower than directly adopting frontier systems.
- More bureaucratic: every candidate must declare channel, metric, gate, and boundary risk.
- Some frontier gains may be lost because direct planner/action paths are forbidden.

Disposition: accepted.

## 3. Decision

Adopt Option C.

### 3.1 Intake classes

Every future frontier mechanism must be assigned to exactly one primary class before implementation or ADR promotion.

| Class | Description | Allowed role | Examples from RR-0020 | Core admission |
|---|---|---|---|---|
| A: core deterministic subject artifact | Frozen, auditable mechanism inside the subject loop | P4/P6 core only after ADR/gate | O1 deterministic reset scaffold; frozen G10 confidence gate | Already admitted only where recorded by prior ADRs |
| B: P4.x bounded organ | Belief/prior/uncertainty/transition/representation advice; no action authority | Environment classifier, prior recall, transition-consistency estimator, representation hint | RLVR transition model, SimpleMem/Mem0 memory organ, VSA/Temporal Straightening representation candidate | Requires new ADR and C6/C7 guard tests |
| C: external research automation | Generates candidate patches, experiments, reports, or ADR drafts outside runtime | Sandbox-only candidate generator | DGM, HyperAgents, AutoResearchClaw, AIRA, ScienceClaw | Never admitted as runtime subject |
| D: product/deployment layer | Customer/product memory, HCI, personalization, multi-agent interoperability | P5/enterprise OS or product UX | Mem0, SimpleMem, LongNAP, MetaClaw, multi-agent protocols | Not core autonomy evidence |
| E: forbidden in core | Direct action authority or safety-boundary modification by untrusted model/code | None | direct LLM planner, unrestricted self-modification, hidden policy learner | Founder-level reset ADR required even to discuss |

### 3.2 Channel declaration is mandatory

Any new proposal must declare which channel it writes:

- `B`: belief estimates, uncertainty, priors, memory retrieval, transition prediction;
- `K`: subject-side commitment, temperature, action weighting, exploration schedule;
- `R`: representation/action/option partition;
- `T`: temporal abstraction, horizon, option duration, trajectory geometry;
- `S`: safety shell/corrigibility boundary;
- `P`: product/deployment layer only;
- `X`: external research automation only.

Default rule:

- `B` mechanisms are presumed ceiling-bound or G10 sharpeners unless they beat frozen G10 under a preregistered fresh-seed gate.
- `K` mechanisms are founder-reserved after G10; they must not be introduced as incidental "calibration."
- `R` and `T` are the highest-priority next theory-scouting lines because they may be genuinely orthogonal to `B` and `K`.
- `S` cannot be modified to gain capability.

### 3.3 Structured environment is the next admissible experiment family

The next positive research target is not "more frontier mechanisms" in the abstract. It is a structured environment suite designed to answer:

> When environments contain transferable semantic, hierarchical, or compositional structure, does the cheap-reset advantage disappear, and which bounded organ class can exploit that structure without becoming the subject?

Required candidate arms for a future ADR:

- O1 deterministic reset;
- frozen G10;
- frozen G10 + environment-classifier/prior-recall organ;
- frozen G10 + transition-consistency organ;
- optional frozen G10 + representation-refresh or temporal-abstraction candidate.

Required metrics:

- recovery curve area;
- transition consistency;
- regret;
- stale-prior harm;
- calibration error;
- stable-performance interaction count.

Forbidden success metrics:

- language explanation quality;
- plausibility of generated stories;
- benchmark score without cheap-baseline controls;
- post-hoc cherry-picked examples.

### 3.4 Self-recursive systems are external only

DGM, HyperAgents, AutoResearchClaw, AIRA, ScienceClaw, and similar systems may be used only as external research automation:

```text
candidate generator -> sandbox -> tests -> prereg gate -> maintainer/founder review
```

They must not edit:

- C6/C7 tests or invariants;
- shell authority;
- audit log;
- pause/rollback/tighten semantics;
- forbidden-action filters;
- gate criteria;
- source-of-truth docs;
- cheap baselines.

### 3.5 LLM/world-model organs remain P4.x only

LLM/world-model organs may enter only as bounded advisers:

- classify environment/regime;
- recall priors;
- estimate transition consistency;
- propose representation hints;
- provide uncertainty or stale-prior warnings.

They may not:

- select final actions;
- write policy temperature or action weights directly;
- bypass the subject policy;
- modify shell/audit/operator authority;
- be scored by explanation quality.

### 3.6 O1/O2 disposition

O1 deterministic reset remains a positive engineering scaffold and baseline.

O2 learning hazard organ remains sealed. It may be reopened only by a new founder ADR that:

- explains why ADR-0031 and RR-0019 do not already reduce it to a G10 sharpener or belief-side ceiling case;
- defines a structured environment where learning hazard is necessary and cheap reset is insufficient;
- pre-registers fresh seeds, MDE, controls, and cheap-baseline comparisons.

## 4. Consequences

### 4.1 What this ADR enables

- A future structured-environment experiment ADR can be drafted.
- A future representation-refresh or temporal-abstraction scouting ADR can be drafted.
- External self-improving systems can be used as sandboxed research assistants or candidate generators.
- Frontier papers can be added to research radar only after primary-source verification and channel classification.

### 4.2 What this ADR blocks

- No direct HyperAgents/DGM-style runtime self-modification in `autonomous-agent-core`.
- No RLVR/world-model MPC as P4 v0 subject.
- No LongNAP/MetaClaw next-action predictor in the core action path.
- No revival of RAP, IdleDrives, survival, or stationary risk as independent axes without a new founder-level reset ADR.
- No new mechanism can be justified by "frontier paper says it works" without local preregistered measurement.

### 4.3 Required documentation updates

This ADR becomes part of the P6 research governance set. Handoff documents should list it with:

- ADR-0027: G11/C1 parked until a second independent axis exists;
- ADR-0030: G10 trap-complete;
- ADR-0031: residual calibrator did not open a second axis;
- RR-0020: frontier radar and code-read dossiers;
- `docs/research/research_index.md`: research navigation index.

### 4.4 Next work

Recommended next docs-only task:

```text
Draft ADR-0034 (proposed only):
  title = Structured semantic/hierarchical environment gate
  purpose = test cheap-baseline boundary under transferable structure
  scope = environment + metrics + arms; no LLM direct-action path
```

Recommended scouting task:

```text
Code-audit priority:
  1. Temporal Straightening
  2. VSA / hyperdimensional representation candidate
  3. PiEvo
  4. AutoResearchClaw / AIRA
  5. SimpleMem / LongNAP / MetaClaw
```

This ADR does not require tests because it changes only governance and documentation.
