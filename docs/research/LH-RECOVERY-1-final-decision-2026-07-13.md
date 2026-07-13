# LH-RECOVERY-1 Chain Decision — 2026-07-13

Decision: **OPEN_BLOCKED_NOT_RUN — SPINE prerequisite now PASS; child D1/D2 and parent gates remain open**

The original chain stopped after the frozen prerequisites returned INVALID. A founder-authorized
fresh successor, `SPINE-E2E-4`, has now completed one frozen run with a verified bounded PASS.
That successor clears only the SPINE prerequisite for the child route.

Therefore:

- SPINE prerequisite PASS is present at `docs/research/SPINE-E2E-4-result.md`;
- LH-RECOVERY-1A D2 remains unconstructed because D1-E, D1-F, combined D1, nonce
  commitments/reveals, corpus materialization, and the one-shot `432/432` oracle prerequisite
  are absent;
- D1 artifact construction is the next admissible child action under the existing plan boundary;
- parent LH-RECOVERY-1 remains open/blocked, not preregistered, not frozen, and not run;
- no long-horizon advantage, autonomy, continual-learning, self-evolution, or AGI claim follows.

This decision supersedes the earlier prerequisite-absent reason but not the parent boundary.
Even a future `LH-RECOVERY-1A` child result cannot mark the parent passed. Opening the parent
requires a new founder/CTO design and preregistration for a real hierarchical candidate against
the strong baselines in the Product-grounded experiment matrix.
