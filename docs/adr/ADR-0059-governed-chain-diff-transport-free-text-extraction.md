# ADR-0059: governed chain diff transport — free-text output with server-side extraction

- Status: Proposed
- Date: 2026-08-07
- Deciders: founder (direction 2026-08-07: proceed per the SELFDEV-4 adjudication's paradigm learning; ADR-0003 founder-reserved tier — execution-contract change in the governed path) / agent drafts, independent review required before Accepted

## Context

ADR-0058 added the opt-in `unified_diff` patch format to the governed chain
with the tool-call JSON transport (provider must return a
`workspace.apply_patch` proposal whose `arguments_json` carries
`{path, diff}`). SELFDEV-4 measured it against the bare baseline under
format-symmetric contracts and adjudicated NEGATIVE (chain 1/12 vs baseline
4/12), with the decisive decomposition: 8 of 9 weather-free chain attempts
failed on the tool-call JSON transport (extra envelope keys, malformed hunk
bodies, apply-time context mismatch), while the baseline's free-text diff
channel solved 5/11 usable attempts in the same window and the chain's own
complete-file transport solved 19/20 at E3.

The evidence localizes the regression to the TRANSPORT, not the diff
semantics and not governance: the governed flow was never even reached on
those attempts (outputs died at proposal validation). The baseline's
robustness comes from free-text output + deterministic server-side
extraction (`_extract_unified_diff` in the baseline CLI) with the same
fail-closed validator.

## Options Considered

- **Option A (chosen): keep ADR-0058's diff semantics; change the transport
  to free-text + server-side extraction inside the governed provider node.**
  In diff mode the prompt asks for a plain-text unified diff (no tool-call
  requirement); the provider node deterministically extracts the diff from
  `response.text` (same extraction rules as the baseline), validates it
  (`validate_unified_diff` + the three-way path binding), and synthesizes
  the single `workspace.apply_patch` proposal with `{path, diff}`. Approval,
  apply, evaluate, compensate all unchanged. Tool-call proposals remain
  valid when present (back-compat).
- **Option B: revert the chain to complete-file.** Restores the E3-level
  chain correctness but keeps the output-reproduction ceiling (large-file
  timeouts) and the format asymmetry against the baseline. Rejected: it
  freezes the harness at a known ceiling.
- **Option C: prompt-tune the tool-call channel** (stronger instruction
  wording, few-shot examples). Rejected: unprincipled knob-twiddling against
  a structurally fragile transport (long diffs inside JSON string literals);
  the evidence says the transport itself is the failure class.

Strongest counterargument to A: free-text extraction adds a parsing surface
(models wrap diffs in prose/fences). Accepted and priced: the baseline's
extraction rule is deterministic and fail-closed (no diff found ⇒ attempt
failure, recorded, never repaired by a human), and it already proved robust
on the baseline arm (only 4/24 DIFF_INVALID from format, 13/24 from
weather).

## Decision

1. **Extraction moves into os_core**: add
   `extract_unified_diff(text: str) -> str | None` to
   `agent_os_core.benchmark_baseline` (first `--- ` header through EOF,
   trailing markdown fences stripped; None if absent). The baseline CLI
   imports it (deduplicated from `_extract_unified_diff`).
2. **Diff-mode provider node** (`execution.py:_call_provider`): in
   `unified_diff` mode the prompt asks for the diff as plain text (single
   file, target path, well-formed hunks; no tool-call requirement). On
   response: if a tool-call proposal exists, validate it as today; if not,
   `extract_unified_diff(response.text)` — None ⇒ fail closed
   ("provider must return exactly one workspace.apply_patch proposal"
   class); extracted diff ⇒ synthesize the proposal with
   `{path: target_path, diff: extracted}` and continue through the existing
   validation (three-way binding, expected_sha256 injection).
3. **No change** to approval, apply (git apply --check fail-closed),
   compensation (byte snapshots), evaluation, or the attempt-accounting
   classes. Output-contract asymmetry note: both arms now use free-text
   diff + extraction — full format symmetry.
4. **Tests first**: e2e sealed diff-mode run where the provider returns the
   diff as fenced TEXT (no tool proposal) → extraction → approval → apply →
   tests → COMPLETED; extraction matrix (fenced / raw / prose-wrapped →
   extracted; no diff → fail closed); the approval-bypass negative for the
   SYNTHESIZED proposal path (provider returns fenced/raw diff TEXT, no
   tool proposal, NO approval ⇒ extraction may occur, but workspace bytes
   unchanged and run not COMPLETED); the carried validation matrix keeps
   passing; tool-call path still accepted.
5. **SELFDEV-5 prereg** (separate document): reuses the SELFDEV-4 frozen
   subset verbatim (declared; no cross-run provider memory) with a
   pre-round provider health gate.

## Consequences

- Build scope: extraction helper move, provider-node extraction branch,
  prompt wording, tests. Small and surgical.
- The chain and baseline now share BOTH the output contract (diff) and the
  transport (free text) — the SELFDEV-5 comparison isolates harness value
  (governance) with no format or transport confound.
- If E5 still shows the chain ≤ baseline on weather-free attempts, the
  harness-value question gets its sharpest possible answer; that is the
  point.
- Deferred: multi-file diffs; lifting the 19,000-byte input truncation;
  prompt-level tuning of any kind.
- Review requirement: independent review before Accepted; implementation
  follows acceptance with tests first.
