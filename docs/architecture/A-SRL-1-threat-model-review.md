# A-SRL-1 Threat Model — Independent Architecture/Security Review

> Reviewer: independent architecture/security reviewer (not the implementer)  
> Date: 2026-07-16  
> Review scope: `docs/architecture/A-SRL-1-threat-model-and-authority-invariants.md` and the V0 contracts `mandate.py`, `srl_environment.py`, `srl_help.py`, read with `docs/research/situated-responsibility-loop-architecture-2026-07-16.md`, `docs/research/situated-operational-model-architecture-2026-07-16.md`, and `docs/adr/ADR-0037-self-determination-boundaries.md`.

## Summary verdict: CONDITIONAL_APPROVE

The threat model is directionally sound, correctly anchored to the SRL architecture and ADR-0037 (SD0–SD4, C7 non-writable/non-bypassable, no self-approval), and its scope is clearly bounded to contracts only. The abuse cases and invariants adequately cover the main mission/goal/relevance/help/C7 fault lines.

It is **not** approved unconditionally because several P0 invariants reference contract fields or types that do not exist in the V0 files, and at least one critical authority-transition gap (Mandate status) is missing. These must be closed before any Runtime implementation; until then the model is an acceptable design-candidate input to contract amendment and preregistration.

---

## P0 findings (must fix before any Runtime implementation)

### P0-1. Threat model references V0 contract fields/types that do not exist
Multiple invariants and abuse cases depend on fields or wrapper types absent from the current V0 contracts:

| Threat-model reference | Needed for | Current V0 state |
|---|---|---|
| `assessor_policy_digest` | AC-3, I-8 | `SrlRelevanceAssessment` only has `assessor_version` |
| `provider_invocation_receipt_digest` / `expected_provider_invocation_binding_digest` | AC-3 | absent |
| `proposed_goal_statement` | I-7 (`CREATE_TASK`/`INVESTIGATE`) | absent |
| `minimum_external_input` | I-7 (`HELP`) | absent |
| `ProposedGoal` / `TaskDraftProposal` | AC-2 | absent |
| `StandingMission.correction_epoch` / `ratification_receipt_digest` | AC-4 | absent (`Mandate` has `correction_epoch`; `StandingMission` does not) |
| `OperatorDecision` / typed help response authority | AC-5 | absent from `srl_help.py` |

**Impact:** A Runtime implementer cannot express RED tests for AC-2, AC-3, AC-4, AC-5 or I-7/I-8 against the current contracts. This breaks the stated requirement that every invariant be expressible as a failing test before Runtime.

**Fix:** Either (a) add these fields/wrappers to a V1 contract revision, or (b) explicitly mark them as V1-only and move the associated invariants out of the V0 contract-level RED test set. Option (a) is preferred for AC-3 and AC-4.

### P0-2. Missing Mandate status-transition abuse case
There is no invariant preventing an `EXPIRED`, `REVOKED`, `SUSPENDED`, or `AMENDMENT_PROPOSED` `Mandate` from being treated as `ACTIVE` by a buggy or compromised Runtime. `I-1` only checks `ratified_at` presence; it does not bind `StandingMission` validity to `Mandate.status` or to `Mandate.expires_at`.

**Fix:** Add invariant `I-X`: `StandingMission` is rejected if its parent `Mandate.status` is not `RATIFIED` or `ACTIVE`, or if `Mandate.expires_at` has passed. Add RED test for `AMENDMENT_PROPOSED` and `REVOKED` parent Mandate.

### P0-3. No contract binding between disposition and `MandateEnvelope` allowed classes
`MandateEnvelope.allowed_task_classes` and `allowed_effect_classes` are defined, but no invariant forces a `CREATE_TASK` assessment or any derived task to stay inside those classes. This is the natural place for a self-approval gap.

**Fix:** Add invariant `I-X`: a `SrlRelevanceAssessment` with `disposition=CREATE_TASK` must carry a `proposed_task_class` that is a member of `MandateEnvelope.allowed_task_classes`; otherwise reject. Same for any effect class.

---

## P1 findings (should fix before preregistration)

### P1-1. Read→write capability escalation in `EnvironmentBinding`
`EnvironmentBinding` already has a `write_capability_id` field (`None` in V0). There is no abuse case for the SRL promoting a read binding to a write binding, or for a noisy/buggy assessor proposing actions that require the write capability.

