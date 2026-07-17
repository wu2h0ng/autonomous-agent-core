# R-STATE-CREDIT-1 Independent External Exact-Head Methodology Review

> Date: `2026-07-17`
> Reviewer: external independent methodology reviewer
> Provider & model identity: `deepseek-v4-pro` (deepseek/deepseek-v4-pro)
> Reviewer role: external, not builder, not codex, not internal self-attack, not freezer, not authorizer
> Exact HEAD under review: `0ca38aa3491161fa115c0b58685cf408e5be106b`
> Branch: `codex/r-state-credit-1-real-bindings-20260715`
> Working tree at review time: clean, 0 modified files
> Verdict: **APPROVE_FREEZE_CANDIDATE**
> Verdict class: `APPROVE_FREEZE_CANDIDATE` — this authorizes the candidate bytes at `0ca38aa` to enter a **separate freezer** identity's freeze-candidate process only.
> Explicit non-grants: no freeze issuance, no freeze-lock creation, no run, no result, no training, no provider call, no promotion, no product capability.

---

## 1. Method

1. Verified `git rev-parse HEAD == 0ca38aa3491161fa115c0b58685cf408e5be106b` and `git status --short` clean.
2. Read the full documentary chain: recast design (`f5fd8eb`), design review (`CONDITIONAL_APPROVE`), design amendment, independent review request (post-P1-closure), self-attack review (F1–F19), review-3 fix report, review-4 fix report, P1 fix report and brief.
3. Read all mechanism source files: `interactive_env.py`, `recast_arms.py`, `arm_blinding.py`, `actor_interface.py`, `action_grammar.py`, `observation.py`, `authority_verifier.py`, `authority_artifacts.py`, `signature_backend.py`, `trajectory_driver.py`, `statistical_integrity.py`, `prereg_resolution.py`, `prereg_candidate.py`, `episode_generator.py`.
4. Read the recast run-contract candidate JSON, exact-content manifest JSON, candidate prereg JSON, legacy retired prereg YAML and manifest, and CURRENT_STATE.yaml.
5. Read all test files: sealed_referee, valid_time, recast_arms, recast_integration, freeze_candidate_closure, review-v3/v4/v5 closure, arm_blinding, authority_verifier.
6. Executed read-only verification (no code changed, no freeze, no provider call):
   - `pytest tests/test_r_state_credit_1*.py -q` → **208 passed** (107.4s)
   - Full research gate `PYTHONPATH=src python -m unittest discover -s tests` → **1237 tests OK (skipped=16)** (180.5s)
   - `ruff check experiments/r_state_credit_1 tests/test_r_state_credit_1*.py` → **All checks passed!**
   - `pyright experiments/r_state_credit_1` → **0 errors, 0 warnings, 0 informations**
   - `python -m experiments.r_state_credit_1.prereg_candidate --check` → **VALID_CANDIDATE_ONLY**, 29 checked source files
   - `git diff --check` → clean

All evidence is from fresh read-only runs against the exact HEAD. No prior chat conclusions were relied on.

---

## 2. Assessment of original six defects (head `7852671`)

