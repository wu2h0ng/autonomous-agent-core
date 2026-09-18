# Form B child agents: the four bounds the kernel actually enforces

- Date: 2026-09-19
- Scope: implementation-side statement for `agent.spawn` (ADR-0061), branch
  `feat/agent-spawn-kernel-20260919`, stacked on the frozen contract layer
  (PR #96).
- Why this file exists: the adversarial C6/C7 preservation review required the
  **ADR** to state four things explicitly instead of leaving them blank. The ADR
  text lives on a parallel branch (`docs/adr/ADR-0061-subagent-fanout-and-child-agent-boundary-2026-09-19.md`,
  worktree `wt-adr61`) that this slice does not own. These are those four
  statements, written against the code that implements them, so they can be
  folded into the ADR verbatim.
- Claim levels: `specified: yes` / `implemented: yes` / `tested: yes`
  (see `tests/product/test_agent_spawn_kernel.py`,
  `tests/product/test_agent_spawn_daemon_e2e.py`) / `integrated: yes` (the
  capability is dispatched through `CapabilityBroker.invoke` like every other
  one) / `verified: only as recorded by the two suites above` / `released: NO`.

## 1. `N` bounds per-parent-turn concurrency, not total tree size

`AGENT_OS_MAX_CHILD_AGENTS` (default 4, `ChildAgentFanOutConfig.from_env`)
bounds the children **in flight for one parent turn**
(`child_agent.enforce_child_agent_fan_out` → `enforce_child_agent_limit`).
It does **not** bound the tree, the total number of children, total tokens,
total cost, or wall-clock time. A depth-`d` tree with fan-out `N` holds
`N ** d` children while no single layer exceeds `N`.

In flight means "not ended": no `CHILD_AGENT_FINISHED` record yet, or a finish
record whose child session still owns an open turn (the operator-visible
parking case), unless an operator has declared the child reconciled. The count
is recomputed from durable events on every spawn attempt, so a restart cannot
reset it (the review's E1/G5).

Nesting is bounded separately by `MAX_CHILD_AGENT_ANCESTOR_DEPTH` (8), enforced
before a child is created, and nested spawn is off unless the composition root
enables it (`AGENT_OS_NESTED_CHILD_AGENTS`, default off).

## 2. "The parent's remaining budget" does not exist yet

There is no consumption ledger anywhere in this spine: `CapabilityGrant.budget_limit`
is a **static** ceiling and the only budget check is a single action's
`estimated_budget` against it (`PolicyKernel.decide`). So the
`parent_remaining_budget` argument `derive_child_grants` receives is the
parent's **static grant ceiling** (`_static_grant_ceiling` in
`apps/api_server/app.py`), and what the change really enforces is the
non-widening property: every child grant is a copy of its parent grant with the
same capability/version/identity, `max_risk_tier(child) <= max_risk_tier(parent)`,
`budget_limit(child) <= budget_limit(parent)`, and `expires_at(child) <=
expires_at(parent)`, validated by the frozen contract function.

**No call site, document or operator surface may claim a cross-session total
budget, or that a child's spend is deducted from a parent budget.** Nothing
does today and nothing here measures it.

## 3. A synchronous spawn has a wall-clock bound because this change adds one

A spawn is a synchronous capability effect: the child's turn runs on the
parent's thread inside the parent turn. Without a bound, the parent's turn would
inherit the child's whole duration (the review's E5). This change adds one:

- `AGENT_OS_CHILD_AGENT_TIMEOUT_SECONDS` (default
  `DEFAULT_CHILD_AGENT_TIMEOUT_SECONDS` = 300) is bound on the child loop as a
  runtime-only deadline (`AgentLoop.set_wall_clock_deadline`);
- the loop checks it at every **step boundary** and stops the child turn itself
  with `stop_reason="wall_clock_exceeded"`, which the spawn reports as
  `status=timeout, stop_reason=child_wall_clock_exceeded`;
- it is a bound on the **child**, not an abandoned worker, and it is not a
  preemption: a single hung provider call is bounded by the provider's own
  request timeout, not by this deadline.

Two consequences that must be written down rather than discovered:

1. The child runs on the parent's thread **on purpose**. The broker's C7
   linearization (`guard_unchanged`) holds the correction authority's lock for
   the duration of an effect, so driving the child on a worker thread deadlocks
   against the parent's own guard (reproduced while building this slice). The
   cost is that an operator's correction issued from another thread waits behind
   a running child, bounded by the deadline above.
2. The parent's execution lease/permit is not re-validated when a long child
   finishes: the broker checks the permit before dispatch, not at seal. That is
   pre-existing behaviour, not something this slice changes, and it is why the
   wall-clock bound exists.

## 4. Digest-only is a narrow rule about the child-agent records

`CHILD_AGENT_SPAWNED`, `CHILD_AGENT_FINISHED` and `CHILD_AGENT_RECONCILED` carry
`prompt_digest` / `summary_digest` and never prompt or completion text, and the
attribution projection (`SurfaceChildAgentsResponse`) copies no child text.

That is all the rule covers. **A child is an ordinary session**: its first user
message is the spawn prompt and its final assistant text is recorded in
`SESSION_MESSAGE_RECORDED` on the child's own task stream, exactly as any
session's messages are. The child's bounded final text also comes back to the
parent as the tool result of `agent.spawn`, which is recorded in the parent's
message stream like any other tool result.

So: **no claim of the form "spawning does not record the prompt" is permitted.**
The rule is about three event types and one projection, and the tests assert
exactly that (`test_attribution_includes_children_without_copying_their_text`).

## Related statements that follow from the same review

- **C7 cascade** (requirement 1): a child's halt check consults its durable
  ancestor chain (`ChildAgentHaltCascade`), read-side only, restart-safe,
  depth-bounded (8, fail-closed on overflow or cycle), and never a writer and
  never a second authority - `snapshot` still delegates, so permits and
  correction receipts keep binding the child's own keys.
- **Burial** (requirement 2): a child whose owning runtime generation is gone is
  closed by an **operator declaration** with `status=failed`,
  `stop_reason=unknown_requires_review` and a `CHILD_AGENT_RECONCILED` block
  naming `CHILD_RUNTIME_GENERATION_GONE`, the declaring operator and the live
  generation. Never `completed`. The frozen `ChildAgentStatus` enum has no
  `unknown` member, so "unknown" is carried by the stop reason and the
  reconciliation block; extending the enum is a contract decision this slice
  does not take.
- **Nested approval** (requirement 4): a child that needs a tier>=3 approval
  parks on its own session's durable pending approval (the operator-visible
  card) and the spawn returns `status=stopped, stop_reason=awaiting_approval`
  inside the wall-clock bound. Nothing is auto-approved.
- **`stopped` is not "no side effects"**: it means the child dispatches no new
  effects; effects already dispatched follow the existing receipt/compensation
  semantics (`C7-BOUNDARY-STATEMENT.md`).
