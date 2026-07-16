# R-STATE-CREDIT-1 Independent Re-Review Request

> Date: `2026-07-16` (refreshed `2026-07-17` after P1 methodology closure)
> Branch: `codex/r-state-credit-1-real-bindings-20260715`
> Review target head: `08e08972017ac37537d788e94c1883d11650cefe`
> Working-tree HEAD at document refresh: `08e08972017ac37537d788e94c1883d11650cefe` (P1 closure: sealed state-dependent referee, valid-time de-leak, real A0-A3 arms with per-arm budgets)
> Status: `IMPLEMENTATION_READY_FOR_INDEPENDENT_REVIEW / NOT_FROZEN / NOT_RUN / NOT_EVIDENCE`
> Track: `Research Track`
> Claim class: `research-automation` — candidate-byte implementation only. Not product, not autonomy, not evidence.
> Authority:
> - `docs/research/R-STATE-CREDIT-1-recast-design-2026-07-16.md`
> - `docs/research/R-STATE-CREDIT-1-recast-design-review-2026-07-16.md`
> - `docs/research/R-STATE-CREDIT-1-recast-design-amendment-2026-07-16.md`

## 1. Request

Request an independent re-review of the R-STATE-CREDIT-1 recast implementation (Phases 1–3, integration tests, and the P1 methodology closure) before a new exact head is frozen and any result-bearing run is authorized.

The original head `7852671` was rejected for six findings. The recast design packet (`f5fd8eb`) and amendment (`f9019b5`) were `CONDITIONAL_APPROVED / DESIGN_ONLY`. A later independent OpenCode exact-head review of `f04e956` returned three P1 methodology defects; the current head closes all three mechanically:

1. **Sealed state-dependent referee.** `_default_policy(current_observation)` is no longer experimental truth. A runner-only sealed referee (`InteractiveEpisode.referee_correct_action` / `referee_loss_map` / `score_action`) derives the correct action and the recast loss map (frozen weights 0/1/2/3/3/5) from sealed cross-turn state: pending unverified effects, blocked commitments, unreviewed conflicts, stale bindings, and pending recovery records. Actor actions resolve sealed conditions and emit visible resolution observations (`EFFECT_VERIFIED`, `STATE_REVIEWED`, `ABSTENTION_RECORDED`, `RECOVERY_APPLIED`), so full-history representations can decide what the current observation alone cannot. Paired cases with byte-identical current observations and diverged sealed histories require diverged correct actions, and the default event-class lookup provably fails them (`tests/test_r_state_credit_1_sealed_referee.py`).
2. **Valid-time turn-index leak closed.** `valid_time` is now a sealed seed-derived clock (seed-specific origin, irregular increments), not `BASE_TIME + minutes=turn`. Out-of-order transactions displace relative to a sealed earlier reference turn; before/after/supersession relations stay decidable. Payload references are opaque seed-derived refs and absolute turn fields became relative delays. Byte-level and statistical recovery attacks (legacy inverse, two-point affine fit, checkpoint-set recovery) fail (`tests/test_r_state_credit_1_valid_time.py`).
3. **Real A0–A3 representation arms.** `experiments/r_state_credit_1/recast_arms.py` implements A0 full bounded raw log, A1 deterministic lossy rolling summary, A2 bounded retrieval under the frozen `nonroutine-recency-v1` rule, and A3 typed state/commitment/conflict compilation of the visible feed (policy-neutral). Each arm holds its own budget ledger (A0 peak bytes vs `B_A0`; A1–A3 cumulative bytes vs `B_ARM`) with sticky fail-closed overflow that forces only that arm to `ABSTAIN`; the shared A0 byte count no longer forces all arms. `ActorRequest` carries arm-rendered representation bytes; neutral labels, randomized call order, and runner-only reverse-map custody are unchanged (`tests/test_r_state_credit_1_recast_arms.py`).

No provider call, model inference, training, freeze, or run is claimed or performed by this document.

## 2. Scope

### In scope

