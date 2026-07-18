# R-W1W2-ABA-1 Design Brief

## Objective

Design, but do not implement or run, a falsifiable Research Track experiment
testing whether direct W1/W2 online state and in-envelope strategy adaptation
have value beyond strong cheap stateful baselines during real replayable
`A1 -> B -> restart -> A2` software-environment shifts.

## Foundational question

Can a bounded W1/W2 candidate adapt to B and recover on novel A2 tasks without
stale-state harm or catastrophic forgetting, while beating a version-keyed
cache, saved workflow, full-public-log frontier model, phase reset and simple
recency/contextual-bandit baselines at matched provider/tool/resource budgets?

## Required design properties

- At least nine independent lineage/version/task units from at least three
  pinned CLI/API/package families; steps and seeds are not independent units.
- A2 is a new task under the A regime, not an A1 answer replay.
- Real, provenance-bound, replayable version/interface/policy changes; no
  uncontrolled external effect and no synthetic adaptivity-gap revival.
- Hidden scorer owns regime truth, hidden tests, future outcomes and best-action
  labels. Actor may see normal public version metadata and past outcomes.
- No training, latent recurrence, W3/W4 upgrade, Product integration, freeze or
  result run in this package.
- Candidate does not receive more tools, calls, tokens, retries, wall time,
  state or recovery instructions than baselines.
- Primary killer baseline is version-keyed cache; full-log frontier and saved
  workflow are mandatory.
- Preserve C6/C7, no permission expansion, no evaluator self-ownership and no
  autonomy claim.

## Hard falsifiers

- Candidate does not lower cumulative verified-outcome loss/regret at matched
  cost versus the best mandatory baseline.
- A2 recovery latency is not better than version-keyed cache.
- Stale-belief harm, repeated error or rollback failure exceeds best baseline.
- Any advantage depends on hidden shift labels, future outcomes, expected
  actions or scorer feedback.
- Candidate wins only frozen/no-adapt arm but not full-log or saved-workflow.
- Any W5/C7/audit/permission violation.

## Required outputs from Claude

1. `research.md`: local evidence, relevant negative map, facts/inferences/
   assumptions, baseline reductions, unresolved design risks.
2. `spec.md`: implementation-ready design with objects, unit selection,
   matched arms, metrics/gates, oracle boundary, manifests/receipts, integrity
   and freeze prerequisites, test plan, stopping rules and claim ceiling.
3. Suggested acceptance-criteria updates.

## Forbidden

- Do not modify Product/Runtime code or experiment harness.
- Do not create private assignments, keys, hidden data or run permits.
- Do not read `/Users/mima1234/Documents/AI-Agent-Projects/.agent_runs/**/scorer-private`.
- Do not freeze, train, invoke a provider for result data, or run an experiment.
- Do not rescue PARK/NOT_MET routes by renaming or retuning them.

## Local anchors

- `docs/GOAL-BLUEPRINT.md` in parent workspace.
- `docs/CURRENT_STATE.yaml` in this repo and parent workspace.
- Existing `tests/research/r_srl_1/` only as an anti-pseudoreplication and
  operator-work reference; do not clone its result claim.
- Public negative evidence under parent `docs/research/` and this repo
  `docs/research/`; search for adaptivity-gap, R-STATE, W1/W2, A->B->A,
  pseudoreplication, oracle and version-keyed state.

