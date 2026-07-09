# Strong-Locus Structure Crossover — Organ-Alone Arm

> **Status:** locked prompt template. Any change requires prereg amendment + re-freeze.
> **Arm:** `organ_alone` — strong LLM reasoner with in-context belief scratchpad, no discovery tools.

## Task

You are discovering the causal structure of a system with {n_nodes} variables.
You may observe the system passively and, within a fixed budget of {budget},
intervene on variables in set **S**. Your goal is to infer which directed
causal edges exist among all variables. You will be scored solely on a
**disjoint held-out set T** that you never see.

You have seen {n_observations} observation rows so far.

## Rules

1. Output a final list of directed edges `(i -> j)` with a confidence score in `[0, 1]`.
2. You may use the scratchpad below to track your belief; it is not executed.
3. Do not propose or execute actions outside the intervention budget.
4. Do not condition your answer on the held-out set T.

## Scratchpad

```
Step: {step}
Budget remaining: {budget_remaining}
Current belief: {belief_summary}
Next proposed intervention: ____________
Reasoning: ____________
```

## Output format

Return a JSON object:

```json
{{
  "edges": [[i, j, confidence], ...],
  "scratchpad": "..."
}}
```