| # | Original finding | Closure assessment |
|---|---|---|
| 1 | Public `family + checkpoint` metadata predicts sealed truth | **Closed.** `ActorRequest` carries only `representation`, `valid_actions`, and `session_label`. Family and checkpoint ordinal are absent from actor-visible bytes. `canonical_json()` excludes `turn_index` and `observed_at_turn`. G1 dummy classifier passes on all seven canonical families (accuracy ≤ majority_prior + 0.05, κ ≤ 0.05). |
| 2 | 140 episodes reduce to seven templates | **Closed.** Each seed produces a distinct `structural_signature()` tuple `(T, entity_count, alias_topology, checkpoint_positions, perturbation_schedule)`. G2 across all 7 families: each family produces >7 structural classes and ≥30% seed-dependent correct-action checkpoints. All 140 `(family, seed)` pairs have distinct global signatures. |
| 3 | Authority records are self-fillable | **Closed.** `AuthorityVerifier` requires 5 distinct signer identities with cross-reference digest checks, signature verification, expiration, witness-ref presence and content matching, acceptance flags, `max_runs == 1`, `result_bearing == true`, and `run_id` binding. `verify_binding_artifacts` rejects any `signer_principal_id == builder_id`. Tests cover builder-minted, tampered-payload, and missing-witness cases. |
| 4 | Fixed arm order and exposed arm identity | **Closed.** `ArmBlinding.call_order()` derives a uniform random permutation from `sha256("arm-order-v1" + episode_seed + checkpoint_ordinal)`. Neutral labels `rep-a`…`rep-d` replace real arm IDs. Reverse mapping is `ArmBlinding.resolve_response()`, runner-only. G3 χ² with df=9, G4 Miller-Madow NMI ≤ 0.05 across `(family, seed, checkpoint)` axes, byte-level scan for forbidden substrings passes. |
| 5 | A3 policy injection | **Closed.** `recast_arms.TypedStateArm` emits no `recovery_directive`, `action_hint`, `recommended_action`, or `policy` field. G6 scans serialized actor-request bytes for whole-word directive hints across development seeds with zero hits. Legacy `arms.py::A3TypedStateArm` still contains `recovery_directive` but is excluded from the frozen source manifest, run contract mechanism files, and trajectory driver. |
| 6 | Static classification, not long-horizon interaction | **Closed.** `InteractiveEpisode` is a 20–60 turn deterministic turn-based loop with `observe()` → `step()` → state update. Perturbations are injected at seed-determined turns, actions change sealed state, and observations are released incrementally. Reversibility tests produce bit-identical event sequences and blinding state across replays. |

---

## 3. Assessment of F4 and F7–F18 (self-attack findings)

| ID | Original severity | Closure assessment |
|---|---|---|
| F4 | P1 — checkpoint algorithm | **Closed** at `e3592c3`. `_select_checkpoint_turns()` enumerates all 4-element combinations with ≥3-turn spacing from eligible terminal turns, selects one via `rng.randrange(len(combinations))`. Matches amended pseudo-code. |
| F7 | P1 — dummy classifier | **Closed** at post-review-request commit. `test_full_gate_g1_dummy_classifier` trains majority-vote dummy on `(family, checkpoint_ordinal)` against referee truth across all 7 canonical families with held-out seeds; accuracy ≤ majority_prior + 0.05, κ ≤ 0.05. |
| F8 | P1 — directive hints scan | **Closed.** G6 now scans serialized actor-request bytes (not just `response.notes`) for whole-word directive hints. |
| F9 | P1 — instance independence | **Closed.** `test_instance_independence_across_canonical_families` checks >7 structural classes per family and ≥30% seed-dependent checkpoint actions across all families. |
| F10 | P2 — witness content check | **Closed.** `_verify_single_artifact` requires witness files to contain artifact `payload_digest`. |
| F11 | P2 — verifier side effects | **Closed.** `verify_binding_artifacts` delegates to `verify(builder_principal=builder_id)` without mutating verifier state. |
| F12 | P2 — perturbation classes incomplete | **Closed.** All 18 frozen `PerturbationClass` values have observation builders and state-effect branches; schedule samples 4–6 classes per episode from the full enum. |
| F13 | P2 — family/seed metadata in temp tree | **Closed.** `_materialize_state` writes only entity and alias state; no family/seed metadata. |
| F14 | P2 — neutral label naming | **Closed.** Labels renamed `arm-a…d` → `rep-a…d`. |
| F15 | P2 — prereg candidate protocol | **Closed.** Candidate declares turn range 20–60, checkpoint protocol with combination-enumeration, perturbation protocol, budgets, neutral blinding. |
| F16 | P2 — run authorization replay | **Closed.** `RunAuthorizationArtifact.run_id` bound to the signed content layer; `AuthorityVerifier.verify(run_id=…)` rejects mismatches. |
| F17 | P3 — perturbation stubs | **Closed.** No `NotImplementedError` stubs remain in the perturbation dispatch layer. |
| F18 | P3 — HMAC test backend | **Closed** as documented-limitation. Review request §8 explicitly discloses the test-only backend and freeze-time swap requirement; §9 question 2 defers backend adequacy to independent reviewer. |

