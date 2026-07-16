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
  perturbation architecture; ten perturbation classes are implemented and the
  remainder are stubbed via `NotImplementedError` in the dispatch layer.
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

## Status

Phase 1 implementation only.  No provider calls, no model inference, no
result-bearing run, and no freeze are created by this code.
