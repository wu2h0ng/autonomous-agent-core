# AGDE-T3 preregistration/result — SVAR temporal active discovery

- Date: 2026-07-04
- Relation to prior gates: AGDE-2 showed active choice can close the static MEC identification gap at
  the information-feasible budget; AGDE-T2 showed choosing WHEN adds value in a two-segment temporal
  setting. AGDE-T3 tests the harder temporal hypothesis class itself: contemporaneous MEC orientation
  plus lag-support in an SVAR arena.
- Claim scope: bounded simulation evidence for temporal active discovery under the governed loop. No
  autonomy, product, r-final, route-promotion, or C6/C7-change claim is authorized.

## Frozen Inputs

- Mechanism: `experiments/agde_t3_freeze.py`
- Arena: `experiments/svar_scm.py`
- Pilot lineage: `AGDE-T3.DESIGN-2026-07-04.md` v1..v5
- Causal-minimality convention: collapse survivors only when contemporaneous orientation is unique and
  the minimal lag-subset is unique.
- Scoring families: `9100..9111`, excluding calibration families `9000..9005`
- Run seeds: `{40, 41}`
- `tol = 0.5`
- `do_value = 3.2`
- Active/random budget: `B = 4`
- Blind-ceiling reference budget: `6`

## Decision Rule

Mechanical verdict:

- `INVALID` if any control fails.
- `MET` iff all controls pass, ACTIVE mean ID >= `0.70`, ACTIVE captures >= `0.50` of the
  BLIND_CEILING-minus-RANDOM gap, and ACTIVE beats RANDOM on at least two thirds of decided cases.
- `NULL` otherwise.

Controls:

- fresh family seeds, disjoint from calibration
- deterministic ACTIVE replay
- gate audit: approvals equal interventions and budget is not exceeded
- C7 halt guard: a paused shell blocks before the first intervention

## Result

Fresh scored run:

| quantity | value | frozen bar |
|---|---:|---:|
| ACTIVE mean ID | **0.5000** | >= 0.7000 |
| RANDOM mean ID | 0.2083 | report |
| BLIND_CEILING mean ID | 0.5000 | report |
| capture vs blind ceiling | 1.0000 | >= 0.5000 |
| ACTIVE > RANDOM | 8/9 decided cases | >= 2/3 |
| controls | all pass | required |

Verdict: **NULL**.

Interpretation: AGDE-T3 does show active intervention choice over random in fresh temporal SVAR
families, and the governed/C7 controls are intact. The gate fails because the absolute temporal
structure identification rate is only 0.500. The stronger blind reference does not exceed ACTIVE,
which means the current verifier/arena/minimality convention is still the bottleneck, not merely the
chooser. Do not lower the bar, reuse calibration families, rerun with rescued seeds, or promote this
as a temporal-dynamics win.

Next legitimate work: diagnose the failure mode on fresh-family strata, then either design a new
temporal verifier/arena gate with a new preregistration or move to the next queued lane (`5e-2`). This
result does not reopen passive discovery or authorize any product/autonomy claim.
