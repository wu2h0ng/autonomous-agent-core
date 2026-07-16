# R-STATE-CREDIT-1 Recast Implementation — Internal Self-Attack Review

> Date: `2026-07-16`
> Reviewer: internal self-attack (not an external verdict)
> Target implementation head: `664e746e8ca0170fd33922c67b994cf944d985a7`
> Worktree HEAD at review time: `75d40ebbaca298a63aaf60d698395b475c31a82d`
> Branch: `codex/r-state-credit-1-real-bindings-20260715`

## 1. Reviewer stance

This document is an internal adversarial self-attack produced before the
independent re-review requested in
`docs/research/R-STATE-CREDIT-1-independent-review-request-2026-07-16.md`.
It is not an external verdict, not a freeze authorization, and not a result.
Its purpose is to surface defects, spec deviations, and weak tests that an
independent reviewer could flag.

## 2. Scope

Design/amendment/review authority:

- `docs/research/R-STATE-CREDIT-1-recast-design-2026-07-16.md`
- `docs/research/R-STATE-CREDIT-1-recast-design-review-2026-07-16.md`
- `docs/research/R-STATE-CREDIT-1-recast-design-amendment-2026-07-16.md`
- `docs/research/R-STATE-CREDIT-1-independent-review-request-2026-07-16.md`

Implementation files reviewed:

- `experiments/r_state_credit_1/interactive_env.py`
- `experiments/r_state_credit_1/episode_generator.py`
- `experiments/r_state_credit_1/observation.py`
- `experiments/r_state_credit_1/arm_blinding.py`
- `experiments/r_state_credit_1/actor_interface.py`
- `experiments/r_state_credit_1/action_grammar.py`
- `experiments/r_state_credit_1/authority_artifacts.py`
- `experiments/r_state_credit_1/signature_backend.py`
- `experiments/r_state_credit_1/authority_verifier.py`
- `experiments/r_state_credit_1/contracts.py`
- `experiments/r_state_credit_1/arms.py`
- `experiments/r_state_credit_1/prereg_candidate.py`
- `experiments/r_state_credit_1/run_contracts.py`

Test files reviewed:

- `tests/test_r_state_credit_1_interactive_env.py`
- `tests/test_r_state_credit_1_arm_blinding.py`
- `tests/test_r_state_credit_1_authority_verifier.py`
- `tests/test_r_state_credit_1_recast_integration.py`

## 3. Severity legend

| Severity | Meaning |
|---|---|
| P0 | Blocks freeze or a result-bearing run; must be fixed before external review. |
| P1 | Must fix before re-review; material spec violation or weak gate. |
| P2 | Should fix; real gap but does not invalidate the protocol on its own. |
| P3 | Cosmetic, documentation, or cleanup item. |

## 4. Findings table

