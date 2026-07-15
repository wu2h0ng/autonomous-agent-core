# ADR-0057: Adaptive Domain Materialization and Optional Domain Prior Boundary

- Status: **Accepted / ADM-P1 IMPLEMENTED_LOCAL_CANDIDATE_SEALING_ONLY / NO ACTIVATION OR PROMOTION AUTHORIZATION**
- Date: 2026-07-15
- Deciders: Founder; delegated CTO
- Track: Product architecture with a separately adjudicated Translational/Research falsifier
- Reviewed design: parent repository commit `60af953`, file SHA-256 `f63648c8766ec42a15e25951a6cb9cfca930efc05d3d2f6631317145c96f362a`
- Architecture-theory review: `RR-0029 §5 ACCEPT_FOR_SPEC`, exact digest above, independent read-only reviewer `/root/adaptive_adr_skeptic`
- Technical review: Kimi Code `TECHNICAL_APPROVE`, exact digest above
- Partially supersedes: ADR-0055 only where `DomainPack` is treated as the default canonical new-domain extension model
- Preserves: ADR-0033, ADR-0037, ADR-0054, C6/C7, SD4, all historical verdicts and migration/release gates

## Context

The Product Blueprint currently makes a manually engineered `DomainPack` the normal path for adding domain semantics. That is useful for packaging a standing vertical such as Data Agent, but it creates linear human engineering cost if every unfamiliar environment first requires a hand-authored ontology, workflow, evaluator and connector bundle.

The opposite design—letting a model invent semantics, evaluators, permissions or executable behavior and immediately use them—is also rejected. It would turn candidate generation into hidden policy and let correlated errors cross the Product authority boundary.

The product needs a bounded default attempt for new-domain `Work` that can form grounded candidates, abstain when it cannot, and reuse independently validated learning without making domain packaging the source of intelligence.

## Decision

### 1. Bounded default attempt

For new-domain `Work` lacking an accepted prior, Agent OS may attempt **Adaptive Domain Materialization** inside the accepted task, source, permission and budget envelope.

The attempt is read-only by default and may terminate as `ASK`, `UNKNOWN` or `NOT_SUPPORTED`. It is not required for ephemeral `Ask`, and it must not impose persistent materialization cost on every interaction.

### 2. Candidate-only output

Materialization may emit sealed candidate data only in these channels:

- `B`: beliefs, uncertainty and provenance;
- `R`: task-local representations and grounded mappings;
- `T`: non-active WorkflowGraph patches;
- `P`: narrowing-only Product configuration or procedure candidates.

It may not write `K` or `S`, active capability grants, credentials, policy, permission, audit, evaluator, approval, promotion or C7 roots. A generated workflow, configuration or implementation remains inert candidate data.

### 3. Existing Product authority remains sovereign

A candidate cannot activate in the run that generated it. Any later use requires:

```text
sealed candidate
  -> externally written evaluation receipt
  -> Product-owned promotion decision
  -> verified patch application
  -> immutable configuration snapshot
  -> new Task/Run through the existing authority spine
```

Identity, policy, approval, audit, correction and C7 remain existing Product authority seams. New receipts or ledgers record candidate/evaluation/promotion facts; they do not form a second final authority, task runtime or execution spine.

### 4. Optional Domain Prior

A manually engineered `DomainPack` is no longer the mandatory or default source of new-domain capability. A validated `DomainPriorArtifact` is an optional, versioned, provenance-bound accelerator, cache or publication artifact.

A prior may narrow configuration, reduce discovery cost and package validated semantics or procedures. It grants no authority, cannot suppress uncertainty and cannot self-promote. `DomainPack` and `DomainPackManifest` may remain compatibility/publication containers until a later migration and compatibility decision.

### 5. Data Agent and SPINE-1 remain intact

Data Agent remains:

- the standing enterprise implementation and SPINE-1 donor;
- the first enterprise adaptation reference environment;
- a strong manually engineered baseline for automatic materialization;
- the owner of Metric, SemanticObject, DataProduct, SQL, query-result and business-action semantics.

ADR-0054's physical target `domain_packs/data_agent`, G0-G7, history-safety, provenance, review, push and merge gates are unchanged. The path remains an internal code-ownership and compatibility boundary; it is not a requirement that every future domain become a hand-authored user-visible pack.

### 6. Research predecessor boundary

The Research Track `OntologyEngine` may only feed provenance-bound observations through a one-way adapter into a Product-owned candidate builder. It may not be copied into Product Runtime, implement Product contracts, write Product stores, grant capabilities or transfer a Research claim.

## Consequences

### Positive

- New-domain capability is tested as grounded acquisition and transfer, not plugin count.
- Data Agent remains valuable without defining the terminal product model.
- Candidate generation can become more capable while authority, evaluation and correction stay external.
- Optional priors preserve cold-start and controlled-deployment advantages without becoming mandatory intelligence modules.

### Costs and risks

- Product contracts are needed for sealing, provenance, evaluation receipts, immutable snapshots and later-run activation.
- Poorly scoped P/T candidates could become hidden policy unless closed schemas and existing authority seams are mechanically enforced.
- Unknown-domain evaluation remains a Research problem; independent promotion does not manufacture ground truth.
- Automatic materialization must beat strong direct-model, retrieval and thin-prior baselines before it earns a capability claim.

## Rejected alternatives

1. **One manually engineered full pack per domain** — rejected as linear engineering and the wrong terminal product model.
2. **Free-form same-run adaptation** — rejected because it collapses proposal, evaluation and authority.
3. **Delete DomainPack and rename `domain_packs/data_agent` now** — rejected because it would break compatibility and pre-empt ADR-0054/SPINE-1.
4. **Copy the Research OntologyEngine into Product Runtime** — rejected because it inherits neither Product provenance nor authority semantics.
5. **A second adaptation runtime or promotion authority** — rejected as architecture failure.

## Implementation and evidence boundary

This ADR supplied the Product boundary; it did not by itself authorize implementation. The separately admitted ADM-P1 slice now implements only typed contracts, isolated persistence and a real local seal/list Product entry point. Its exact evidence and claim ceiling are recorded in `../product/PM-ADM-P1-CANDIDATE-SEALING-2026-07-15.md`.

ADM-P1 does not implement or authorize discovery/acquisition, candidate evaluation, promotion, activation, optional priors, immutable Task configuration snapshots, experiments, training, migration, package deletion/rename, push, merge or release.

The parent portfolio decision `AI-Agent-Projects/docs/research/founder-decision-2026-07-15-accelerated-multi-lane-execution.md` separately admitted the first Product implementation lane. ADM-P1 followed its reviewed contract and test plan; later research claims still require their own frozen preregistration.
