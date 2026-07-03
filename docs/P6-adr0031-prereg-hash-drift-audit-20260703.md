# P6 ADR-0031 Prereg-Hash Drift Audit (2026-07-03)

- Status: drift audit / no fresh claim / no verdict change
- Layer: object / mechanism evidence hygiene
- Scope: `ADR-0031` historical result authority versus current worktree drift

## Conclusion

`ADR-0031` remains the last committed historical authority for the
`PRED1-HOLDS` claim.

The current worktree must **not** be treated as a fresh re-verification of that
result, because the prereg-hash lineage is currently split three ways:

1. committed docs still cite one prereg hash;
2. the working-tree result artifact carries a second prereg hash;
3. the current code now computes a third prereg hash.

Until that drift is separately adjudicated, the correct interpretation is:

```text
historical ADR-0031 verdict: preserved
fresh verification status: NOT AUTHORIZED
Gate-2 relevance: none
route-promotion relevance: none
```

## Evidence

Committed documentation still cites:

- `fe40754e2f7ff59dc6529af23703bfcf8ff99006a9e4e4a8a64694adf14833bf`

Current worktree result artifact contains:

- `806a41a4467de6478c2601d17f296de57e6b7049e136246e386f9b840c7ac665`

Current code computes:

- `47b05e6455f542b0ee04b4d894766672272ed0cdd156a7417dac4b73438cf424`

Sources inspected:

- `docs/CURRENT_STATE.yaml`
- `docs/PROJECT_PLAN.md`
- `docs/adr/ADR-0031-prediction1-residual-calibrator-vs-g10.md`
- `experiments/prediction1_residual_calibrator.py`
- `experiments/prediction1_residual_calibrator.result.json`

## Interpretation Boundary

This audit does **not** say:

- ADR-0031 is overturned;
- `PRED1-HOLDS` is newly falsified;
- Gate-2 should reopen;
- Direction 1 should change;
- VH/G-Eco should be revived.

It says only this:

- the historical `ADR-0031` claim remains the last committed authority;
- the current worktree no longer supports treating that line as freshly
  hash-consistent;
- any future agent must not silently absorb the working-tree result file as if
  it were the historical locked artifact.

## Required Next Action

If this line is ever touched again, it must go through a separate adjudication
step that decides one of the following:

1. restore the historical artifact/lock lineage;
2. regenerate the result artifact under a newly explicit lock lineage;
3. formally record that the current worktree result file is non-authoritative
   and must remain excluded from claims.

Until then, the safe posture is:

```text
preserve the historical ADR-0031 verdict as last committed authority;
do not treat the current worktree as fresh verification.
```