| ID | Severity | Claim from design/amendment | What was implemented | Gap or defect | Suggested fix | Test that would catch it |
|---|---|---|---|---|---|---|
| F1 | P0 | Amendment §4.5: actor request must not contain turn index, checkpoint ordinal, or any signal that a checkpoint is occurring. | `arm_blinding.py::actor_request` passes `turn_index` straight into `ActorRequest`, and `Observation` serializes `turn_index` and `observed_at_turn` in its canonical JSON. | The actor sees the exact turn number at every checkpoint and in every observation. Because checkpoint positions are deterministic from the seed, a model that knows the schedule can infer checkpoint ordinal from `turn_index`. | Remove `turn_index` from `ActorRequest`; remove or blind `turn_index` / `observed_at_turn` from `Observation` canonical serialization (keep them only in runner-internal state). | `test_byte_level_no_turn_index_metadata` that asserts `"turn_index"` and `"observed_at_turn"` are absent from serialized actor-request bytes. |
| F2 | P0 | Amendment §5 / design §7.3: authority artifacts must be issued by identities the builder cannot mint; `verify_binding_artifacts` must reject builder-generated authority. | `authority_verifier.py::verify_binding_artifacts` adds `{builder_id}:{builder_id}` and bare `builder_id` to the rejection set, but compares against full identity keys of the form `{principal_id}:{instance_id}`. | An artifact signed with `signer_principal_id == builder_id` and an arbitrary `instance_id` (e.g., `builder:external-1`) is *not* rejected. The bare `builder_id` entry never matches a real identity key. | In `verify_binding_artifacts`, reject any artifact whose `signer_principal_id` equals `builder_id`, regardless of `instance_id`. Add a dedicated rejection branch in `_verify_single_artifact`. | `test_builder_principal_any_instance_rejected` that creates an artifact with `signer_principal_id=builder_id` and `instance_id != builder_id` and asserts rejection. |
| F3 | P0 | Design §9.4 / amendment §5: exact-content manifest must cover every mechanism and corpus byte. | `prereg_candidate.py::_SOURCE_PATHS` lists only legacy files (`arms.py`, `scenarios.py`, `contracts.py`, etc.). | The new recast mechanism files (`interactive_env.py`, `episode_generator.py`, `arm_blinding.py`, `actor_interface.py`, `authority_artifacts.py`, `authority_verifier.py`, `signature_backend.py`, `observation.py`, `action_grammar.py`) are not in the source manifest. The native freeze lock cannot bind them. | Extend `_SOURCE_PATHS` to include every file in the recast qualification path and remove files no longer used by the recast run contract. | Run `python -m experiments.r_state_credit_1.prereg_candidate --check` and verify the manifest covers all recast mechanism files. |
| F4 | P1 | Amendment §4.3: checkpoint selection must implement the exact frozen pseudo-algorithm with minimum 3-turn spacing. | `interactive_env.py::_select_checkpoint_turns` originally used `rng.sample(range(len(eligible_terminal_turns)), 4)` and sorted the result. | The original implementation was not the algorithm specified in the amendment and could not guarantee the spacing invariant on all seeds. | Implement the amendment pseudo-code literally: enumerate every 4-element combination of eligible terminal turns with consecutive spacing ≥3, draw one combination with `rng.randrange`, and return it in ascending order. | `test_checkpoint_algorithm_matches_amendment` that compares output against a reference implementation of the amendment pseudo-code on a grid of seeds. |
| F5 | P1 | Amendment §2.2 / §2.3: A0 overflow must force A0 to `ABSTAIN` while other arms continue; non-A0 overflow must force only that arm to `ABSTAIN`. | `interactive_env.py::observe` maintains a single `_a0_overflow` flag and a single `_arm_overflow` flag, both derived from the same `_cumulative_a0_bytes()` measurement. | There is no per-arm representation budget. When the A0 tuple exceeds `B_A0`, the returned `forced=ABSTAIN` is applied to every arm in the runner, not just A0. Non-A0 arms cannot continue independently. | Track cumulative bytes per representation arm in the runner; compare A0 tuple size to `B_A0` and each compressed representation to `B_ARM`; force `ABSTAIN` only for the arm(s) that overflow. | `test_a0_overflow_does_not_force_other_arms` that overflows `B_A0` only and asserts non-A0 arms still receive requests. |
| F6 | P1 | Design §6.3 / amendment G6: A3 output must contain no `recovery_directive` or equivalent privileged action hint. | The recast `StubActor` path returns no hints, but legacy `experiments/r_state_credit_1/arms.py::A3TypedStateArm.consume` still appends `"recovery_directive": TaskStateReducer.recovery_directive(snapshot)` to its representation. | The legacy A3 arm file is still in the repository and referenced by the source manifest. It can still be imported and executed by the old runner path, re-introducing the exact confound the recast was meant to remove. | Either remove `recovery_directive` from `A3TypedStateArm` or delete/deprecate the legacy arm file and exclude it from the frozen run contract. | Run the legacy `A3TypedStateArm.consume` on a sample `ArmInput` and assert `"recovery_directive" not in representation`. |
| F7 | P1 | Design §9 / amendment G1: dummy classifier using only `family + checkpoint` must not exceed chance on sealed truth. | `test_full_gate_g1_dummy_classifier` only checks fixed-action dummies (`ABSTAIN`, `CONTINUE`) against the majority prior. | It does not construct the design-mandated `family + checkpoint` feature and does not predict sealed truth. It cannot detect leakage of the correct action via public metadata. | Build the actual dummy-classifier gate: for each `(family, checkpoint_ordinal)` pair, predict the most common sealed action and measure accuracy / Cohen's κ against held-out seeds. | `test_family_checkpoint_dummy_classifier_no_better_than_chance` using `Counter` or `scikit-learn DummyClassifier` with sealed labels. |
| F8 | P1 | Amendment G6: no arm output may contain a privileged action hint. | `test_full_gate_g6_no_recovery_directive_in_arm_output` only inspects `response.notes`. | The `StubActor` returns empty notes, so the test passes trivially. It does not inspect the representation bytes actually delivered to the actor, where a directive could be embedded. | Search the serialized actor-request / representation bytes for directive substrings (`recovery_directive`, `action_hint`, `policy`, `recommended_action`, `rollback`, `rollforward`, `recover`, `retry`) and assert zero hits. | `test_actor_request_bytes_no_directive_hints` that scans every generated request. |
| F9 | P1 | Amendment G2 / design §4.1: instance-independence diagnostic must show no seven-template clustering across all seven canonical families. | `test_distinct_seeds` uses one synthetic `TEST_FAMILY` and proves 20 seeds differ. | There is no 7-family diagnostic. The design requires at least 30% of checkpoints within each family to have seed-dependent correct actions, measured across canonical families. | Add `test_instance_independence_across_canonical_families` that generates all `ScenarioFamily` values, computes structural signatures, and asserts no clustering into ≤7 equivalence classes plus the 30% decision-variation criterion. | The new test itself; run it on development seeds and report the metric. |
| F10 | P2 | Amendment §5.3: verifier must check cross-references, signatures, acceptance flags, and witness references. | `authority_verifier.py` verifies signatures, payload digests, and existence of witness files. | It did not verify that the witness file actually lists / contains the artifact's digest; a stale or empty witness file could satisfy the check. | Make the witness check content-aware: when the resolved witness path is a file, require the artifact's `payload_digest` to appear in the file contents. | `test_witness_file_must_contain_artifact_digest`. |
| F11 | P2 | Amendment §5.3: `verify_binding_artifacts` must be a fail-closed entry point. | `verify_binding_artifacts` passes the builder principal to `verify()` via a `builder_principal` keyword argument. | Original concern about mutating `self._builder_identities` no longer applies; the current implementation does not mutate shared state. | Keep `verify_binding_artifacts` as a thin, side-effect-free wrapper over `verify(builder_principal=builder_id)`. | Existing builder-rejection tests plus a regression test calling `verify_binding_artifacts` twice with different builder ids. |
| F12 | P2 | Design §3.1 / §3.2: perturbation classes must be injectable at seed-determined turns and the combination must vary by seed. | All 18 frozen classes are now implemented in `interactive_env.py`: `_schedule_perturbations` samples 4–6 classes from the full enum via `rng.sample` per seed (a colliding trigger shifts to the nearest earlier free turn so every class releases its own observation), and each class has an observation builder and a state-effect branch; `REPRESENTATION_PRESSURE` and `PROTECTED_STATE_AT_BOUND` are marker-only by design. | None remaining for this finding. | Implement the missing perturbation observations/effects (chosen over reducing the enum, which design §3.2 mandates in full). | `test_all_frozen_perturbation_classes_observable` runs 120 seeds and asserts every enum value is scheduled by some seed and observed once its trigger turn is reached. |
| F13 | P2 | Design §3.1: episode materializes in a temporary directory with no external side effects. | `InteractiveEpisode` writes only observable entity/alias state into the temp tree. | No `README.md`, `state/runtime.json`, or other identifying metadata is written; family and seed remain runner-internal. `test_temp_tree_contains_no_family_seed_metadata` audits every file. | Keep identifying metadata in memory; do not add metadata files to the materialized tree. | `test_temp_tree_contains_no_family_seed_metadata`. |
| F14 | P2 | Design §5.1 / §5.2: arm identity must be absent from actor inputs. | `arm_blinding.py` uses neutral labels `arm-a` ... `arm-d`. | The substring `arm` is still present in the actor request. While not a real arm identity, it is a role hint inconsistent with the design's "Representation X" neutral labels. | Rename neutral labels to `rep-a` ... `rep-d`. | Update `NEUTRAL_LABELS` and ensure `test_byte_level_no_arm_identity` still passes. |
| F15 | P2 | Design §8 / amendment: frozen preregistration candidate must reflect the new interactive envelope. | `prereg_candidate.py::build_stage_a_prereg_candidate` now emits `episode_length_turns_range_inclusive: [20, 60]`, `checkpoint_protocol` with `SEED_DETERMINED_COMBINATION_ENUMERATION_WITH_MIN_3_TURN_SPACING`, `perturbation_protocol`, and recast budgets `O_MAX`, `B_A0`, `B_ARM`. Arms carry `blinding_protocol: NEUTRAL_LABEL_NO_ARM_IDENTITY_IN_ACTOR_REQUEST`. | None remaining for this finding. Legacy `arms.py` implementation paths remain as runner implementation references, but the envelope, checkpoint, perturbation, and budget contracts now describe the recast protocol. | Update the candidate builder to describe the recast protocol exactly: turn range, perturbation schedule, checkpoint selection algorithm, budget parameters, and neutral actor interface. | `validate_stage_a_prereg_candidate` and `test_stage_a_candidate_declares_complete_non_authorizing_protocol` assert the recast envelope, checkpoint protocol, and budgets. |
| F16 | P2 | Amendment §5.3: authority artifacts must be limited to one result-bearing run (`max_runs == 1`, `result_bearing == true`) and bound to a single run id. | `RunAuthorizationArtifact` now carries a non-empty `run_id`; `AuthorityVerifier.verify()` optionally checks it against the caller-supplied run id; `verify_binding_artifacts()` forwards the run id. | None remaining for this finding. | Bind a unique run id into the `run-authorization` artifact and verify it against the runner's run id; or maintain an external spent-authorization ledger. | `test_run_authorization_run_id_binding` accepts the matching run id and rejects a mismatched run id. |
| F17 | P3 | Design §3.2: all listed perturbation classes must be implementable. | The perturbation dispatch layer in `interactive_env.py` is now exhaustive over the frozen enum; no perturbation `NotImplementedError` stubs remain. | None remaining for this finding. The remaining `NotImplementedError` hits are out of scope here: `signature_backend.py` (F18 production-backend stub) and `authority_artifacts.py::content_mapping` (template method overridden by every concrete artifact). | Implement the classes (done under F12). | `test_all_frozen_perturbation_classes_observable`; static grep confirms no perturbation stubs remain. |
| F18 | P3 | Amendment §5.1: production signature mechanism must be asymmetric. | `signature_backend.py` provides `TestHmacBackend` and an `Ed25519BackendStub` that raises `NotImplementedError`. | The production backend is a stub. This is acknowledged, but an external reviewer will note it as a freeze blocker until a real backend is wired. | Replace `Ed25519BackendStub` with a real Ed25519 backend and key-management harness, or freeze with the stub explicitly documented as a known limitation. | Run `pytest` with the production backend configured. |
| F19 | P3 | Worktree / review target consistency. | The independent review request names `664e746` as the implementation head. | The worktree HEAD at review time is `75d40eb`, two documentation commits after `664e746`. The doc-only commits do not change mechanism files, but the review package should align the stated head with the actual bytes under review. | Either reset the review target to `664e746` or update the request document to name `75d40eb` and recompute the manifest. | `git rev-parse HEAD` matches the head named in the review request. |

