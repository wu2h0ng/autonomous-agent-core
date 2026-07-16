# R-STATE-CREDIT-1 Independent Re-Review Request

> Date: `2026-07-16`
> Branch: `codex/r-state-credit-1-real-bindings-20260715`
> Review target head: `c063b37fd22d0583f27f21ae5c5e1a7128fed2d6`
> Working-tree HEAD at document creation: `c063b37fd22d0583f27f21ae5c5e1a7128fed2d6` (P2 F12/F17: all 18 frozen perturbation classes implemented)
> Status: `IMPLEMENTATION_READY_FOR_INDEPENDENT_REVIEW / NOT_FROZEN / NOT_RUN / NOT_EVIDENCE`
> Track: `Research Track`
> Claim class: `research-automation` — candidate-byte implementation only. Not product, not autonomy, not evidence.
> Authority:
> - `docs/research/R-STATE-CREDIT-1-recast-design-2026-07-16.md`
> - `docs/research/R-STATE-CREDIT-1-recast-design-review-2026-07-16.md`
> - `docs/research/R-STATE-CREDIT-1-recast-design-amendment-2026-07-16.md`

## 1. Request

Request an independent re-review of the R-STATE-CREDIT-1 recast implementation (Phases 1–3 plus integration tests) before a new exact head is frozen and any result-bearing run is authorized.

The original head `7852671` was rejected for six findings. The recast design packet (`f5fd8eb`) and amendment (`f9019b5`) were `CONDITIONAL_APPROVED / DESIGN_ONLY`. This request package points to the implementation bytes and tests that mechanically close each finding and each open concern.

No provider call, model inference, training, freeze, or run is claimed or performed by this document.

## 2. Scope

### In scope

- Interactive turn-based episode environment (`experiments/r_state_credit_1/interactive_env.py`).
- Deterministic episode generator (`experiments/r_state_credit_1/episode_generator.py`).
- Bounded observation contract (`experiments/r_state_credit_1/observation.py`).
- Neutral arm-blinding and balanced call-order module (`experiments/r_state_credit_1/arm_blinding.py`).
- Provider-neutral actor interface and deterministic stub actor (`experiments/r_state_credit_1/actor_interface.py`).
- Frozen action grammar (`experiments/r_state_credit_1/action_grammar.py`).
- Typed authority artifacts (`experiments/r_state_credit_1/authority_artifacts.py`).
- Pluggable signature backend with test-only HMAC and Ed25519 stub (`experiments/r_state_credit_1/signature_backend.py`).
- Independent authority verifier (`experiments/r_state_credit_1/authority_verifier.py`).
- Phase 1–3 qualification and integration tests (`tests/test_r_state_credit_1_interactive_env.py`, `tests/test_r_state_credit_1_arm_blinding.py`, `tests/test_r_state_credit_1_authority_verifier.py`, `tests/test_r_state_credit_1_recast_integration.py`).

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

SHA-256 computed from the worktree at document creation.

