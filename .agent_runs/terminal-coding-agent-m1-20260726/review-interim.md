# Interim Fresh-Eyes Review — terminal coding agent M1 (ceeb761)

> Reviewer: Kimi fresh-eyes subagent (NON-INDEPENDENT interim, same model family as implementer)
> Date: 2026-07-30
> Scope: `git diff 527695d..ceeb761` on `feature/terminal-coding-agent-m1`
> Commit 527695d (pre-existing coordinator-decomposition WIP import): alert-level only.
> Task packet: `docs/product/GC-TERMINAL-CODING-AGENT-M0-M1-2026-07-26.md`,
> `docs/architecture/T-P-CORE-TERMINAL-CODING-AGENT-ARCHITECTURE.md`,
> `.agent_runs/terminal-coding-agent-m1-20260726/{implementation-log,verification}.md`
> Verification performed by this reviewer: re-ran
> `.venv/bin/pytest -q tests/product/test_terminal_chat_loop.py` → **21 passed in 4.18s**
> (matches the claimed result). Full Product suite not re-run; the claimed
> 1606-passed/18-failed baseline is taken as reported.

## Findings (by severity)

### HIGH

None found. No execution path was located where a model-proposed capability runs
without `PolicyKernel.decide` → exact `ActionPermit` → correction-epoch validation.
`_execute_proposal` (agent_loop.py:420-479) always routes through
`ActionPipeline.execute` (action_pipeline.py:84-175), which calls `policy.decide`,
records `POLICY_DECIDED`, mints the permit, checks lease fence and invokes the broker;
`WorkspaceSandbox.invoke` re-validates permit match, expiry and epoch drift. The model
only ever produces `ProviderToolProposal`; `CHAT_CAPABILITY_IDS` whitelists the
dispatch surface. C7 is not bypassed in the reviewed diff.

### MEDIUM

1. **Risk tier is caller-declared; the kernel never floors it against the capability
   spec.** `PolicyKernel.decide` (governance.py:230-245) checks
   `action.risk_tier > grant.max_risk_tier` and `>= 3 → approval`, but never
   `action.risk_tier < capability_spec.risk_tier`. The tier attached to an
   `ActionContract` comes from the loop-local `ACTION_RISK_TIERS` dict
   (agent_loop.py:52-61, 440). Today the dict is static and correct, so the model
   cannot influence it — but the *enforcement point* is the caller, not the kernel.
   Any future caller (or a dict edit, e.g. a new capability defaulting to tier 1 via
   `ACTION_RISK_TIERS.get(capability_id, 1)`) silently gets tier-3 shell execution
   with no `ApprovalDecision`, because the grant ceiling (now 3) admits tier 1.
   Defense-in-depth fix is small: deny when
   `action.risk_tier < context.capability.risk_tier`.

2. **Dangling ASSISTANT `tool_calls` poison the session after `unauthorized_proposal`
   / `loop_detected` stops.** In `_drive` (agent_loop.py:262-311) the ASSISTANT message
   echoing *all* proposals is appended before the per-proposal loop; on
   `unauthorized_proposal` the loop breaks before any TOOL message, and on
   `loop_detected` it breaks after the triggering proposal, leaving the remaining
   proposals of that response without TOOL replies. The next `run_turn` in the same
   REPL sends this history to a real OpenAI-compatible provider, which rejects
   assistant `tool_calls` not followed by matching `tool` messages (HTTP 400) — the
   live session is unrecoverable after either stop. DeterministicProvider never
   notices, so all 21 tests stay green. Fix: append error TOOL messages for every
   skipped proposal (or drop the dangling ASSISTANT message) before breaking.

3. **`chat -p` has no Ctrl-C handling → unrecorded kill.** `apps/cli/__main__.py`
   `_chat`: the interactive path wraps both `input()` and `loop.run_turn` in
   `KeyboardInterrupt` handlers that call `app.correct_task` (recording
   `CORRECTION_WRITTEN`); the `-p` path calls `loop.run_turn` bare. Goal Card
   authority condition: "Ctrl-C maps to a correction halt through the existing
   correction authority, never to an out-of-band process kill that skips the event
   record." The non-interactive path violates it.