## 5. Positive closures

The following claims are genuinely closed by the implementation:

- **Arm identity removed from actor request.** `actor_interface.py::ActorRequest` has no `arm_id`, family, checkpoint ordinal, or sealed label. `arm_blinding.py` replaces real `ArmId` values with neutral labels before the actor sees the request, and the reverse mapping is available only to the runner (`resolve_response`).
- **Call order is randomized and deterministic.** `ArmBlinding.call_order` derives a uniform permutation from `hash("arm-order-v1" + episode_seed + checkpoint_ordinal)`, is independent of family/seed content, and is reproducible across restarts.
- **Authority topology enforces distinct non-builder identities.** `AuthorityVerifier` requires five distinct signer identity keys, rejects builder identities (basic case), verifies payload digests, detached signatures, expiration, witness-ref presence, acceptance flags, `max_runs == 1`, `result_bearing == True`, and cross-reference digests between artifacts.
- **Run authorization is bound to a single run id.** `RunAuthorizationArtifact` carries a non-empty `run_id` in its signed content layer. `AuthorityVerifier.verify(run_id=...)` rejects a mismatched run id, so the same authorization cannot be replayed for a different run (F16).
- **Interactive turn-based loop exists.** `InteractiveEpisode` is materializable in a temp directory, runs 20–60 turns deterministically from the seed, applies state changes per action, and releases observations incrementally.
- **Reversibility is tested.** `test_reversibility` and `test_reversibility_across_blinding` demonstrate bit-identical event sequences, checkpoints, and neutral call order across replays.
- **A3 policy confound removed from recast path.** The new `StubActor` selects actions from observations and the frozen grammar only; it does not receive or emit a `recovery_directive` or equivalent hint.
- **Per-turn byte cap enforced.** `ObservationSizeExceeded` is raised if any single observation exceeds `O_MAX`, and the integration tests verify normal development seeds stay within the cap.
- **Legacy rejection test present.** `test_builder_minted_artifact_rejected` and `test_authority_bundle_with_builder_signer_rejected` confirm that at least the obvious builder-identity case is rejected.