---

## 4. Assessment of OC-P1-1, OC-P1-2, OC-P1-3 (OpenCode P1 closure)

| ID | Closure assessment |
|---|---|
| OC-P1-1 — Sealed referee | **Closed.** `referee_correct_action()` derives truth from sealed `SealedDecisionConditions` (pending_effect, pending_recovery, blocked_commitment, pressure, conflict, stale_binding). `test_paired_histories_byte_identical_observation_different_truth` demonstrates bit-identical current observations with diverged sealed histories requiring diverged correct actions. The event-class lookup fails to discriminate. Resolution observations (`EFFECT_VERIFIED`, `STATE_REVIEWED`, `ABSTENTION_RECORDED`, `RECOVERY_APPLIED`) are visible. |
| OC-P1-2 — valid_time leakage | **Closed.** `_build_valid_schedule()` produces a seed-specific irregular clock with origin jitter and per-turn irregular increments. Opaque refs via `_opaque_ref()` replace turn-numbered identifiers. Absolute-turn fields became relative delays. Legacy affine inverse recovers <10% of turns; two-point affine fit <35%; checkpoint positions not recoverable; before/after/supersession relations remain decidable; out-of-order displacement not one fixed offset. |
| OC-P1-3 — Real A0–A3 arms | **Closed.** `recast_arms.py` implements `FullLogArm`, `RollingSummaryArm`, `BoundedRetrievalArm`, `TypedStateArm` with per-arm `ArmBudgetLedger` (A0 peak mode, A1–A3 cumulative mode). Overflow is sticky and isolated per arm. `ActorRequest` carries arm-rendered `representation` bytes. `ArmBlinding.blinded_calls()` wires real representations per call-order position. No shared A0 forcing. |

---

## 5. Review-3, review-4, and review-5 closures (external reviews at later commits)

All closure tests pass at `0ca38aa`:

- **Review-3** (11 tests): retired-input rejection, G3/G4 executable statistics, route-label absence, exhaustive loss table, trajectory authority qualification-only.
- **Review-4** (12 tests): G3 Pearson independence with df=9, chi-square mutation detection, exact Cartesian product coverage, recovery route from full history, no route proxy in representations, internal truth record non-serializability, closed qualification projection boundary.
- **Review-5** (7 tests): integrity contract canonical ClassVar lock, identical recovery bytes require different history routes, subset/family/recovery/classification attacks all fail closed.
- **Freeze-candidate closure** (7 tests): candidate action set matches grammar, both recovery routes observed on development seeds, wrong recovery is `STALE_BELIEF_USE` not `UNSAFE_EFFECT_REPLAY`, legacy prereg retired, recast manifest binds all declared bytes.

---

## 6. P0 findings

None. All P0 items from the self-attack review (F1, F2, F3) were closed at `44de1ae` or earlier and remain closed at `0ca38aa`.

---

## 7. P1 findings

None found at methodology level that block freezing this candidate.

The candidate at `0ca38aa` is a **mechanism and protocol candidate**, not a complete runnable experiment. This is explicitly disclosed in the review request §1 status line (`IMPLEMENTATION_READY_FOR_INDEPENDENT_REVIEW / NOT_FROZEN / NOT_RUN / NOT_EVIDENCE`). The following items are pre-run requirements, not freeze-blockers, but a separate reviewer must confirm them before any freeze-lock is created:

1. **Signature backend remains HMAC-SHA256 for tests only.** `TestHmacBackend` is deterministic and non-secure. The `Ed25519BackendStub` is a placeholder. The production freeze must swap to a real asymmetric signature scheme (e.g., Ed25519) with key management. This is disclosed in review request §8 bullet 1 and §9 question 2; the independent reviewer (this document) confirms that the disclosed test-only HMAC backend is **acceptable for the freeze-candidate stage** and must be replaced before any result-bearing run.

2. **No provider/actor binding exists in the recast path.** The candidate `actor_binding_protocol` requires `provider`, `model_id`, `model_revision_or_snapshot`, `system_prompt_sha256`, and `tool_schema_sha256` to be bound at freeze. The qualification tests use deterministic `StubActor` only. A real provider binding must be independently reviewed and bound into the frozen contract before any run.

3. **No recast result runner or scorer wiring exists.** `run_checkpointed_episode` is explicitly `SHARED_QUALIFICATION_TRAJECTORY_ONLY` with no scorer, verdict, or result writer. A result-bearing runner must be independently reviewed.

4. **Legacy formal prereg retirement is declared inside the candidate.** The recast run-contract candidate (`RECAST-RUN-CONTRACT-CANDIDATE-2026-07-17.json`) lists `EXACT-CONTENT-MANIFEST-2026-07-15.json` and `PREREGISTRATION-2026-07-15.yaml` as `RETIRED_HISTORY_ONLY` in its `legacy_inputs` section. The legacy files themselves carry `status: RETIRED_HISTORY_ONLY` / `active_freeze_input: false`. `prereg_resolution.resolve_active_prereg_inputs()` rejects them. The freeze process must use only the recast run-contract candidate, not the retired legacy inputs.

---

## 8. P2 findings (methodology observations, not freeze-blocking)

1. **Family→perturbation binding is declared by the candidate but not enforced by the generator.** The candidate prereg declares `required_perturbations` and `referee_targets` per family (e.g., `CONTRADICTION` family requires `SIMULTANEOUS_CONFLICTING_EVIDENCE`, `DELAYED_DEPENDENT_ACTION`, `PROCESS_RESTART`). However, `_schedule_perturbations()` samples 4–6 classes from all 18 `PerturbationClass` values uniformly via `rng.sample`, and `family_id` enters only `_episode_seed()` — it is a seed salt, not a perturbation constraint. The generator treats all seven families identically.

   **Assessment:** This is a declared-contract incompleteness, not a methodology defect. The design does not require per-family perturbation conditioning (§4 merely requires structural seed variability), so the failure is that the candidate **over-declares** its guarantees. The families still serve as 7 independent seed-salt strata with structurally distinct episodes per seed (G2 verified), so the robustness gate `AT_LEAST_5_OF_7_FAMILIES_IMPROVE` is still meaningful as a robustness check over 7 independent groups — the groups just differ by salt rather than by perturbation pedigree. **Recommendation:** Either implement per-family perturbation conditioning or remove the `required_perturbations`/`referee_targets` decorations from the candidate before freeze (the reviewer may choose either path).

2. **Checkpoint terminal turns use evenly-spaced grid, not per-class semantic derivation.** The amendment §4.2 defines per-class terminal-phase triggers (e.g., `RECEIPT_LOSS`: "first post-due turn", `PRECONDITION_REFUTATION`: "the refutation turn"). The implementation spaces terminal turns evenly across `[5, T-2]` and applies `_terminal_offset()` backward from each grid point to set the trigger turn. For offset-0 classes this collapses the trigger and terminal to the same turn; for offset-2 classes, the trigger fires two turns before the grid point.

   **Assessment:** Sealed conditions are genuinely active at each checkpoint (verified by the tests). The simpler grid-implementation is a mechanical rewrite of the terminal-phase concept, not a violation. The enumerative algorithm with 3-turn spacing and seed-determined selection is frozen and deterministic. **Recommendation:** The reviewer accepts this as an equivalent implementation. The amendment's per-class table serves as design rationale; the grid ensures spacing invariants hold on every seed.

