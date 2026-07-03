# P6 No-Gate-2 Hold Brief (2026-07-03)

- Status: decision brief / no authorization
- Layer: object / mechanism evidence
- Branch inspected: `research/causal-world-model-2026-06-30`
- Decision authority: founder/CTO for any Gate-2 unlock, new ADR, freeze, or
  r-final

## Conclusion

Current research state does not justify a Gate-2 unlock.

The correct current posture is:

```text
Gate-2 status: HOLD
route status: Direction 1 remains pre-ADR/pre-build
claim ceiling: tracked exploratory artifact only
recommended decision: keep No Gate-2 unless founder/CTO explicitly authorizes a new cheap falsifier definition or a new ADR
```

## Facts

1. `VH/G-Eco` is not an active unlock candidate.
   - Current authoritative state is `PARK_BY_§7A_C_NOT_SUPPORTED` after the
     2026-06-27 pre-Gate-2 halt.
   - No Gate-2, r-final, verdict, ADR-0037 closure, reseed, retune, or rescue
     is authorized from that line.

2. `Direction 1` is the only live Track R next action.
   - It is still pre-ADR and pre-build.
   - The tracked 30-seed run-local cheap falsifier over seeds `2400..2429`
     returned `NO_NEW_DIRECTION_1_MECHANISM`.
   - FAST and SLOW share the same best gated arm (`K025`), so the artifact does
     not open a fresh mechanism axis.

3. There is no current research completion bar.
   - `docs/CURRENT_STATE.yaml` still authoritatively says:
     - `No Gate-2`
     - no `r-final`
     - no verdict
     - no autonomy claim
     - no product claim

4. There is a separate truth-hygiene issue that must not be conflated with
   Gate-2.
   - Working tree still shows:
     - `M experiments/prediction1_residual_calibrator.result.json`
   - This is a separate documentation/adjudication drift problem for ADR-0031.
     It is not evidence for reopening Gate-2.

## What Would Actually Change The State

Only one of the following can legitimately change the current `No Gate-2`
status:

1. A new founder/CTO-authorized cheap falsifier definition that is explicitly
   different from the already tracked Direction 1 null result.
2. A new founder-level ADR that authorizes a different mechanism route.
3. A founder/CTO decision to reopen a previously parked route with fresh seeds
   and fresh freeze discipline.

What cannot change the state:

- rereading the same Direction 1 artifact;
- reinterpretation of the same 30-seed null result;
- rescue language around VH/G-Eco;
- product-layer progress;
- workflow-layer governance progress.

## Recommended Next Decision

The narrowest honest next decision is:

```text
HOLD No Gate-2.
Do not unlock freeze/r-final.
Require any next research move to enter as a new cheap falsifier definition or a new founder-level ADR.
```

## Why This Matters

Without this hold line, the program will tend to convert:

- partial mechanism scaffolds,
- historical harness work,
- or unrelated product/governance progress

into implied research advancement. That is exactly the drift this project is
trying to prevent.