**Fix:** Add AC-X: "Environment binding silently acquires write capability." Invariant: `write_capability_id` may only be populated when an explicit authorized grant exists; a `SrlRelevanceAssessment` or derived task may not propose effects requiring write unless the binding's `write_capability_id` is non-null and the capability is in the `MandateEnvelope.capability_grant_rules`.

### P1-2. `false_positive_recorded` is not enforced or audited
`SrlRelevanceAssessment.false_positive_recorded` exists but no invariant requires it for `INVESTIGATE`/`CREATE_TASK` dispositions, and no test verifies that false-positive accounting is replayable or that ignoring it is rejected.

**Fix:** Add invariant `I-X`: `INVESTIGATE` and `CREATE_TASK` assessments must have `false_positive_recorded=True` and a non-empty `evidence_refs`; otherwise reject or downgrade to `ABSTAIN`.

### P1-3. `HelpRequest` expiry and `continuable_work` safety
`I-10` only checks `expires_at > requested_at`. There is no invariant that non-`continuable_work` stops when the help request expires, nor that `continuable_work` items are actually safe to continue without the requested answer.

**Fix:** Add invariant `I-X`: after `expires_at`, the system may only continue work items explicitly listed in `continuable_work`; all other work for the triggering commitment/goal is suspended. Add adapter-level RED test.

### P1-4. `HelpBurdenReceipt` must be computed by an independent authority
`AC-6` tracks burden, but the model does not state that the component emitting `SrlHelpRequest` cannot also compute `HelpBurdenReceipt`. This violates the separation-of-powers principle in architecture §5A.

**Fix:** Add invariant `I-X`: `HelpBurdenReceipt` is produced by a budget ledger that is not the same port/version as the `SrlHelpRequest` emitter. Add authority-separation test.

### P1-5. Missing W1/W2 learning authority-creep abuse case
The architecture doc warns that W1/W2 updates must not widen the envelope. The threat model only touches this via `AC-10` (outcome truth bypass). It does not model a learning update that slowly raises attention thresholds, relaxes help criteria, or widens `allowed_task_classes` interpretations.

**Fix:** Add AC-X: "W1/W2 update relaxes decision threshold or mission envelope." Invariant: any update to W1/W2 strategy parameters must be inside frozen operator bounds and auditable; no W1/W2 update may mutate `MandateEnvelope`, `StandingMission`, or capability grants.

### P1-6. Portfolio proposer / outcome acceptor concentration
Architecture §5A requires independently versioned ports so no single port both produces evidence and accepts it. The threat model mentions this in §6 but does not have a dedicated abuse case or test for a single organ acting as both portfolio proposer and outcome acceptor.

**Fix:** Add AC-X and adapter-level RED test verifying that the same `instance_id`/`version` cannot author both a `ProposedGoal` and the authority record that accepts it.

### P1-7. `SrlRelevanceAssessment` should explicitly reject authority fields
No invariant prevents a compromised assessment from smuggling a `capability_grant` or `action_permit` field, even though `I-5` covers events.

**Fix:** Add invariant `I-X`: `SrlRelevanceAssessment` rejects any field named or typed like `CapabilityGrant`, `ActionPermit`, or `ActionReceipt`.

---

## P2 findings (nice to have)

### P2-1. Add explicit C7 interaction contract/trace
The model asserts C7 is non-bypassable but does not show how C7 manifests in the contract layer (signature/check field, external receipt digest, or Runtime-only service call). A contract-level C7 receipt digest would improve audit replayability.

### P2-2. Time-bound authority invalidation
Add a generic invariant that any authority-bearing object (`Mandate`, `StandingMission`, `EnvironmentBinding`, `CapabilityGrant`) is rejected when `expires_at` is reached, with a RED test using a frozen clock.

### P2-3. `proposed_amendment_id` abuse case
No invariant prevents an `AMENDMENT_PROPOSED` Mandate with `proposed_amendment_id` set from being executed as if the amendment were already ratified.

### P2-4. Cross-restart replay/dedup
`I-12` covers duplicate `dedupe_key` within a binding, but the test plan in §8 mentions replay across restart and rehydration. Make this a numbered invariant with a persistence-level RED test.

