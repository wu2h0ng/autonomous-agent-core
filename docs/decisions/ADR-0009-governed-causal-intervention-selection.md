# ADR-0009: Governed causal intervention-selection in the loop (S5)

- Status: Proposed on feature branch `codex/s5-governed-causal-intervention-selection-20260705`.
  Not merged to origin, not pushed, not released.
- Cross-repo authorization: workspace RR-0048 phase-gate Option 2. This slice was taken **within** the
  deployment layer to build the goal's *named core capability* — "选择运行哪个干预" (choosing which
  intervention to run) — into the OS governed loop, behind the standing `origin/main` push HOLD.
- No import of `autonomous-agent-core` (#19); uses the existing seam contract (ADR-0004) unchanged.

## Context

The ultimate objective states that the capability that matters — open-world causal discovery — lives in the
**governed action loop itself**, in *choosing which intervention to run*, and that this choice must be
**causal** (强): pick the intervention that moves the metric *under intervention*, not the one that merely
correlates ("在分布漂移、相关性说谎时依然正确"). Until now the OS loop proposed **one** action and the
governed-decision seam only *verified* that one. The seam **contract** already supports multi-candidate
selection (`candidate_actions` → `chosen_action`), but the runtime never exercised it.

## Decision

Let the proposer enumerate **multiple candidate interventions** and have the deterministic, contentless
governed disposer **select** among them by real interventional (cohort A/B) evidence:

1. **Contract (minimal, backward-compatible).** Add `ActionProposal.candidate_actions: tuple[str, ...] = ()`.
   Empty (the default) preserves exact single-recommendation behavior.
2. **Runtime.** At the proposal-time seam consult, send `proposal.candidate_actions or (recommended_action,)`.
   The disposer returns the causally-`chosen_action`, which is now recorded in the `governed_decision` audit
   trace event (`chosen_action`, `None` when nothing was verified-effective).
3. The disposer still only **tightens** (DENY/ESCALATE/VERIFY_MORE); the human Approval gate and the C7
   corrigibility pause are unchanged and take precedence (a paused shell still halts the run).

## Scope / non-goals — honest bounds

- **Enumerated, not self-generated.** The candidate interventions are supplied by the proposer/domain, not
  open-world self-generated. This is governed selection among a given set, **not** open-world causal
  discovery (that lives in the object layer and reaches the OS only through the seam).
- **Selection surfaced, execution staged.** The disposer's `chosen_action` is computed and recorded in the
  trace. Wiring it to *redirect the executed operation* (execute the chosen candidate rather than the
  recommended action, which requires candidates to carry full connector/action_type/parameters) is a
  deliberately separate next slice.
- **Not autonomy over the gate.** Selecting an intervention is the *designed* governed-autonomy
  (确定性、无内容的处置面选择实验); it does not touch SD4, C7 immutability, R4/R5 (still proposal-only),
  or `origin/main`/release (still HOLD). No contract loosening; the seam can only tighten.
- **Single domain.** Exercised on the GMV metric; genuine 通用 (cross-domain without rebuild) is not claimed.

## Consequences

- Positive: the OS governed loop now carries the goal's named core capability — it can choose *which*
  intervention to run, and it does so **causally** (the interventional verifier rejects a correlational lure
  even when the lure is listed first), governed and auditable. This is 强 + governed selection integrated
  into the loop, honestly bounded.
- Cost: one optional contract field and a trace-schema addition (`chosen_action`); default behavior and all
  existing tests unchanged.

## Tests (would fail if selection were bypassed)

- `tests/integration/test_s5_governed_causal_intervention_selection.py`: the disposer selects the causal
  driver over a correlational lure (regardless of order); all-lures → ESCALATE (never auto-selects an
  unverified intervention); a paused shell still halts (C7 intact); the default no-candidates path is
  backward compatible.