## 6. Questions for the external reviewer

1. **Turn-index metadata:** `Observation` and `ActorRequest` currently expose `turn_index` (and `observed_at_turn`) to the actor. Is this acceptable as inherent sequence information, or does it violate the design amendment's "no turn-index metadata" rule and need to be removed/blinded before freeze?

2. **Legacy `arms.py`:** The recast qualification path does not invoke `arms.py`, but the file still contains `A3TypedStateArm` with the `recovery_directive` confound and is referenced by the existing source manifest. Should it be removed, recast, or explicitly excluded from the frozen run contract before the independent review?

3. **Signature backend:** The authority verifier currently uses an HMAC test backend with an `Ed25519BackendStub` placeholder. Is this sufficient for the non-self-minting gate at review time, or must a real asymmetric backend and key-management harness be wired and exercised before a freeze can be authorized?

## 7. Summary

- **Findings by severity:** P0 = 3, P1 = 6, P2 = 7, P3 = 3.
- **Verdict:** Not ready for external review without fixes.
- **Blocking issues:**
  - `turn_index` leaks in `ActorRequest` and `Observation` bytes (F1).
  - Authority verifier does not reject all builder-principal artifacts (F2).
  - Exact-content manifest / source manifest does not cover the new recast mechanism files (F3).
- **Recommended hold:** Resolve at least F1–F3 and F5–F9 before submitting to independent re-review. The remaining P2 items can be addressed in parallel but should not be deferred past freeze.

