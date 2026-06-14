# ADR-0027: Post-C3 route disposition - consolidate G10, park G11/C1 until a second winning axis exists

- Status: **Accepted (founder-delegated CTO ruling, 2026-06-14).**
- Date: 2026-06-14
- Deciders: founder-delegated CTO in the current coordination thread.
- Scope: P6 route-C governance after ADR-0024/G10 and ADR-0026/C3. Docs-only route decision; no mechanism change.
- Predecessors: ADR-0024 (G10 MET), ADR-0025 (route-C/G11 accepted but not frozen), ADR-0026 (C3 RED).

## 1. Context

G10 confirmed the first decisive positive result in the program: `P0 = confidence-gated policy + no organ` beat the cheap reset on fresh seeds 800..829 by 40.1%, 30/30 seeds, with bootstrap 95% CI [457.0, 562.9]. The mechanism is subject-side and C6-preserving.

C3 then tested whether the proposed endogeny axis could carry a directed signal. It returned RED: DIRECTED, RANDOM, and POLICY idle behavior were statistically indistinguishable, with DIRECTED marginally worse than RANDOM. Per ADR-0026, the endogeny axis must be dropped from C1.

The proposed G11/C1 system-level gate depended on a multi-axis signature:

```text
reframe / survival / robustness / endogeny
```

After C3:

| axis | state |
|---|---|
| reframe | confirmed vs cheap baseline by G10 |
| survival | claim-1 ablation supported, but not a head-to-head cheap-baseline win |
| robustness | RAP/G4 NOT MET |
| endogeny | C3 RED, dropped |

So the original C1 would collapse into "G10 plus weaker side metrics", not a genuine multi-axis autonomy signature.

## 2. Decision

Do **not** freeze G11 or build the C1 composite-demand environment now.

Treat G10 as the current confirmed positive result and the cleanest research contribution:

```text
subject-side belief-to-action coupling can decisively beat cheap reset while preserving C6/C7
```

Park G11/C1 until a second independent axis has a preregistered, vs-cheap-baseline win. The original route-C altitude move remains conceptually accepted, but it is not executable as a gate after C3 RED.

## 3. What Is Not Being Decided

- This is **not** a final failure ruling on the four-claim program.
- This does **not** reopen claim-2 relevance mechanisms, IdleDrives, RAP, or G7/G8 organ tuning.
- This does **not** relax C6 or put organs in the control path.
- This does **not** authorize LLM spend or live LLM control-path work.

## 4. Next Work

Near-term work should consolidate rather than build a weak C1:

1. Update handoff docs so every agent starts from "G10 MET, C3 RED, G11 parked".
2. Record G10 as the confirmed positive subject-side mechanism and C3 as the reason endogeny is dropped.
3. If the project wants another system-level gate, first design a new independent demand axis under a new ADR with MDE/power and a cheap-baseline win criterion.
4. P5 deployment projection may proceed in parallel because it harvests validated claims 1/3/4 and now the G10 subject-side coupling result; it must still obey its own enterprise ADR boundary.

## 5. Consequences

- G11/C1 is no longer the immediate next implementation task.
- The immediate next state is documentation consolidation and, after a clean handoff, either P5 projection or a new-axis ADR.
- Negative results remain first-class: C3 RED is not patched or rerun.
- The branch should be kept clean before merge/push coordination.
