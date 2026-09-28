# Research Route Capsules

Route capsules isolate research mechanism, environment, evaluator, preregistration and result artifacts.
Product code (`packages/`, `apps/`) must not import from `research/routes/`.

## Directory structure

```
<route_id>/
  mechanism/
  environment/
  evaluator/
  prereg/
  result/
```

## Admission rules

1. Every route declares exact files, claim class, consumer and status.
2. Product code cannot import Research modules directly.
3. Historical files remain in place until a separate history-safe move.
4. Code existence cannot imply route activation or product admission.

## Promotion candidates

Sealed outputs from research routes (promoted via independent evaluation) are stored in
`promotion_candidates/` and consumed by Product through one-way adapters.
