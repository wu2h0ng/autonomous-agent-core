# ADR-0011: Live closed active-experimentation loop (S8)

- Status: Proposed on feature branch `codex/s8-live-closed-active-experimentation-loop-20260705`.
  Not merged to origin, not pushed, not released.
- Cross-repo authorization: workspace RR-0048 phase-gate Option 2, behind the standing `origin/main` HOLD.
  No import of `autonomous-agent-core` (#19).
- Builds on: S7 (ADR-0010, self-generated experiments), S5 (causal selection), S4 (outcome learning).

## Context

S7 proved the self-generation *mechanism*, but its resolved-ledger was a hand-set simulation, so the
learn→re-propose loop was a mechanism, not a live closed loop. Closing it for real — the system's
self-generated experiments driven by its OWN accumulated result, end to end — is in-bounds and is the honest
next step toward the goal's "从反馈学习并复利那份知识" (learn from feedback and compound it).

## Decision

Add `agent_os_core.experimentation` with two small components:

- **`ExperimentLedger`** — a real store of the drivers the system has interventionally RESOLVED (causal
  effect determined). `UncertaintyDrivenProposer` reads `ledger.resolved` (no simulated set), so resolved
  drivers stop being re-proposed.
- **`ActiveExperimentationLoop`** — `run_round()` runs the governed loop with the self-generating proposer,
  then records the driver the governed disposer **confirmed** (`verdict == ALLOW` + `chosen_action`) back
  into the ledger. The next round's self-generated experiments are therefore driven by the system's own real
  accumulated result. The closed cycle, live: propose (自主) → govern-causally-select (强) → record confirmed
  driver (learn / 复利) → re-propose from the updated ledger.

## Scope / non-goals — honest bounds

- **Governance unchanged and supreme.** `runtime.run` still enforces the C7 pause (a paused run raises before
  any result — nothing is recorded) and the tighten-only seam; R4/R5 stay proposal-only; human approval is
  unchanged. The orchestrator only *records what the disposer confirmed*, never a self-declared outcome.
- **Anti-wirehead.** The `ExperimentLedger` drives experiment PRIORITIZATION only. It does not promote
  knowledge or mint realized value (that stays the S4 operator-attested adoption path), so a gamed entry can
  at worst change which experiment is proposed next — never value or knowledge. It records only drivers the
  interventional verifier confirmed (ALLOW), not self-reports.
- **Not open-world discovery.** Still a KNOWN, domain-supplied driver-space; the loop prioritizes within it.
  It does not discover the driver-space or hypothesize novel causal structure — that is the object-layer
  capability, reachable only through a founder-gated seam extension.
- **Single-step, single-domain, binary resolved signal.** Multi-step experiment design, an information-gain
  uncertainty policy, and cross-domain operation are not claimed.

## Consequences

- Positive: the propose→act→learn→re-propose cycle is now **live and closed** over real stores in one
  domain — a real milestone shape ("在一个领域做到是里程碑"): the system chooses its own experiments from its
  own accumulated interventional evidence, governed and corrigible. Combined with S1–S7, all four
  commitments now have an in-bounds foothold in one running, governed loop.
- Cost: two small OS Core components; the honest bounds above must travel with any claim. This is a milestone
  in a single domain, explicitly not the arbitrary-domain, open-world-discovery goal.

## Tests (would fail if the loop were not live/closed or bypassed governance)

- `tests/integration/test_s8_live_closed_active_experimentation_loop.py`: round 2's self-generated
  experiments shift from round 1's REAL recorded outcome (no hand-set state); the loop records only
  interventionally-confirmed drivers (all-lures → empty ledger); a paused C7 halts a live round and records
  nothing.
