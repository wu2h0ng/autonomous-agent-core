# R-STATE-CREDIT-1 Phase 1 — Interactive Episode Recast

This directory contains Phase 1 of the R-STATE-CREDIT-1 recast: an interactive,
turn-based episode environment and a seed-dependent corpus generator.  It
replaces the static 24-event classification template from the rejected head
`7852671`.

## New modules

- `observation.py` — `Observation` contract model with canonical JSON
  serialization for byte-budget measurement.
- `interactive_env.py` — `InteractiveEpisode`: deterministic, reversible,
  turn-based loop materializable in a temporary directory.  Supports the full
  perturbation architecture; all eighteen frozen perturbation classes are
  implemented (observation + effect) and the dispatch layer is exhaustive.
- `episode_generator.py` — `EpisodeGenerator`: seeded by `family_id` +
  `seed_id`, produces structurally distinct episodes per seed with a frozen
  perturbation schedule and exactly four checkpoints.
- `tests/test_r_state_credit_1_interactive_env.py` — Phase 1 qualification
  tests: reversibility, seed distinctness, budget overflow fail-closed behavior,
  checkpoint spacing, and temp-directory isolation.

## Running Phase 1 tests

From the repository root:

```bash
.venv/bin/python -m pytest tests/test_r_state_credit_1_interactive_env.py -v
```

To also verify that the existing corpus and scorer tests still pass:

```bash
.venv/bin/python -m pytest tests/test_r_state_credit_1_real_corpus.py tests/test_r_state_credit_1_real_scorer.py -q
```

Lint and type-check the new files:

```bash
ruff check experiments/r_state_credit_1/interactive_env.py experiments/r_state_credit_1/episode_generator.py experiments/r_state_credit_1/observation.py tests/test_r_state_credit_1_interactive_env.py
.venv/bin/python -m pyright experiments/r_state_credit_1/interactive_env.py experiments/r_state_credit_1/episode_generator.py experiments/r_state_credit_1/observation.py tests/test_r_state_credit_1_interactive_env.py
```

## Design anchors

- `docs/research/R-STATE-CREDIT-1-recast-design-2026-07-16.md` §3–4
- `docs/research/R-STATE-CREDIT-1-recast-design-amendment-2026-07-16.md` §2–4

## Phase 2 — Arm blinding and neutral actor interface

Phase 2 adds the experimental controls needed to compare representation arms
without confounding by arm identity, call order, or embedded action policy.

### New modules

- `action_grammar.py` — Frozen `ActorAction` grammar: `REVIEW`, `VERIFY_EFFECT`,
  `ABSTAIN`, `CONTINUE`, `RECOVER_ROLLBACK`, `RECOVER_ROLL_FORWARD`.  Validation
  helpers enforce the closed set.
- `actor_interface.py` — `ActorRequest` and `ActorResponse` contracts.  The
  request contains only the observable prefix released so far, `turn_index`,
  `valid_actions`, and a neutral `session_label`.  No `arm_id`, family,
  checkpoint ordinal, sealed label, or future events are present.  Includes a
  deterministic `StubActor` that can be replaced by a provider-backed actor
  later.
- `arm_blinding.py` — `ArmBlinding`: maps real arm identities to the neutral
  labels `arm-a`, `arm-b`, `arm-c`, `arm-d` per episode and checkpoint.  Call
  order is a uniform random permutation derived from the episode seed and
  checkpoint ordinal; reverse mapping is runner-only.
- `tests/test_r_state_credit_1_arm_blinding.py` — Phase 2 qualification tests:
  byte-level absence of real arm names and role hints, χ² call-order uniformity,
  independence of call order from family/seed, neutral-label enforcement, and
  runner-only reverse mapping.

### Running Phase 2 tests

```bash
.venv/bin/python -m pytest tests/test_r_state_credit_1_arm_blinding.py -v
```

To verify that Phase 1 and the existing corpus/scorer tests still pass:

```bash
.venv/bin/python -m pytest tests/test_r_state_credit_1_interactive_env.py tests/test_r_state_credit_1_real_corpus.py tests/test_r_state_credit_1_real_scorer.py -q
```

Lint and type-check the new files:

```bash
ruff check experiments/r_state_credit_1/arm_blinding.py experiments/r_state_credit_1/actor_interface.py experiments/r_state_credit_1/action_grammar.py tests/test_r_state_credit_1_arm_blinding.py
.venv/bin/python -m pyright experiments/r_state_credit_1/arm_blinding.py experiments/r_state_credit_1/actor_interface.py experiments/r_state_credit_1/action_grammar.py tests/test_r_state_credit_1_arm_blinding.py
```

### Design anchors

- `docs/research/R-STATE-CREDIT-1-recast-design-2026-07-16.md` §5
- `docs/research/R-STATE-CREDIT-1-recast-design-amendment-2026-07-16.md` §6 G3–G5

## Phase 3 — Authority artifact format, signature/witness mechanism, and verification

Phase 3 implements the non-self-minting authority topology required by the
recast amendment §5.  The builder can no longer fill or sign acceptance and
authorization artifacts; each required role is issued and signed by a distinct
identity.

### New modules

- `authority_artifacts.py` — Pydantic-style dataclasses for the five required
  artifact types: `prereg-acceptance`, `architecture-acceptance`,
  `native-freeze-lock`, `c7-acceptance`, and `run-authorization`.  Each artifact
  carries a content layer, an envelope with `artifact_id`, `payload_digest`,
  `signer_principal_id`, `signer_instance_id`, `signature_bytes`, `signed_at`,
  `expires_at`, and `witness_refs`, plus an `AuthorityArtifactBundle` container.
- `signature_backend.py` — `SignatureBackend` protocol, a deterministic
  `TestHmacBackend` using `hmac` + `hashlib.sha256` with distinct per-identity
  secrets, and an `Ed25519BackendStub` ready for production substitution.
- `authority_verifier.py` — `AuthorityVerifier` and typed `VerificationResult`.
  Verifies that artifacts are signed by distinct allowed identities, rejects
  builder-minted artifacts, checks signatures, expiration, witness references,
  payload digest consistency, cross-references between artifacts, acceptance
  flags, and the one-run result-bearing authorization constraint.
- `tests/test_r_state_credit_1_authority_verifier.py` — Phase 3 qualification
  tests covering builder rejection, unknown signer rejection, payload tampering
  detection, expiration, distinct-identity topology, valid-bundle acceptance,
  and witness-reference validation.

### Running Phase 3 tests

```bash
.venv/bin/python -m pytest tests/test_r_state_credit_1_authority_verifier.py -v
```

To verify that Phases 1–2 and the existing corpus/scorer tests still pass:

```bash
.venv/bin/python -m pytest tests/test_r_state_credit_1_interactive_env.py tests/test_r_state_credit_1_arm_blinding.py tests/test_r_state_credit_1_real_corpus.py tests/test_r_state_credit_1_real_scorer.py -q
```

Lint and type-check the new files:

```bash
ruff check experiments/r_state_credit_1/authority_artifacts.py experiments/r_state_credit_1/signature_backend.py experiments/r_state_credit_1/authority_verifier.py tests/test_r_state_credit_1_authority_verifier.py
.venv/bin/python -m pyright experiments/r_state_credit_1/authority_artifacts.py experiments/r_state_credit_1/signature_backend.py experiments/r_state_credit_1/authority_verifier.py tests/test_r_state_credit_1_authority_verifier.py
```

### Design anchors

- `docs/research/R-STATE-CREDIT-1-recast-design-2026-07-16.md` §7
- `docs/research/R-STATE-CREDIT-1-recast-design-amendment-2026-07-16.md` §5, §6 G8

## Status

Phases 1–3 implementation only.  No provider calls, no model inference, no
result-bearing run, and no freeze are created by this code.
