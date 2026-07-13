# LH-RECOVERY-1 Parent Gate — BLOCKED, Not This Slice

**Status:** `OPEN/BLOCKED`; `NOT_PREREGISTERED_NOT_FROZEN_NOT_RUN`.

The Product-grounded experiment matrix defines `LH-RECOVERY-1` as **durable hierarchical
execution with bounded replanning** over held-out task streams. The currently implemented
Product runtime exposes a narrower mechanism: one explicit Principal-authorized workflow
rebind that preserves already completed nodes. It does not implement automatic/hierarchical
planning and therefore cannot be evaluated under the parent ID without overclaiming.

The original plan at this path is withdrawn for three falsification reasons:

1. candidate and fixed suffixes were forced to be semantically identical, making the positive
   effect gate unreachable except through leakage or defects;
2. its `signal -> replan` sequence was not executable against the live state machine;
3. corpus generation, baseline blindness, C7 priority, expiry, approval freshness, and
   prospective power were not mechanically closed.

The admissible next slice is the separate child gate:

- [`2026-07-12-lh-recovery-1a-explicit-rebind.md`](2026-07-12-lh-recovery-1a-explicit-rebind.md)

`LH-RECOVERY-1A-EXPLICIT-REBIND` is a prerequisite/component falsifier only. Its `MET`,
`NOT_MET`, `INVALID`, or `PARK` outcome must not change this parent gate to passed. Opening the
parent later requires a new founder/CTO design for a real hierarchical candidate and a fresh
preregistration against the experiment matrix.