| Path | SHA-256 |
|---|---|
| `experiments/r_state_credit_1/interactive_env.py` | `4b6fa981076afb9c7fd753bb04f680792294d39831a807ed73d7f3c4ca8901e4` |
| `experiments/r_state_credit_1/episode_generator.py` | `2685895ee5bb02b27420c68d5928fdda10613b9c53b24b67248dd68cb951fe43` |
| `experiments/r_state_credit_1/observation.py` | `b07db0e872adcea5bf40df64889ed8f92a0fc9cddcba85f596ff8a6558ea53bf` |
| `experiments/r_state_credit_1/arm_blinding.py` | `b22bf1f09276da53d85d9db16834d497630b43fc6f87a2de07ebb53f936e8b69` |
| `experiments/r_state_credit_1/actor_interface.py` | `ead674ca87964ee8893e73f9193491b9bd0770aead6f6533b6a47e1c7461d5ec` |
| `experiments/r_state_credit_1/action_grammar.py` | `7fbf5415f0bafc596cfb40195a9e34ea88e559088ce53203a4c9a50753964a98` |
| `experiments/r_state_credit_1/authority_artifacts.py` | `f72ad2a36c314637b1a3a7ac88dc57f0d6fc3d4b7fec899d0260c01c3abee0b0` |
| `experiments/r_state_credit_1/signature_backend.py` | `066757e3a58c4b439b8e3058d2a0bc220be46e36488603e9a23c92f9c9d00e76` |
| `experiments/r_state_credit_1/authority_verifier.py` | `55dafe560f754af6dcdc2580573fa67034e965abc2ea61fa9db7621d6e7ac635` |
| `experiments/r_state_credit_1/recast_readme.md` | `08f40e9dddcdcff12faf563ce781b94b2b88d3a1c7395d1b6a56f38c5901e8c7` |
| `experiments/r_state_credit_1/prereg_candidate.py` | `da90c3d57b544ee420b641945d9d50005c5bacccd6d153e9781f5f0c6f997057` |
| `tests/test_r_state_credit_1_interactive_env.py` | `f0c1088ca1279e1c7baf6bd15c732d6da1b6e9f81144acea8f793f4808b75fbe` |
| `tests/test_r_state_credit_1_arm_blinding.py` | `2a93dbee7ee5e2f30981fc6a1cc7f85e0223eadbbccf459929e723a637a06214` |
| `tests/test_r_state_credit_1_authority_verifier.py` | `992966670fb544ce2d98a1d4641ae18e150ac1939e0835a7cf20255a9103a1fb` |
| `tests/test_r_state_credit_1_recast_integration.py` | `a01d6e83d1f3ebcfac16789518abecd65b87c8e14f34ea425378b3e04f579f20` |
| `tests/test_r_state_credit_1_prereg_candidate.py` | `4c624e8c52844c6d6a1a771bd1c66a642a2b7d81c04684304b75cc8ef5e55119` |
| `docs/research/R-STATE-CREDIT-1-recast-design-2026-07-16.md` | `fe7a766d53894dd194afe4324fee032cb93b6197a593274fbe124403fbb25a53` |
| `docs/research/R-STATE-CREDIT-1-recast-design-review-2026-07-16.md` | `fe188c2ecd203fc7884bf8b0a40872d9ee67ecdf09105a3d23bd06580d13f892` |
| `docs/research/R-STATE-CREDIT-1-recast-design-amendment-2026-07-16.md` | `e93291c3e85ffe969d9fe0d029226fd5a279005e85743fa08cbf0f96544b7646` |
| `docs/research/R-STATE-CREDIT-1-recast-self-attack-review-2026-07-16.md` | `b988d8e5347a5fc977f6696a1620d291d3624b9a924a7f1ad1e7eaf620817e88` |

## 6. Verification commands

From the worktree root:

```bash
# Confirm the implementation/integration head.
git rev-parse HEAD

# Targeted Phase 1-3 qualification + integration tests.
uv run --extra product-test pytest \
  tests/test_r_state_credit_1_interactive_env.py \
  tests/test_r_state_credit_1_arm_blinding.py \
  tests/test_r_state_credit_1_authority_verifier.py \
  tests/test_r_state_credit_1_recast_integration.py \
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
  experiments/r_state_credit_1/authority_artifacts.py \
  experiments/r_state_credit_1/signature_backend.py \
  experiments/r_state_credit_1/authority_verifier.py \
  tests/test_r_state_credit_1_interactive_env.py \
  tests/test_r_state_credit_1_arm_blinding.py \
  tests/test_r_state_credit_1_authority_verifier.py \
  tests/test_r_state_credit_1_recast_integration.py
```

Expected results as measured on this worktree:

- Targeted Phase 1-3 tests: `40 passed, 0 failed`.
- Full `tests/test_r_state_credit_1*.py`: `142 passed, 0 failed`.
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
| G6 — No directive in arm output | Implemented / tested | `test_full_gate_g6_no_recovery_directive_in_arm_output` scans serialized actor-request bytes and `StubActor` response notes for the four frozen G6 directive field names (`recovery_directive`, `action_hint`, `recommended_action`, `policy`). Environment vocabulary (e.g. a recovery or retry record inside an observation payload) is not a runner directive. The legacy `arms.py::A3TypedStateArm` still contains `recovery_directive` and is explicitly excluded from the frozen source manifest. |
| G7 — Reversibility | Implemented / tested | `test_reversibility` and `test_reversibility_across_blinding` compare bit-identical event sequences and checkpoint/call-order state across replays. |
| G8 — Authority builder rejection | Implemented / tested | `test_builder_minted_artifact_rejected`, `test_authority_bundle_with_builder_signer_rejected`, `test_tampered_payload_rejected`. |
| G9 — Budget overflow fail-closed | Implemented / tested | `test_budget_overflow_fail_closed`, `test_no_overflow_on_development_seeds`, `test_observation_budget_envelope_per_turn`. |
| G10 — Checkpoint determinism | Implemented / tested | `test_four_checkpoints` verifies exactly four checkpoints, spacing ≥ 3 turns, and range `[5, T_max - 2]`; `test_checkpoint_algorithm_matches_amendment` checks `_select_checkpoint_turns` against the amended combination-enumeration pseudo-code on development seeds. |