- Interactive turn-based episode environment with sealed state-dependent referee and recast loss scorer (`experiments/r_state_credit_1/interactive_env.py`).
- Deterministic episode generator (`experiments/r_state_credit_1/episode_generator.py`).
- Bounded observation contract (`experiments/r_state_credit_1/observation.py`).
- Real A0–A3 representation arms with per-arm budget ledgers (`experiments/r_state_credit_1/recast_arms.py`).
- Neutral arm-blinding and balanced call-order module (`experiments/r_state_credit_1/arm_blinding.py`).
- Provider-neutral actor interface and deterministic event-class-lookup stub actor (`experiments/r_state_credit_1/actor_interface.py`).
- Frozen action grammar (`experiments/r_state_credit_1/action_grammar.py`).
- Typed authority artifacts (`experiments/r_state_credit_1/authority_artifacts.py`).
- Pluggable signature backend with test-only HMAC and Ed25519 stub (`experiments/r_state_credit_1/signature_backend.py`).
- Independent authority verifier (`experiments/r_state_credit_1/authority_verifier.py`).
- Qualification and integration tests (`tests/test_r_state_credit_1_interactive_env.py`, `tests/test_r_state_credit_1_arm_blinding.py`, `tests/test_r_state_credit_1_authority_verifier.py`, `tests/test_r_state_credit_1_recast_integration.py`, `tests/test_r_state_credit_1_sealed_referee.py`, `tests/test_r_state_credit_1_valid_time.py`, `tests/test_r_state_credit_1_recast_arms.py`).

### Out of scope

- Provider/model binding or live result-bearing run.
- Product-track activation, release, or autonomy claim.
- The legacy `arms.py` representation arms (A0–A3) used by the rejected `7852671` corpus path; they are not invoked by the recast qualification path in this package.

## 3. Original findings closure

| # | Original finding (head `7852671`) | How the recast implementation closes it mechanically | Key files / tests |
|---|---|---|---|
| 1 | Public `family + checkpoint` metadata predicts sealed truth. | `ActorRequest` contains no family, checkpoint ordinal, turn index, or sealed label. Checkpoints are derived from the seed-specific perturbation schedule, not from public metadata. | `actor_interface.py` (`ActorRequest`); `arm_blinding.py` (`actor_request`); `interactive_env.py` (`_select_checkpoint_turns`); tests: `test_full_gate_g1_dummy_classifier`, `test_byte_level_no_arm_identity`. |
| 2 | 140 episode-seed pairs reduce to seven independent templates. | Each seed gets a distinct perturbation schedule, alias topology, entity count, episode length, and checkpoint set. `EpisodeGenerator.structural_signature()` exposes these dimensions for audit. | `interactive_env.py` (`_build_initial_state`, `_build_aliases`, `_schedule_perturbations`, `_select_checkpoint_turns`); `episode_generator.py`; test: `test_distinct_seeds`. |
| 3 | Authority records are self-fillable. | Five typed authority artifacts require distinct non-builder identities, detached signatures, witness references, cross-reference digests, and acceptance flags. `AuthorityVerifier` rejects builder-minted artifacts and tampered payloads. | `authority_artifacts.py`; `authority_verifier.py`; `signature_backend.py`; tests: `test_builder_minted_artifact_rejected`, `test_distinct_identity_topology_required`, `test_valid_bundle_accepted`, `test_authority_bundle_with_builder_signer_rejected`. |
| 4 | Fixed arm order and exposed arm identity. | `arm_blinding.py` replaces real arm IDs with neutral labels and computes a uniform random call order per checkpoint from the episode seed. The reverse mapping is runner-only. | `arm_blinding.py`; `actor_interface.py` (no `arm_id`); `action_grammar.py`; tests: `test_byte_level_no_arm_identity`, `test_call_order_chi_square_uniform`, `test_call_order_independent_of_family_seed`, `test_neutral_labels_only`, `test_reverse_mapping_runner_only`. |
| 5 | A3 policy injection (`recovery_directive`). | The recast actor interface and `StubActor` select actions only from the observation prefix and the frozen action grammar. No directive, hint, or arm-specific policy is embedded in the actor request or in the stub response notes. | `actor_interface.py`; `action_grammar.py`; test: `test_full_gate_g6_no_recovery_directive_in_arm_output`. |
| 6 | Static classification, not long-horizon interaction. | `InteractiveEpisode` is a turn-based loop (20–60 steps) where actions change state, perturbations are injected at seed-determined turns, and observations are released incrementally. | `interactive_env.py` (`InteractiveEpisode`, `observe`, `step`, `run`); tests: `test_reversibility`, `test_temporary_directory_isolation`, `test_end_to_end_no_provider`. |

