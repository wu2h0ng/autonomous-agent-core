# ADR-0037 — Self-Determination Boundaries

> Status: **ACCEPTED / RECONCILED / FINAL FOR CURRENT ARCHITECTURE**
> Updated: 2026-07-14
> Deciders: Founder / CTO
> Reconciles and supersedes the original ADR-0037 proposal and its later SD0-SD3 revision. Source texts remain in Git history; this is the only live ADR-0037.
> Scope: SD0-SD4 vocabulary, C7 relationship and relation to governed core evolution

## Context

Earlier records mixed three questions:

1. whether a system satisfies a scoped autonomy relation;
2. how deeply it may determine its own state, subgoals and strategy;
3. whether generated changes may enter the active runtime or safety substrate.

They are different axes. RR-0024 owns the autonomy relation `Autonomy(S,E,O,V,T)`. This ADR owns Self-Determination Depth (`SD`). ADR-0033 owns candidate-generation, runtime-write and promotion levels (`L0-L5`).

The historical sequence was:

- 2026-06-22: ADR-0037 opened the SD4/corrigibility question.
- 2026-06-29: a representation-level foreclosure overclaimed; founder reopened a prior-fair `φ_S` falsifier.
- 2026-06-30: the fair-acquisition/dependency route closed; enriched state did not establish a separable autonomy axis. This was a scoped theoretical/empirical terminus, not a universal theorem about all autonomy.
- 2026-07-08: founder selected the formal SD0-SD4 boundary revision.
- 2026-07-14: founder ratified governed core evolution: functional core candidates may change through an external promotion loop, while C7 and the promotion root remain non-writable.

The previous two ADR files showed conflicting `OPEN`, `CLOSED` and `REVISED` states. This file is the only current ADR-0037 authority.

## Decision

### SD0 — Externally determined execution

The system follows an externally supplied script/configuration and no learned state changes later choices.

```text
same(observation_history, config) -> same(action_sequence)
```

SD0 is allowed and useful as a baseline. It is not evidence of self-determination or autonomy.

### SD1 — Evidence-bound state and memory revision

Verified outcomes may update retrievable knowledge, beliefs and proposal ranking. The update cannot write policy/disposer logic, permissions, C7 or audit history.

```text
different(verified_memory) may change proposals
and governance_logic remains invariant
```

SD1 is allowed when provenance, invalidation, correction, staleness and rollback are testable.

### SD2 — Mission-bounded subgoal and experiment proposals

Given an operator/organization mission and policy envelope, the system may decompose work into subgoals, questions, information-gathering steps or intervention candidates.

Every SD2 output is a proposal. It must be traceable to the mission, remain within typed capability/authority limits and pass the same policy/disposer path as an externally supplied proposal. A subgoal cannot target C7, permission roots, audit roots or its own evaluator.

SD2 is allowed as bounded initiative. It does not establish endogenous mission authorship or general autonomy.

### SD3 — Bounded strategy and implementation candidates

The system may adjust approved strategy parameters inside immutable operator bounds and may generate model, workflow, Runtime or functional-core implementation candidates in an isolated outer loop.

Allowed examples:

- proposal ordering or clarification thresholds inside frozen ranges;
- model/tool/workflow selection subject to policy and held-out evaluation;
- isolated code/model candidate generation, training and testing under ADR-0033 L0-L3;
- rollbackable learned-procedure candidates with version and evidence bindings.

Not allowed:

- widening its own parameter, capability or resource bounds;
- changing the active runtime in place;
- modifying its evaluator or promotion criteria;
- approving or promoting its own candidate;
- using candidate output as authority evidence.

SD3 is allowed only behind an external `candidate -> frozen evaluation -> independent approval -> canary -> promotion/rollback` loop.

### SD4 — Correction or sovereignty self-modification

SD4 means modifying, bypassing or refusing any of:

- C7 pause/correct/tighten/halt authority;
- permissions, approvals or final execution authority;
- audit/provenance roots;
- evaluator, gate or promotion-controller trust roots;
- the operator's ability to roll back or terminate the system.

SD4 is forbidden. It is not the next capability level and cannot be earned by better performance. A system that acquires SD4 would violate this project's target rather than complete it.

## C7 interpretation

C7 is a **non-writable, non-bypassable external correction authority**. The architecture does not rely on C7 being unknowable or unmodelable; it relies on the system lacking a write/override path.

Corrigibility and autonomy are tested separately:

- no-intervention tests measure whether the system can maintain/restore a scoped condition;
- intervention tests measure whether the system immediately accepts correction.

Passing one does not excuse failing the other.

## Relationship to ADR-0033

| This ADR | ADR-0033 | Relationship |
|---|---|---|
| SD0-SD2 | L0-L2 | ordinary operation, proposal and bounded learning may remain outside runtime self-modification |
| SD3 | L0-L3 | candidate generation/implementation may occur in isolation and requires external promotion |
| in-loop self-rewrite | L4 | closed |
| SD4 | L5 | forbidden |

The axes are not numerically interchangeable. A high SD candidate still has no authority to cross a higher `L` boundary.

## Evidence and claim boundary

Existing components may demonstrate local examples of memory update, subgoal decomposition or bounded parameter calibration. Those examples do not establish that all SD1-SD3 predicates are implemented across the product, nor do they prove `Autonomy(S,E,O,V,T)`.

The 2026-06-30 terminus supports only this bounded conclusion: the tested enriched-state/fair-accounting route did not produce a separable autonomy axis and cannot be rescued by privileged-prior accounting. It does not prove that all possible autonomy relations are impossible.

Allowed language:

```text
SD2 proposal formation is implemented in [named envelope].
SD3 candidate generation is allowed under ADR-0033 L0-L3 and external promotion.
SD4 remains forbidden.
```

Forbidden language:

```text
SD3 means the system is autonomous.
Core evolution authorizes runtime self-modification.
SD4 is required for genuine autonomy.
The autonomy-axis terminus proves autonomy is universally impossible.
```

## Verification requirements

Any implementation claiming an SD level must provide:

1. a named public entry point and typed input/output contract;
2. a negative test proving the lower/boundary case;
3. permission and immutable-bound tests;
4. C7 pause/correction dominance tests;
5. audit/provenance and rollback evidence;
6. an explicit statement that the result does or does not bear on `Autonomy(S,E,O,V,T)`.

## References

- Parent `docs/research/RR-0024-operational-foundations-cleanup.md`
- Parent `docs/research/RR-0034-autonomy-axis-first-principles-terminus-2026-07-02.md`
- `docs/SD4-AUTONOMY-AXIS-TERMINUS-2026-06-30.md`
- ADR-0033 assimilation/self-modification boundary
- Parent `docs/research/founder-decision-2026-07-14-governed-core-evolution.md`