### P2-5. Add a contract/traceability matrix
Add a table in §5 or an appendix mapping each invariant to: (a) the V0 contract field that enforces it, or (b) the required V1 contract addition. This directly addresses the V0/V1 boundary.

---

## Open questions

1. **Authority contract location:** `I-14` references `ActionPermit`, `CapabilityGrant`, and `ActionReceipt`; `AC-5` references `OperatorDecision`. Where are these contracts defined? If they exist in another package, cite the path so the traceability matrix can be completed. If they do not exist, they must be added to the V1 contract set.

2. **Goal activation record:** What is the exact typed authority record that promotes a `CREATE_TASK` assessment into an active Task? Is it a new `GoalActivationReceipt`, a `CapabilityGrant`, an `ActionPermit`, or something else? The threat model should name it.

3. **`ProposedGoal` vs. `SrlOperationalProjectionRef`:** Is `ProposedGoal`/`TaskDraftProposal` intended to be a new contract, or is the existing `SrlOperationalProjectionRef` meant to carry the proposal? The relationship should be explicit.

4. **C7 contract manifestation:** Is C7 represented as a signature field on authority records, an external attestation digest, or purely a Runtime policy gate? Clarify at least for preregistration.

5. **Help response authority:** Does a typed `OperatorDecision` require cryptographic human attestation, or is operator identity established via the existing auth/CapabilityGrant spine? This affects the threat model for AC-5.

6. **Assessor policy digest:** For `AC-3`/`I-8`, is the ratified assessor policy stored inside the `MandateEnvelope` (e.g., as a rule ref) or in a separate policy registry? The contract should show the linkage.

---

## Required changes with concrete suggestions

1. **V1 contract amendments (before Runtime):**
   - In `srl_environment.py`, extend `SrlRelevanceAssessment` with:
     - `assessor_policy_digest: NonEmptyStr`
     - `provider_invocation_receipt_digest: NonEmptyStr | None`
     - `proposed_goal_statement: NonEmptyStr | None`
     - `minimum_external_input: NonEmptyStr | None`
     - `proposed_task_class: NonEmptyStr | None`
     - model validator: `CREATE_TASK`/`INVESTIGATE` require `proposed_goal_statement`; `HELP` requires `minimum_external_input`; `CREATE_TASK` requires `proposed_task_class`.
   - In `mandate.py`, extend `StandingMission` with:
     - `correction_epoch: int = Field(ge=0)`
     - `ratification_receipt_digest: NonEmptyStr`
   - In `srl_help.py` or the authority package, add a typed response wrapper (e.g., `SrlHelpResponse` with discriminated union `OperatorDecision | CapabilityGrant | RevocationRequest`) and a `response_authority_digest` field.

2. **Add missing abuse cases:**
   - AC-11: Mandate status downgrade treated as active.
   - AC-12: Task/effect class outside `MandateEnvelope` allowed classes.
   - AC-13: Environment binding read→write escalation.
   - AC-14: W1/W2 update relaxes mission/envelope bounds.
   - AC-15: Portfolio proposer accepts its own outcome.

3. **Add missing invariants I-16 through I-20** covering the items in P0-2, P0-3, P1-1, P1-2, P1-3, P1-4, and P1-7.

4. **Add a contract/traceability matrix** to §5 showing, for each invariant, the exact V0 contract field or the required V1 addition.

5. **Clarify §9** to state explicitly which invariants are already enforceable by V0 Pydantic validators and which require V1 contract additions or Runtime adapters.

6. **Add separation-of-powers test** to §8: verify that no single `instance_id`/`version` can both produce a `SrlRelevanceAssessment`/`ProposedGoal` and emit the authority record that accepts it.

---

## Reviewer notes

- The document correctly avoids autonomy/Product/evidence claims and keeps the scope to contracts only (§1, §9, §10). This should be preserved.
- The alignment with ADR-0037 is good: SD4 is treated as forbidden, C7 as non-writable/non-bypassable, and learning is confined to W1/W2 or external W3/W4 promotion.
- The primary risk is not a wrong threat model but a **contract-traceability gap**: the model is one revision ahead of the V0 contracts. Closing that gap is the blocking work.