## 4. Open concerns resolution

| # | Open concern from design review | Amendment section | Implementation / test that resolves it |
|---|---|---|---|
| 2 | Representation budget and pressure fail-closed behavior. | Amendment §2 | `interactive_env.py` defines `O_MAX`, `B_A0`, `B_ARM`; `observe()` raises `ObservationSizeExceeded` for per-turn overflow and forces `ABSTAIN` on cumulative overflow. Tests: `test_no_overflow_on_development_seeds`, `test_budget_overflow_fail_closed`, `test_observation_budget_envelope_per_turn`. |
| 3 | A0 truncation risk and hard cap semantics. | Amendment §3 | A0 receives the complete ordered observation tuple (`_cumulative_a0_bytes`); no truncation or summarization is performed. Overflow forces `ABSTAIN` with reason `REPRESENTATION_BUDGET_OVERFLOW`. Tests same as concern 2. |
| 4 | Exact deterministic checkpoint trigger rule. | Amendment §4 | `interactive_env.py` implements a terminal-phase table (`_terminal_offset`), seed-determined perturbation scheduling (`_schedule_perturbations`), and deterministic checkpoint selection (`_select_checkpoint_turns`) with minimum 3-turn spacing. Test: `test_four_checkpoints`. |
| 5 | Exact authority artifact format, signature mechanism, and verification code. | Amendment §5 | `authority_artifacts.py` provides the five JSON schemas and content-layer digests; `signature_backend.py` provides the signing protocol; `authority_verifier.py` implements `verify_binding_artifacts` and rejects builder-minted artifacts. Tests: Phase 3 authority verifier tests and integration authority tests. |

## 5. Artifact manifest

SHA-256 computed from the worktree at document refresh (head `08e0897`).

| Path | SHA-256 |
|---|---|
| `experiments/r_state_credit_1/interactive_env.py` | `3fe102fa9e66f19c26da941c8277117a221dd54b2b5cf62e3a40636c80d89129` |
| `experiments/r_state_credit_1/episode_generator.py` | `2685895ee5bb02b27420c68d5928fdda10613b9c53b24b67248dd68cb951fe43` |
| `experiments/r_state_credit_1/observation.py` | `b07db0e872adcea5bf40df64889ed8f92a0fc9cddcba85f596ff8a6558ea53bf` |
| `experiments/r_state_credit_1/arm_blinding.py` | `cabfdb67a8ffe92025e0af0fb8fd6fe89e914029c4a178950d0daeff010850da` |
| `experiments/r_state_credit_1/actor_interface.py` | `b0200a67d90fcdecff2249b3e195410cf7a683a89bfd9f32219c1176ba86ae0e` |
| `experiments/r_state_credit_1/action_grammar.py` | `7fbf5415f0bafc596cfb40195a9e34ea88e559088ce53203a4c9a50753964a98` |
| `experiments/r_state_credit_1/recast_arms.py` | `e0d7fc937f517767d99e83336b38cd074a77491339c2c0785c6d5e3cb01199a1` |
| `experiments/r_state_credit_1/authority_artifacts.py` | `f72ad2a36c314637b1a3a7ac88dc57f0d6fc3d4b7fec899d0260c01c3abee0b0` |
| `experiments/r_state_credit_1/signature_backend.py` | `066757e3a58c4b439b8e3058d2a0bc220be46e36488603e9a23c92f9c9d00e76` |
| `experiments/r_state_credit_1/authority_verifier.py` | `55dafe560f754af6dcdc2580573fa67034e965abc2ea61fa9db7621d6e7ac635` |
| `experiments/r_state_credit_1/recast_readme.md` | `08f40e9dddcdcff12faf563ce781b94b2b88d3a1c7395d1b6a56f38c5901e8c7` |
| `experiments/r_state_credit_1/prereg_candidate.py` | `bc8a28dad8a73f2de9e4d359011230404dfe5e58d669756362bb34f065a3193d` |
| `tests/test_r_state_credit_1_interactive_env.py` | `7967a5e12942414390fcd0296311310c4a822ffb54ec55a5a81927a2630bf4eb` |
| `tests/test_r_state_credit_1_arm_blinding.py` | `d8955e768e94cc230f3e7e6b5a143b9c075eea02e35149c65a9ea6eb24ec8b3e` |
| `tests/test_r_state_credit_1_authority_verifier.py` | `992966670fb544ce2d98a1d4641ae18e150ac1939e0835a7cf20255a9103a1fb` |
| `tests/test_r_state_credit_1_recast_integration.py` | `129235b34d98afeba606340208601e23ff3f63b28a1570dd3f61b8870a794a90` |
| `tests/test_r_state_credit_1_recast_arms.py` | `8b7d7f1f628052b7442cfce680d34616f34f50900a7d8ee69fc309e64eeb82d8` |
| `tests/test_r_state_credit_1_sealed_referee.py` | `f07b907451039dcfe44203abac6a0d2433f4ecac22b7a6e032165f154763442b` |
| `tests/test_r_state_credit_1_valid_time.py` | `3f095f8dbb5d22df7a31a792eb86d0b73e5364d9424a573935164ea24fb91c87` |
| `tests/test_r_state_credit_1_prereg_candidate.py` | `4c624e8c52844c6d6a1a771bd1c66a642a2b7d81c04684304b75cc8ef5e55119` |
| `docs/research/R-STATE-CREDIT-1-recast-design-2026-07-16.md` | `fe7a766d53894dd194afe4324fee032cb93b6197a593274fbe124403fbb25a53` |
| `docs/research/R-STATE-CREDIT-1-recast-design-review-2026-07-16.md` | `fe188c2ecd203fc7884bf8b0a40872d9ee67ecdf09105a3d23bd06580d13f892` |
| `docs/research/R-STATE-CREDIT-1-recast-design-amendment-2026-07-16.md` | `e93291c3e85ffe969d9fe0d029226fd5a279005e85743fa08cbf0f96544b7646` |
| `docs/research/R-STATE-CREDIT-1-recast-self-attack-review-2026-07-16.md` | `78c7e38d41ddadc78c0c61f033ed5a53a82d8ff0f899d0a2b95e928d84d3bbb8` |

