# Independent Review — terminal coding agent M1 (ceeb761 + c27fac1)

> Reviewer: fresh Kimi Code CLI session (independent process, zero shared context with implementer sessions)
> Date: 2026-08-06 (review executed); salvaged 2026-08-12
> Scope: `git diff 527695d..c27fac1` on `feature/terminal-coding-agent-m1`
> Process note: the review session exhausted its API quota moments before writing
> this file; the content below is salvaged verbatim from the session's recorded
> final analysis (it had completed first-hand verification, including re-running
> the targeted suite and spot-checking the live-run event dump, before cutoff).

## Verification performed by this reviewer

- Re-ran targeted suite independently: `tests/product/test_terminal_chat_loop.py`
  green (matches implementer claims); full-suite claim (1625 passed / 18 failed, all
  18 pre-existing) spot-checked via subagent and accepted.
- Spot-checked `live-verification-2026-07-30.events.json` first-hand: 24 events,
  internally consistent, code-consistent, no secrets, matches transcript — BUT all
  timestamps are 2026-08-06, not 2026-07-30 as labeled.

## Findings

### HIGH

None. Governance spine verified first-hand: every executed proposal goes
build_action -> record_action_proposed -> gateway (tier>=2) -> ActionPipeline.execute
-> policy.decide -> POLICY_DECIDED -> permit -> lease fence -> broker.invoke
(permit re-match, expiry, epoch). The model only produces ProviderToolProposal;
CHAT_CAPABILITY_IDS whitelists the dispatch surface; tiers come from a static host
dict; the kernel floors under-declared tiers. No bypass found. RC1-RC7 from the
interim review are genuinely closed (RC2 code-present-but-untested is the weakest).

### MEDIUM

1. **Live-evidence date mislabeling.** All events in the committed dump are
   timestamped 2026-08-06, while filenames/md/CURRENT_STATE say 2026-07-30, and the
   md "Notes" section describes the repeat run misleadingly. Evidence integrity
   matters constitutionally here. Required fix: redate artifacts + md + status string.
2. **RC2 (`chat -p` Ctrl-C) has no regression test.** Interactive path is tested;
   the -p path is not. Required: SIGINT test proving CORRECTION_WRITTEN + exit 130.
3. `workspace.run_tests` (tier 1) vs `workspace.shell` (tier 3) inconsistency for the
   same pytest invocation — documented as accepted risk in CURRENT_STATE boundary;
   observation only.
4. Sensitive-file exfil channel (`workspace.read` of `.env` -> provider payload) is
   inherent to coding agents; recommend a sensitive-file denylist before pointing at
   real repos. Recommendation, not blocker.

### LOW (selection)

- Truncated approval preview (2000 chars): human approves digest of a full action
  from a partial preview.
- Unbounded subprocess capture before truncation; uncapped artifact writes.
- grep ReDoS has no timeout (carried from interim).
- KeyboardInterrupt mid-turn leaves dangling tool_calls; fail-closed via correction
  halt, but a resumed session would hit provider HTTP 400 (resume is M4 scope).
- TurnResult lives in os_core as a dataclass, not in contracts (spec deviation).
- `.env.example` rewrite drops OPENAI_API_URL/ANTHROPIC_API_URL docs while the
  research harness still reads them.
- `workspace.search` glob mode ignores the `path` argument.
- `_subprocess_env` drops HOME/USER for run_tests (may break suites needing HOME).
- total_tokens double-counts context (conservative direction; M2 cost display note).
- Shell timeout kills only the direct child (no process group); hardlinks pass
  _safe_path (second-stage); RC3 reason string also used for headless -p denials.
- Graph-path grant envelope (max_risk_tier 1 -> spec tier) is a latent policy
  relaxation for tier-2 graph actions with no approval surface; no committed graph
  does this today; pinned by test + commit message, but the spec/boundary docs do not
  state it explicitly.
- The live run's tier-2 interactive approval leaves no durable approval event; it is
  corroborated only by the pty transcript, not the event stream.

## Open questions

1. Should the graph-path grant-envelope change be amended into the Architecture
   Brief explicitly, given spec section 6's confirmation wording predates it?
2. Should tier-2 approvals (not only denials) be recorded durably?

## Required changes (before merge)

1. Correct the live-verification date labeling (artifact filenames, md header/notes,
   CURRENT_STATE status string) from 2026-07-30 to the actual 2026-08-06.
2. Add a SIGINT regression test for `chat -p` proving CORRECTION_WRITTEN + exit 130.
3. State the graph-path grant-envelope change (grants track spec tiers; tier-2
   mutating graph actions admitted without an approval surface) explicitly in the
   boundary text.

## Recommendations (non-blocking)

Sensitive-file denylist (.env et al.) before real-repo use; run_tests/shell tier
consistency; full-diff approval display; bounded subprocess capture; regex timeout;
process-group kill; record tier-2 APPROVE decisions durably.

## Verdict

**APPROVE_WITH_REQUIRED_CHANGES** — governance spine unbypassed, interim fixes
genuinely closed, no HIGH findings; the three required changes above are minor
(evidence relabeling, one regression test, boundary-text touch-up).
