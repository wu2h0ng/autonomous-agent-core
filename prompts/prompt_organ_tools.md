# Strong-Locus Structure Crossover — Organ-Tools Arm

> **Status:** locked prompt template. Any change requires prereg amendment + re-freeze.
> **Arm:** `organ_tools` — same LLM reasoner, given Bayesian belief-update and
> info-gain machinery as callable tools. The tool implementations are
> byte-identical to the functions used inside the governed loop.

## Task

You are discovering the causal structure of a system with {n_nodes} variables.
You may observe the system passively and, within a fixed budget of {budget},
intervene on variables in set **S**. Your goal is to infer which directed
causal edges exist among all variables. You will be scored solely on a
**disjoint held-out set T** that you never see.

You have seen {n_observations} observation rows so far. You do not compute
posteriors or information gains yourself. Instead, you may call the two tools
below. Their outputs are authoritative; your role is to orchestrate them.

## Current belief summary

- Step: {step}
- Budget remaining: {budget_remaining}
- Particles: {n_particles}
- Posterior entropy: {posterior_entropy}
- Top edge predictions: {top_edge_predictions}

## Rules

1. Output a final list of directed edges `(i -> j)` with a confidence score in `[0, 1]`.
2. Use `belief_update` to revise your posterior after each observation.
3. Use `info_gain` to choose the next intervention.
4. Do not propose or execute actions outside the intervention budget.
5. Do not condition your answer on the held-out set T.

## Tools

### `belief_update`

Update the particle posterior over DAG structures given new observations.

- Input:
  - `observations`: list of observation rows.
  - `prior_state`: current posterior state (particles + weights); omit on first call.
- Output: posterior state (particles + weights).

### `info_gain`

Rank candidate interventions by expected reduction in posterior entropy.

- Input:
  - `observations`: current observational/interventional data.
  - `candidate_interventions`: `{{node: [value1, value2, ...]}}`
  - `posterior_state`: current posterior
- Output: ranked list `[[node, value, expected_information_gain], ...]` sorted by descending gain.

## Output format

Return a JSON object:

```json
{{
  "tool_call": {{"name": "info_gain" or "belief_update", "arguments": {{...}}}},
  "scratchpad": "..."
}}
```

When the budget is exhausted or no positive information gain remains, return:

```json
{{
  "edges": [[i, j, confidence], ...],
  "scratchpad": "..."
}}
```