## 6. Verification commands

From the worktree root:

```bash
# Confirm the implementation/integration head.
git rev-parse HEAD

# Targeted qualification + integration + P1 closure tests.
uv run --extra product-test pytest \
  tests/test_r_state_credit_1_interactive_env.py \
  tests/test_r_state_credit_1_arm_blinding.py \
  tests/test_r_state_credit_1_authority_verifier.py \
  tests/test_r_state_credit_1_recast_integration.py \
  tests/test_r_state_credit_1_sealed_referee.py \
  tests/test_r_state_credit_1_valid_time.py \
  tests/test_r_state_credit_1_recast_arms.py \
  -q

# Full R-STATE-CREDIT-1 test suite (includes existing corpus/scorer tests).
uv run --extra product-test pytest tests/test_r_state_credit_1*.py -q

# Full repository unittest discover.
uv run python -m unittest discover -s tests -v

# Lint and type check.
uv run ruff check experiments/r_state_credit_1 tests/test_r_state_credit_1*.py
uv run pyright experiments/r_state_credit_1 tests/test_r_state_credit_1*.py

# Manifest integrity spot-check.
sha256sum \
  experiments/r_state_credit_1/interactive_env.py \
  experiments/r_state_credit_1/episode_generator.py \
  experiments/r_state_credit_1/observation.py \
  experiments/r_state_credit_1/arm_blinding.py \
  experiments/r_state_credit_1/actor_interface.py \
  experiments/r_state_credit_1/action_grammar.py \
  experiments/r_state_credit_1/recast_arms.py \
  experiments/r_state_credit_1/authority_artifacts.py \
  experiments/r_state_credit_1/signature_backend.py \
  experiments/r_state_credit_1/authority_verifier.py \
  tests/test_r_state_credit_1_interactive_env.py \
  tests/test_r_state_credit_1_arm_blinding.py \
  tests/test_r_state_credit_1_authority_verifier.py \
  tests/test_r_state_credit_1_recast_integration.py \
  tests/test_r_state_credit_1_sealed_referee.py \
  tests/test_r_state_credit_1_valid_time.py \
  tests/test_r_state_credit_1_recast_arms.py
```

Expected results as measured on this worktree:

- Targeted qualification + P1 closure tests: `62 passed, 0 failed`.
- Full `tests/test_r_state_credit_1*.py`: `164 passed, 0 failed`.
- Full `unittest discover`: `1237 tests` with `OK (skipped=16)`.
- `ruff check`: `All checks passed!`
- `pyright`: `0 errors, 0 warnings, 0 informations`.

## 7. Pre-freeze mechanical gates checklist

| Gate | Status | Evidence |
|---|---|---|
| G1 — Dummy classifier leakage | Implemented / tested | `test_full_gate_g1_dummy_classifier` trains a majority-vote dummy on `(family, checkpoint_ordinal)` and evaluates on held-out seeds across all 7 canonical families; accuracy ≤ majority prior + 0.05 and Cohen's κ ≤ 0.05. |
| G2 — Instance independence | Implemented / tested | `test_instance_independence_across_canonical_families` verifies each canonical family produces >7 structural equivalence classes and ≥30% of checkpoints have seed-dependent correct actions. |
| G3 — χ² arm-order uniformity | Implemented / tested | `test_call_order_chi_square_uniform` passes with p > 0.01 criterion. |
| G4 — Arm-order independence | Implemented / tested | `test_call_order_independent_of_family_seed` passes χ² test of independence. |
| G5 — Byte-level absence of arm names | Implemented / tested | `test_byte_level_no_arm_identity` and `test_end_to_end_no_provider` search actor-request bytes for forbidden substrings. |
| G6 — No directive in arm output | Implemented / tested | `test_full_gate_g6_no_recovery_directive_in_arm_output` scans serialized actor-request bytes and `StubActor` response notes for the four frozen G6 directive field names (`recovery_directive`, `action_hint`, `recommended_action`, `policy`); `test_blinded_calls_deliver_arm_specific_bytes_with_custody` re-scans the real arm representations. Environment vocabulary (e.g. a recovery or retry record inside an observation payload) is not a runner directive. The legacy `arms.py::A3TypedStateArm` still contains `recovery_directive` and is explicitly excluded from the frozen source manifest. |
| G7 — Reversibility | Implemented / tested | `test_reversibility` and `test_reversibility_across_blinding` compare bit-identical event sequences and checkpoint/call-order state across replays. |
| G8 — Authority builder rejection | Implemented / tested | `test_builder_minted_artifact_rejected`, `test_authority_bundle_with_builder_signer_rejected`, `test_tampered_payload_rejected`. |
| G9 — Budget overflow fail-closed | Implemented / tested | `test_budget_overflow_fail_closed`, `test_no_overflow_on_development_seeds`, `test_observation_budget_envelope_per_turn`, plus per-arm isolation/stickiness in `test_arm_specific_overflow_cannot_force_other_arms` and `test_overflow_is_sticky_for_remaining_checkpoints`. |
| G10 — Checkpoint determinism | Implemented / tested | `test_four_checkpoints` verifies exactly four checkpoints, spacing ≥ 3 turns, and range `[5, T_max - 2]`; `test_checkpoint_algorithm_matches_amendment` checks `_select_checkpoint_turns` against the amended combination-enumeration pseudo-code on development seeds. |

## 8. Known limitations / deviations