4. **Approval denial is not recorded as a durable event (spec §8 deviation).**
   When the gateway returns `False` (agent_loop.py:459-463) the loop returns a TOOL
   error message (in-memory only) after `record_action_proposed`. The event stream
   then contains an `ACTION_PROPOSED` with no corresponding denial, decision or
   receipt — an auditor cannot distinguish "user rejected" from "never dispatched".
   Architecture Brief §8: "approval declined (`n`): proposal recorded as *denied*".
   Record a denial event (or a decided/denied marker) before returning.

5. **`_build_grants` elevation is application-wide, not chat-scoped**
   (apps/api_server/app.py:437-459). `max_risk_tier` changed from hardcoded `1` to
   `spec.risk_tier` for *all* grants, so the static WorkflowGraph path's policy
   envelope changed too: a graph action on `workspace.apply_patch`/`workspace.edit`
   declared at tier 2 previously died with `RISK_TIER_EXCEEDED` and is now `ALLOW`ed
   with no approval surface anywhere (the kernel only demands approval at tier ≥ 3;
   the terminal confirmation gateway exists only inside the chat loop). No existing
   test broke (full suite reportedly red only on pre-existing baseline), so this is a
   silent relaxation rather than a regression — but the Goal Card scopes the change to
   the chat slice, and `open_chat_session` already builds a scoped `chat_grants`
   subset that could have carried elevated tiers instead of mutating the shared
   envelope. Needs either a scoped fix or an explicit spec amendment + a golden-path
   test pinning the new tier-2 behavior.

6. **Stop conditions and context trimming lack tests.** Goal Card done-condition 4
   lists turn cap, token budget and retryable-failure exhaustion; only loop detection
   is tested. Untested: `budget_exceeded`, `max_steps`, provider retry exhaustion,
   `_trimmed_history` truncation (including its ASSISTANT/TOOL block-atomicity
   invariant, which finding 2 shows is fragile). Also untested: kernel-level
   `APPROVAL_REQUIRED` escalation when a tier-3 action arrives without an approval
   (only gateway-level denial is tested).

### LOW

7. **`AutoApproveGateway` is exported from the package root** (agent_loop.py:95-101,
   `agent_os_core/__init__.py`) and auto-approves tier ≤ 2 writes with no human. Its
   docstring says "for `-p` runs and hermetic tests", but `-p` actually uses
   `NonInteractiveDenyGateway` — the doc is wrong and the export invites production
   misuse. Move to test support or rename/document as test-only.