## 8. Post-fix status

Self-attack fixes were applied at commit `44de1ae` and the independent review
request package was updated to post-fix head `44de1ae` at `9a5aa28`.

| ID | Severity | Status | Fix commit / note |
|---|---|---|---|
| F1 | P0 | Closed | `44de1ae` — `turn_index`/`observed_at_turn` removed from `ActorRequest` and `Observation.canonical_json()`. |
| F2 | P0 | Closed | `44de1ae` — `AuthorityVerifier` rejects any artifact with `signer_principal_id == builder_id`. |
| F3 | P0 | Closed | `44de1ae` — `_SOURCE_PATHS` extended with the nine recast mechanism files. |
| F4 | P1 | Closed | Amendment §4.3 revised to enumerate all valid 4-checkpoint combinations and select one deterministically from the seed; `_select_checkpoint_turns` updated to match the revised pseudo-code. `test_four_checkpoints` and `test_checkpoint_algorithm_matches_amendment` pass on development seeds. |
| F5 | P1 | Closed | `44de1ae` — A0 overflow no longer forces non-A0 arms to abstain. |
| F6 | P1 | Closed | `e32f530` — revised resolution: legacy `arms.py` retains `A3TypedStateArm.recovery_directive` but is excluded from the frozen prereg source manifest (`_SOURCE_PATHS`), so the recast contract does not bind the legacy confound; the recast qualification path never invokes the legacy arms. |
| F7 | P1 | Closed | Post-review-request — `test_full_gate_g1_dummy_classifier` now trains a majority-vote dummy on `(family, checkpoint_ordinal)` and evaluates on held-out seeds. |
| F8 | P1 | Closed | Post-review-request — `test_full_gate_g6_no_recovery_directive_in_arm_output` now scans serialized actor-request bytes for whole-word directive hints. |
| F9 | P1 | Closed | Post-review-request — `test_instance_independence_across_canonical_families` verifies >7 structural classes per family and ≥30% seed-dependent correct-action checkpoints. |
| F10 | P2 | Closed | `_verify_single_artifact` now requires witness files to contain the artifact's `payload_digest`; `test_witness_file_must_contain_artifact_digest` rejects stale/empty witness content. |
| F11 | P2 | Closed | `verify_binding_artifacts` does not mutate `self._builder_identities`; it delegates to `verify(builder_principal=builder_id)`. |
| F12 | P2 | Closed | `c063b37` — all 18 frozen perturbation classes implemented (observation builders, state effects, terminal offsets, default-policy mapping); schedule samples from the full enum via `rng.sample`; `test_all_frozen_perturbation_classes_observable` asserts schedulability and observability across 120 seeds. |
| F13 | P2 | Closed | `InteractiveEpisode` writes no family/seed metadata to the temp tree; audited by `test_temp_tree_contains_no_family_seed_metadata`. |
| F14 | P2 | Closed | Neutral labels renamed from `arm-a` ... `arm-d` to `rep-a` ... `rep-d`; `test_byte_level_no_arm_identity` still passes. |
| F15 | P2 | Closed | `prereg_candidate.py` now emits the recast envelope (20–60 turns), `checkpoint_protocol` (4 seed-determined checkpoints with combination-enumeration selection), `perturbation_protocol`, and budgets `O_MAX`/`B_A0`/`B_ARM`. |
| F16 | P2 | Closed | `RunAuthorizationArtifact.run_id` added; `AuthorityVerifier.verify(run_id=...)` rejects mismatched run ids; `test_run_authorization_run_id_binding` covers accept/reject cases. |
| F17 | P3 | Closed | `c063b37` — perturbation `NotImplementedError` stubs removed; dispatch layer exhaustive over the frozen enum (see F12). |
| F18 | P3 | Open | Production Ed25519 backend remains a stub in `signature_backend.py`; must be replaced with a real backend or explicitly documented as a freeze limitation before freeze. |
| F19 | P3 | Closed | Review target head consistency maintained by refreshing the review request after each implementation head change. |