- **Signature backend uses HMAC-SHA256 for test harness only.** `TestHmacBackend` is deterministic and per-identity distinct, but it is not a secure signature scheme. `Ed25519BackendStub` is provided as a production placeholder. The production freeze must replace the test backend with an equivalent asymmetric signature scheme (e.g., Ed25519) and wire real key management.
- **Legacy `arms.py` still contains the A3 `recovery_directive` but is excluded from the active source manifest.** The recast qualification path uses the new `recast_arms.py` implementations; the legacy arms and the rejected corpus/bindings remain history-only and must not enter the active manifest or a temp arm mount.
- **The legacy formal runner prereg (`docs/pre_spec/R-STATE-CREDIT-1.STAGE-A.PREREGISTRATION-2026-07-15.yaml`) and its exact-content manifest still bind the rejected corpus/scorer path bytes.** They stay internally consistent (candidate digests refreshed) as a historical record; the recast run contract must either re-derive a new formal prereg from the recast mechanisms or explicitly retire the legacy one before freeze. This is a reviewer decision, not a builder decision.
- **Released-event counts inherently bound the current turn.** A full-log baseline necessarily reveals how many observations have been released, and the bounded arms expose event counts; the P1-2 closure claim is that the timestamp channel and payload artifacts no longer encode exact turn/checkpoint positions beyond that inherent count.
- **Sealed-state resolutions are visible as dedicated observation classes.** `EFFECT_VERIFIED`, `STATE_REVIEWED`, `ABSTENTION_RECORDED`, and `RECOVERY_APPLIED` make prior action effects decidable from the full history; they are environment events, not directives, and are required so representation quality (not hidden state access) determines checkpoint decisions.
- **The sealed referee priority ladder is builder-designed.** Pending effect > pending recovery > blocked commitment/pressure > conflict > stale binding > continue, with the frozen loss weights 0/1/2/3/3/5. It is declared in the prereg candidate and requires independent review before freeze.
- **Development budgets never trigger arm overflow.** Per-arm overflow is a fail-closed safety net exercised by injected small budgets in tests, per amendment §2.
- **All 18 frozen perturbation classes are implemented.** Every `PerturbationClass` enum value has an observation builder and a state-effect branch and is schedulable at seed-determined turns. `PROTECTED_STATE_AT_BOUND` remains marker-only; `REPRESENTATION_PRESSURE` now raises a sealed pressure flag that requires an acknowledging `ABSTAIN`. Verified by `test_all_frozen_perturbation_classes_observable` across 120 seeds.
- **No provider/model call has been made.** All tests use deterministic stub actors and local HMAC signatures.

## 9. Questions for the independent reviewer

1. Does the current interactive environment + episode generator satisfy the instance-independence gate for all seven canonical families, or must a family-wise diagnostic be added and pass before freeze?
2. Is the authority artifact verifier topology sufficient for the non-self-minting gate, given that the signature backend is currently HMAC-SHA256 for tests with an Ed25519 stub ready for production?
3. Should the legacy `arms.py::A3TypedStateArm.recovery_directive` be removed or the entire legacy arm file retired before freeze, even though the recast qualification path does not use it?
4. Is the G1 dummy-classifier probe in the integration tests adequate as a freeze gate, or must the full scikit-learn `DummyClassifier` using `family + checkpoint` against sealed truth be implemented first?
5. Now that all 18 frozen perturbation classes are implemented, are the checkpoint trigger semantics (terminal-phase table + deterministic selection algorithm with 3-turn spacing + trigger-collision shift to the nearest earlier free turn) sufficiently frozen for the preregistration lock, and are the marker-only classes (`REPRESENTATION_PRESSURE`, `PROTECTED_STATE_AT_BOUND`) acceptable as observation-only perturbations?
6. Is the sealed referee priority ladder and loss assignment (pending effect > recovery > blocked commitment/pressure > conflict > stale binding; wrong-action classes per condition) acceptable as the frozen truth source, and are the paired-history discrimination tests sufficient evidence that the referee is not reducible to an event-class lookup?
7. Are the visible resolution observation classes acceptable as environment events, or do they need a narrower schema before freeze?
8. Should the legacy formal runner prereg and exact-content manifest (rejected corpus path) be retired now or kept as internally consistent history until the recast formal prereg is derived?

## 10. Next steps after review

1. **Reviewer verdict:** Return a verdict document in `docs/research/` as one of:
   - `ACCEPT_FOR_FREEZE` — no freeze-blocking issues.
   - `CONDITIONAL_APPROVE` — list exact required fixes before freeze.
   - `REVISE_BEFORE_REVIEW` — material issues remain; re-review required.
2. **If accepted:** Create a `native-freeze-lock.json` by a freezer identity distinct from builder and reviewers, binding the exact-content manifest of `08e08972017ac37537d788e94c1883d11650cefe`.
3. **C7 acceptance:** Obtain `c7-acceptance-<owner_id>.json` binding epoch, capability token digest, and stop path.
4. **Founder/CTO run authorization:** Obtain `run-authorization-<founder_id>.json` referencing the freeze lock and C7 acceptance, authorizing exactly one result-bearing run.
5. **Result-bearing run:** Execute one frozen run under the native freeze lock, with independent adjudication and claim review.

## 11. Non-claims

This review request does not establish autonomy, product capability, experimental validity, or a result. It is a research-governance gate before freeze.