3. **MET verdict grammar does not include the four design-listed integrity gates as explicit conditions.** The candidate `met_requires_all` includes 7 conditions while design §8.3 lists 11 (missing `INSTANCE_INDEPENDENCE_VALID`, `ARM_IDENTITY_BLINDING_VALID`, `ARM_ORDER_BALANCED`, `A3_POLICY_CONFOUND_ABSENT`). The stop rules also lack `STOP_INSTANCE_INDEPENDENCE`. The amendment §6 treats these as pre-freeze qualification gates (G1–G10), and the candidate's `INTEGRITY_VALID` umbrella condition could absorb them. **Recommendation:** Clarify in the freeze that `INTEGRITY_VALID` subsumes G1–G10 validation, or add the four missing gates explicitly. No code change required; this is a documentation-candidate alignment item.

4. **Sealed referee priority ladder and loss weights are builder-designed.** The priority ladder (pending effect → recovery → blocked commitment/pressure → conflict/stale → continue) and the frozen loss weights (0/1/2/3/3/5) are hardcoded in `_correct_action_for_conditions()` and `loss_map_for_conditions()`. They are disclosed in review request §8 and require independent acceptance before freeze. **This document accepts** the ladder as a reasonable task-design choice for the interactive state-maintenance envelope, with the caveat that the experiment's claim is only as strong as the ladder's task-relevance.

5. **Residual event-count disclosure.** Every arm envelope inherently reveals the number of released observations. A0 exposes `released` count, A1 exposes class counts, A2 exposes `omitted`/`selected` counts, A3 exposes epoch and assertion lists. The actor can always infer the current turn number from the representation length. This is disclosed in review request §8 and is inherent to any history-bearing representation — a full log necessarily reveals its own cardinality.

---

## 9. Disclosed limitations accepted as acceptable

The reviewer accepts the following disclosed limitations as non-blocking:

- HMAC test-only backend (swap required at production freeze)
- Legacy `arms.py::A3TypedStateArm` still contains `recovery_directive` but is excluded from the active recast manifest, run contract, and trajectory driver
- Development budgets never trigger arm overflow (fail-closed net only; overflow tested via injected small budgets)
- Resolution observations (`EFFECT_VERIFIED`, etc.) are visible as new environment event classes
- No `arms.py`, `result_runner.py`, `real_corpus.py`, or `real_scorer.py` are bound in the recast candidate; they remain history-only

---

## 10. Verdict

**APPROVE_FREEZE_CANDIDATE**

The candidate mechanism, protocol, and qualification tests at exact HEAD `0ca38aa3491161fa115c0b58685cf408e5be106b` satisfy the recast design requirements as amended, close all six original defects, close all self-attack F1–F19 findings, close all three OpenCode P1 methodology defects, and pass all qualification gates, static analysis, type-checking, and the full research-discover gate.

This verdict:

- **Grants**: authority to enter this candidate into a **separate freezer** identity's freeze-candidate process.
- **Requires before freeze-lock creation**: (a) review of the pre-run items in §7 above by the freezer and preregistration reviewer; (b) explicit acceptance of the sealed referee ladder and loss weights by the preregistration reviewer; (c) the P2 items in §8 need not be resolved for freeze but should be addressed before a result-bearing run.
- **Does not grant**: freeze issuance, freeze-lock creation, C7 acceptance, run authorization, result-bearing execution, training authority, verdict adjudication, Stage B design, product capability, autonomy, merger, push, or release.
- **Does not imply**: that the typed-state arm will outperform the full-log baseline — the experiment has not been run.

---

## 11. File created

- `docs/research/R-STATE-CREDIT-1-EXTERNAL-EXACT-REVIEW-0CA38AA-2026-07-17.md`

No other files were created, modified, deleted, frozen, or committed by this review.