8. **`workspace.run_tests` executes arbitrary workspace code at tier 1 auto-pass.**
   pytest imports `conftest.py` and test modules — full code execution. This is
   pre-existing tiering, but chat makes it one model proposal away, and the
   "read/search-class = READ_ONLY auto-pass" framing (Architecture Brief §1 decision
   3) understates it: run_tests is not read-only in any meaningful sense. Combined
   with one approved edit, the model gains arbitrary code execution without ever
   hitting the tier-3 approval path. Acceptable for a local coding agent, but should
   be acknowledged in the boundary text (the CURRENT_STATE boundary currently
   stresses shell's allowlist, not this).

9. **Model-controlled regex in `workspace.search` grep has no timeout**
   (capability.py `_search`): a catastrophic-backtracking pattern hangs the REPL
   (self-DoS only, local threat model).

10. **TOCTOU in `_safe_path`** (capability.py:307-324): symlink check → `resolve()` →
    later open/write are not atomic. Local single-operator threat model makes this a
    note, not a blocker.

11. **Idempotency dedup is structurally disabled for chat actions.** Chat node ids
    embed a fresh `turn-{uuid}` (agent_loop.py:447-449), so
    `idempotency_key = run_id:node_id` never repeats and the idempotency store /
    `_validate_cached_patch_effect` replay path never engages. Deliberate per the log,
    but worth stating in the boundary text.

12. **`total_tokens` double-counts context**: summing per-call `usage.total_tokens`
    re-counts the whole conversation each step, so `max_turn_tokens` trips early.
    Conservative direction; fine for M1, note for M2 cost display.

13. **`workspace.search` glob mode ignores the `path` argument** (always walks from
    `self.root`), while grep/ls honor it — minor contract inconsistency.

14. **`.env.example` rewrite drops `OPENAI_API_URL` / `ANTHROPIC_API_URL`**
    documentation, but `src/aac/llm_client.py:49` and
    `src/aac/llm_weight_organ.py:73` still read those variables (research harness).
    Unrelated churn with a minor doc regression; the harness has defaults, so no
    break.

15. **Live-provider verification claim lacks a durable artifact.** The worktree
    (uncommitted) `docs/CURRENT_STATE.yaml` update claims
    `LIVE_PROVIDER_TASK_VERIFIED_2026_07_30` with a narrative, but
    `.agent_runs/terminal-coding-agent-m1-20260726/` contains only the 2026-07-26
    implementation-log and verification files — no transcript, event dump or dated
    live-run record. Per evidence discipline, the claim needs a dated evidence
    pointer; as committed, the repo only supports `STUB_PROVIDER_E2E`.

### Alert-level (527695d WIP import, not this task's code)

- The branch contains a large imported WIP baseline and the worktree still carries
  unrelated dirty/untracked files (`docs/architecture/*SRL*`, `experiments/*`,
  `research/`, `ruff.toml`, etc.). This review did not audit 527695d content; the
  claimed 18-failure full-suite baseline is attributed to it and to clock expiry, and
  was not independently reproduced here beyond the targeted suite.

## Open questions

1. Was the app-wide grant elevation (finding 5) an intentional golden-path change? Is
   there any committed workflow or test that declares a tier-2 `apply_patch` node and
   now silently passes where it was previously denied?
2. Where is the recorded evidence for the 2026-07-30 live-provider run (transcript /
   event-stream dump)? If it exists, it should be committed under `.agent_runs/`.
3. Per-capability failure-path tests: Goal Card done-condition 3 asks each new
   capability to have failure paths for illegal path, expired permit and epoch drift.
   Only illegal-path is tested per capability; expired-permit/epoch-drift rely on
   pre-existing shared broker tests. Is that accepted as satisfying the condition?
4. `workspace.run_tests` tier-1 classification (finding 8): accepted design, or
   should chat map it to tier 2 like edits?

## Required changes (before independent review / any merge request)

1. Fix the dangling-`tool_calls` history poisoning (finding 2) and add a test that
   runs a further turn after `unauthorized_proposal` and `loop_detected` stops.
2. Add Ctrl-C → `correct_task` handling on the `chat -p` path (finding 3).
3. Record approval denials as durable events (finding 4).
4. Either scope the grant-tier elevation to chat grants or document the intentional
   golden-path change + pin it with a test (finding 5).
5. Add a kernel-side risk-tier floor check (`action.risk_tier >= spec.risk_tier`) or
   a recorded ADR-style note declining it (finding 1).
6. Add tests for `budget_exceeded`, `max_steps`, retry exhaustion and
   `_trimmed_history` (finding 6); fix or remove the misleading `AutoApproveGateway`
   docstring (finding 7).
7. Attach dated live-provider evidence to the run directory or drop the
   `LIVE_PROVIDER_TASK_VERIFIED` status from CURRENT_STATE (finding 15).

## Verdict

**APPROVE_WITH_REQUIRED_CHANGES** — the governance spine (decide/permit/epoch/broker)
is genuinely unbypassed and the targeted suite is real and green, but findings 2-5 are
concrete correctness/spec/audit defects (one of them live-provider-breaking) that must
be fixed before this slice can claim `IMPLEMENTED_LOCAL` cleanly or face the formal
independent review.