## 8. Known limitations / deviations

- **Signature backend uses HMAC-SHA256 for test harness only.** `TestHmacBackend` is deterministic and per-identity distinct, but it is not a secure signature scheme. `Ed25519BackendStub` is provided as a production placeholder. The production freeze must replace the test backend with an equivalent asymmetric signature scheme (e.g., Ed25519) and wire real key management.
- **Legacy `arms.py` still contains the A3 `recovery_directive` but is excluded from the frozen source manifest.** The recast qualification path does not invoke the old A0–A3 arms; it uses the new `ActorRequest` / `StubActor` interface. The frozen run contract binds only the recast mechanism files listed in the source manifest.
- **All 18 frozen perturbation classes are implemented.** Every `PerturbationClass` enum value has an observation builder and a state-effect branch and is schedulable at seed-determined turns (`rng.sample` over the full enum per episode; a trigger colliding with another class shifts to the nearest earlier free turn, staying at or before its terminal phase). `REPRESENTATION_PRESSURE` and `PROTECTED_STATE_AT_BOUND` are marker-only observations that deliberately do not mutate state. Verified by `test_all_frozen_perturbation_classes_observable` across 120 seeds.
- **No provider/model call has been made.** All tests use deterministic stub actors and local HMAC signatures.

## 9. Questions for the independent reviewer

1. Does the current interactive environment + episode generator satisfy the instance-independence gate for all seven canonical families, or must a family-wise diagnostic be added and pass before freeze?
2. Is the authority artifact verifier topology sufficient for the non-self-minting gate, given that the signature backend is currently HMAC-SHA256 for tests with an Ed25519 stub ready for production?
3. Should the legacy `arms.py::A3TypedStateArm.recovery_directive` be removed or the entire legacy arm file retired before freeze, even though the recast qualification path does not use it?
4. Is the G1 dummy-classifier probe in the integration tests adequate as a freeze gate, or must the full scikit-learn `DummyClassifier` using `family + checkpoint` against sealed truth be implemented first?
5. Now that all 18 frozen perturbation classes are implemented, are the checkpoint trigger semantics (terminal-phase table + deterministic selection algorithm with 3-turn spacing + trigger-collision shift to the nearest earlier free turn) sufficiently frozen for the preregistration lock, and are the marker-only classes (`REPRESENTATION_PRESSURE`, `PROTECTED_STATE_AT_BOUND`) acceptable as observation-only perturbations?

## 10. Next steps after review

1. **Reviewer verdict:** Return a verdict document in `docs/research/` as one of:
   - `ACCEPT_FOR_FREEZE` — no freeze-blocking issues.
   - `CONDITIONAL_APPROVE` — list exact required fixes before freeze.
   - `REVISE_BEFORE_REVIEW` — material issues remain; re-review required.
2. **If accepted:** Create a `native-freeze-lock.json` by a freezer identity distinct from builder and reviewers, binding the exact-content manifest of `c063b37fd22d0583f27f21ae5c5e1a7128fed2d6`.
3. **C7 acceptance:** Obtain `c7-acceptance-<owner_id>.json` binding epoch, capability token digest, and stop path.
4. **Founder/CTO run authorization:** Obtain `run-authorization-<founder_id>.json` referencing the freeze lock and C7 acceptance, authorizing exactly one result-bearing run.
5. **Result-bearing run:** Execute one frozen run under the native freeze lock, with independent adjudication and claim review.

## 11. Non-claims

This review request does not establish autonomy, product capability, experimental validity, or a result. It is a research-governance gate before freeze.
