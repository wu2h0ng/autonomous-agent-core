# ADR-0010: Uncertainty-driven self-generated experiments (S7)

- Status: Proposed on feature branch `codex/s7-uncertainty-driven-self-generated-experiments-20260705`.
  Not merged to origin, not pushed, not released.
- Cross-repo authorization: workspace RR-0048 phase-gate Option 2. Taken **within** the deployment layer,
  behind the standing `origin/main` push HOLD, to build a bounded, in-bounds slice of the goal's **自主**
  commitment ("它...决定性地选择自己的实验" — it deterministically chooses its own experiments).
- No import of `autonomous-agent-core` (#19).

## Context

Across S5–S6 the governed loop could *select* causally among candidate interventions, but the candidates
were **enumerated** (supplied per run). The 自主 commitment requires the system to **self-determine which
experiments to run**. The full form — discovering the causal structure / the driver-space itself under a
world model — is the object-layer capability (RR-0046/AGDE) and reaches the OS only through a founder-gated
seam extension. But a **bounded** slice is in-bounds: choose *which* experiment to run next from the
system's own record of what it has and has not yet determined.

## Decision

Add `UncertaintyDrivenProposer` (in `agent_os_core.action_proposal`), an **injectable, opt-in** proposer:

- **Input:** a domain-supplied `driver_space` (the known candidate interventions) and a `resolved_provider`
  (the drivers whose causal effect the system has already determined via recorded interventional outcomes —
  the S4 outcome/knowledge ledger).
- **Behavior:** it emits the **unresolved** drivers as the candidate experiments (`candidate_actions`) — the
  interventions worth running to reduce uncertainty. As outcomes accumulate the resolved set grows and the
  proposed experiment set **shifts**: the system chooses different experiments because its uncertainty
  changed. It never emits an empty set (re-offers the full space when all are resolved).
- The governed disposer then **selects causally** among these candidates (S5, the seam), a human still
  **approves**, and **C7** can still stop the run. Default runtime behavior is unchanged (the standard
  `ActionProposalBuilder` remains the default; this proposer is injected only when a caller opts in).

## Scope / non-goals — honest bounds

- **Bounded autonomy, not autonomy over the gate.** The system proposes its own experiments; it does not
  execute without human approval and cannot seize the correction channel. C7 stays immutable/unmodelable;
  the disposer only tightens; R4/R5 stay proposal-only; `origin/main`/release stay HOLD. This is the
  *designed* governed-autonomy (器官选择实验,人可纠可停), explicitly **not** SD4.
- **Not open-world discovery.** It prioritizes *within* a given `driver_space` by heuristic uncertainty
  (resolved vs unresolved). It does **not** discover the driver-space or hypothesize novel causal structure
  — that is the object-layer capability, reachable only through the seam.
- **Heuristic uncertainty.** "Resolved" is a binary ledger signal; a staleness / information-gain / re-test
  policy is a deliberate future refinement, not claimed here.
- **Single-step.** One experiment proposed/selected per run; multi-step experiment design is not claimed.

## Consequences

- Positive: the loop can now **self-generate its own experiments** from its own accumulated uncertainty and
  govern-select causally among them, human-approved and corrigible — the 自主 axis has a real, bounded,
  in-bounds foothold *inside the governed loop*, not just in a research branch. Combined with S4 (learn from
  outcomes) and S5 (causal selection), the loop approximates propose-experiment → govern → act → learn →
  re-propose, within one domain.
- Cost: a new opt-in OS Core proposer to maintain; the honest bounds above must travel with any claim.

## Tests (would fail if self-generation were faked)

- `tests/integration/test_s7_uncertainty_driven_self_generated_experiments.py`: the self-generated
  experiment set shifts as the system learns (a resolved driver drops from round 2's candidates); the
  disposer selects the causal driver among the self-generated set and ESCALATEs when only lures remain;
  all-resolved falls back to the full space (never empty); a paused shell halts a self-generated run (C7).
