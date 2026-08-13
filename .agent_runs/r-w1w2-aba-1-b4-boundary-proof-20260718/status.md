# R-W1W2-ABA-1 B4 Boundary Proof Status

Current state:

- Agent OS main: `c1e159e6f95250bcfa3b50d8ab0e8ed652fa36b5`.
- Public scaffold: independently approved at exact code head
  `24280fc46879a2b4a4f9884af6bf10fb179406e7`.
- B1-B5 external closure audit: `CONTINUE_EXTERNAL_CLOSURE`, but only via
  time-boxed B4 independent custody boundary proof first.
- Experiment: `EXPERIMENT_IMPLEMENTATION_DENIED / PREREG_REVISE /
  NOT_IMPLEMENTATION_READY / NOT_FROZEN / NOT_RUN`.

Known blockers:

- B4 has no accepted independent scorer/freezer principal.
- B2 has no prospective candidate-blind frame.
- B3 and B5 are explicitly parked until B2 and B4 are accepted.
- Same-principal local services, local Docker/Colima, local HMAC/SQLite and
  ordinary CI are not accepted as independent custody.

Relevant public files:

- `docs/CURRENT_STATE.yaml`
- `.agent_runs/r-w1w2-aba-1-stage1-implementation-20260718/preregistration_candidate.md`
- `.agent_runs/r-w1w2-aba-1-stage1-implementation-20260718/b1b5_external_closure_audit.md`
- `.agent_runs/r-w1w2-aba-1-stage1-implementation-20260718/implementation_final_review.md`
- `src/aac/r_w1w2_aba`
- `tests/research/r_w1w2_aba`
