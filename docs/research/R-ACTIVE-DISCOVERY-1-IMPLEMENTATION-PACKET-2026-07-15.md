# R-ACTIVE-DISCOVERY-1 — Core Harness Implementation Packet

> Status: `IMPLEMENTATION_AUTHORIZED / HARNESS_ONLY / NOT_FROZEN / NOT_RUN`
>
> Date: 2026-07-15
>
> Track: Research infrastructure and controlled mechanism falsifier
>
> Scope: closed contracts, deterministic probe accounting, append-only hypotheses,
> information-value selection, inert evaluator IR, sealed referee protocol, and one
> hermetic opaque-CLI family

## 1. Bounded question

Can a fixed strategy model, given only an incomplete public descriptor and a
bounded reversible probe interface, maintain competing hypotheses, choose probes
for expected information value, and produce grounded behavior/evaluator
candidates that predict unqueried black-box behavior better than strong cheap
baselines?

This implementation does not call a model and does not answer that question. It
only builds the smallest harness needed for a later preregistered comparison.

## 2. Claim ceiling and nulls

A later frozen run may test only the following bounded claim:

> In named hermetic software black boxes, typed hypothesis state plus a
> deterministic value-of-information selector improves held-out behavior-contract
> accuracy, calibration, and query efficiency over the strongest applicable
> matched-budget baseline.

Live nulls remain:

- `H0_ACTIVE`: active selection does not beat systematic or random probing.
- `H0_REGISTRY`: typed append-only hypotheses do not beat a strong free-form
  engineering workflow.
- `H0_EVALUATOR`: generated tests only replay queried cases and do not predict
  hidden behavior.
- `H0_TRANSFER`: any advantage disappears on a held-out software family.
- `H0_SHIFT`: stale behavior rules are not detected or invalidated after an
  interface-preserving semantic switch.

No implementation or development qualification may be called scientific
discovery, autonomy, domain adaptation, learning, an Agent OS capability, or a
Product Track result.

## 3. Required future arms

The harness contracts preserve space for these separately frozen arms:

1. `ACTIVE_VOI`: typed registry plus deterministic information-value selector;
2. `FREEFORM`: same model/probe budget with a strong frozen generic engineering
   workflow and no typed registry;
3. `SYSTEMATIC`: schema-derived boundary, pairwise, repetition, and ordering
   probes;
4. `RANDOM`: uniform selection from the same public legal probe catalogue;
5. `PASSIVE`: incomplete descriptor only, reported as a cheaper Pareto baseline;
6. `TRACE_MEMO`: exact queried input/output lookup with abstention elsewhere;
7. `GENERIC_TESTS`: evaluator IR generated from the public schema only.

This change implements no arm runner and performs no arm comparison.

## 4. Authority and write boundary

- The actor may submit only typed registry revisions, probe requests, and an inert
  final bundle digest.
- A model output never directly invokes Python, shell, browser, network, source
  inspection, or arbitrary code.
- Every probe is checked against an external halt seam and a hard budget before
  the adapter is called.
- Hidden score access is unavailable until the transcript and final bundle are
  sealed.
- The evaluator candidate is a closed data-only `TestIR`; it is not an authority.
- Product Runtime, `src/aac`, C6/C7 implementation, policy, audit, promotion, and
  `DomainCandidate` stores are out of scope.
- The protocol-level halt seam preserves fail-closed correction structure but is
  not evidence that Product C7 is integrated or validated.

## 5. Leakage and oracle boundary

Actor-visible data are limited to:

- an opaque operation and field descriptor;
- normalized probe status/stdout/stderr/output;
- opaque before/after state digests;
- budget receipts and append-only registry receipts.

Actor-visible data must not contain source paths, implementation class names,
family/config/version labels, hidden rule names, hidden tests, oracle partitions,
verdict thresholds, other-arm artifacts, or hidden scores.

The F1 family is a deterministic hermetic development fixture. Its source may be
reviewed by implementers, but a future model actor receives no filesystem tool and
only the public protocol projection. Future scored configurations require an
independently committed hidden manifest and one-shot reveal; this implementation
does not create such a manifest.

## 6. Integrity and kill gates

Any later run is invalid if one of these occurs:

- unknown contract fields are accepted;
- a probe executes after halt or without budget;
- budget, retry, output, or state accounting differs across matched arms;
- hidden score or configuration becomes visible before final seal;
- actor-provided code, dynamic expected values, or tautological assertions enter
  `TestIR`;
- the hypothesis history is rewritten, `OTHER` reaches zero, contradictory
  evidence is silently discarded, or stale rules are overwritten in place;
- selector choice depends on opaque labels rather than probability partitions,
  cost, and stable public order;
- snapshot replay differs for identical state and probe bytes;
- development qualification is presented as evidence.

Mechanical scientific dispositions remain for a later preregistration:
`PARK_ACTIVE_ADAPTATION`, `NULL_EVALUATOR_VALUE`, `NO_TRANSFER_EVIDENCE`,
`NULL_NONSTATIONARY`, `INVALID_LEAKAGE`, `INVALID_BUDGET`, and `UNDERPOWERED`.
This harness does not compute any of them.

## 7. F1 development family

F1 is an opaque CLI-precedence state machine. The public descriptor exposes one
opaque operation, three opaque input fields with closed JSON shapes, an opaque
setting token, and normalized result fields. Hidden semantics choose:

- source precedence;
- repeated-option first/last/error behavior;
- unknown-option ignore/error behavior;
- empty-as-missing behavior;
- atomic or partial state update on parse failure;
- deterministic success/error status and output routing.

The actor never receives those semantic labels. The family is local, reversible,
seeded, snapshot-capable, deterministic, and has no external side effects.

## 8. Development-only CLI

Only these commands are allowed:

```text
python -m research_tools.active_discovery.cli validate-spec --spec <json>
python -m research_tools.active_discovery.cli qualify-dev --spec <json>
```

Both require `mode = NOT_EVIDENCE`. `qualify-dev` may execute deterministic
developer-supplied F1 probes and emit contract/replay receipts, but it must never
emit a research verdict, calibration statistic, baseline comparison, model result,
or promotion signal.

## 9. Explicit non-authorization

This packet authorizes no provider/model call, calibration, power estimate,
preregistration freeze, hidden-set generation, result-bearing run, r-final,
Product integration, `CURRENT_STATE` update, push, merge, or release.
