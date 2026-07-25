# ADR-0058: governed chain unified-diff patch channel (opt-in patch_format)

- Status: Accepted
- Date: 2026-07-26
- Deciders: founder (direction 2026-07-25: diff channel is the next highest-value harness change per the SELFDEV-3 adjudication; ADR-0003 founder-reserved tier — execution-contract change in the governed path) / agent drafts
- Review: independent reviewer (kimi subagent, blind-anchored, no builder run history) — Round 1 CHANGES_REQUESTED (F-1..F-4), Round 2 TECHNICAL_APPROVE 2026-07-26

## Context

Three consecutive evaluation rounds produced converging evidence that the
governed chain's complete-file replacement output contract is its residual
bottleneck — while its correctness is not:

1. MT round (self-made targets, NEGATIVE): on `apps/cli/__main__.py` (551+
   lines) the provider twice emitted invalid Python as "complete replacement
   content" (diff fragments, mismatched braces) — 2/2 completed attempts.
2. SELFDEV-2 (SUPPORTS w/ caveats): 180s × K2 reasoning latency ×
   complete-file output was the envelope's binding constraint; the two
   largest files went 0/4 on the chain.
3. SELFDEV-3 (SUPPORTS, window-unconfounded): with 600s the chain solved
   19/20 completed attempts — but `sympy__sympy-13974` still timed out 2/2
   (content-specific generation length, not size alone), and the bare
   baseline's binding constraint became unified-diff reliability
   (13/24 DIFF_INVALID). The chain won under the declared harder output
   contract (complete-file vs diff).

The governed provider node (`execution.py:1077-1160`) mandates complete-file
replacement: the prompt instructs "Propose the complete replacement content",
proposals must contain exactly `{path, content}`, and
`workspace.apply_patch` writes bytes. Consequences: output token volume
scales with file size (the timeout/degradation classes above), a hard
19,000-byte task ceiling, and a declared output-contract asymmetry vs the
diff-based cheap baseline.

A unified-diff channel attacks the timeout/degradation classes and the
asymmetry: output volume drops to the size of the change (the
output-reproduction ceiling disappears; the 19,000-byte INPUT-content
truncation remains per Consequences), and the output contract matches the
baseline's (eliminating the asymmetry rather than merely declaring it
conservative).

## Options Considered

- **Option A (chosen): additive opt-in `patch_format` on the governed
  provider/apply path.** The workflow/task declares
  `patch_format: "unified_diff"` (default `"complete_file"`, fully backward
  compatible). In diff mode: the prompt asks for a single-file unified diff
  for the target; proposal arguments must be exactly `{path, diff}`; the
  diff is validated with the SAME fail-closed rules the cheap baseline uses
  (`validate_unified_diff`: single file, path match, no absolute/`..`
  segments, well-formed hunks) and applied host-side via `git apply`
  (check-first, fail-closed) inside the governed workspace — same trust
  level as writing bytes (the workspace is ours; the diff text is validated
  model output). C6/C7: approval/exact-digest/compensation semantics
  untouched; only the proposal FORM and its validation change.
- **Option B: replace complete-file with diff everywhere.** Smaller code
  delta long-term but breaks every existing Agent OS selfdev target, the
  sealed-run product tests, and T1's frozen red/green fixture semantics;
  and there is no evidence diff mode fixes content-specific latency in
  general (sympy is one task). Rejected: blast radius without necessity.
- **Option C: keep complete-file, raise timeouts further.** Does not remove
  the 19KB ceiling, keeps the output-contract asymmetry, and leaves the
  MT-round syntax-failure class (large full-file generation) unaddressed.
  Rejected: treats the symptom already priced by E2's 600s.

Strongest counterargument to A: unified diffs from models are themselves
unreliable (13/24 DIFF_INVALID on the bare baseline) — the chain may inherit
that failure class. Accepted and priced: the baseline's diff failures were
the BASELINE's binding constraint, but the chain's diff validation is the
same fail-closed validator the baseline already pays; per-attempt INVALID
classes already account for malformed output; and the diff channel makes
chain and baseline contract-symmetric, which is what future rounds need to
compare harness value rather than output-format difficulty.

## Decision

1. **`patch_format` plumbed as a task/run-level option** with default
   `"complete_file"`. Run inputs may carry `patch_format: "unified_diff"`;
   it propagates into `_call_provider` (prompt + validation) and the apply
   step. The forbidden runtime-input list
   (`apps/api_server/app.py:919-937`, `forbidden_configuration_inputs`)
   does NOT include `patch_format`, and inputs pass through verbatim into
   the run context (`execution.py:1371-1372`), so no reserved-key
   collision exists.
2. **Prompt branch** (`execution.py:_call_provider`): diff mode asks for
   exactly one single-file unified diff for the target path (no other
   content, no markdown fence requirement), otherwise unchanged (target
   path, current sha256, current file content up to the same limit — the
   limit remains for INPUT, to be revisited separately).
3. **Proposal validation branch**: in diff mode, proposals must contain
   exactly `{path, diff}` (any other key → existing fail-closed error);
   the three-way binding is enforced explicitly: diff-header path ==
   proposal `path` == reviewed target (the proposal-path/target equality
   already exists at `execution.py:1146`; `validate_unified_diff` checks
   single-file internal consistency only and does NOT bind the diff to a
   path — the header-path check is added here). `diff` must also pass
   `agent_os_core.benchmark_baseline.validate_unified_diff` (single file,
   no absolute/`..` segments, well-formed hunks) — the same validator the
   cheap baseline uses, now shared by both arms.
4. **Apply branch**: in diff mode, the governed apply step applies the
   validated diff via `apply_unified_diff` (git apply --check first,
   fail-closed, no repair) instead of writing bytes. Compensation
   (restore pre-change bytes) is unchanged — it snapshots bytes, not
   formats.
5. **Benchmark admission**: `SelfDevelopmentBenchmarkTask` and
   `prepare_benchmark_task_package` run inputs gain
   `patch_format: "unified_diff"` as the declared benchmark default at the
   NEXT prereg (SELFDEV-4); Agent OS selfdev targets keep complete_file.
6. **Tests first** (bypass-detecting): product test driving a sealed
   diff-mode run end-to-end (provider proposes a diff → approval → git
   apply → tests → evaluate → COMPLETED); an approval-bypass test (sealed
   diff-mode run WITHOUT approval ⇒ workspace bytes unchanged, run not
   COMPLETED); validation tests (content-form rejected in diff mode,
   diff-form rejected in complete mode, second file rejected,
   absolute/`..` rejected, diff-header path != proposal path rejected,
   proposal path != reviewed target rejected, malformed hunk rejected);
   a sealed task without snapshot id still fails closed in diff mode.

## Consequences

- Build scope: `execution.py` prompt/validation/apply branches, run-input
  plumbing, shared validator import, benchmark package run-input, product
  tests. No contract-schema change is required for
  `SelfDevelopmentBenchmarkTask` (patch_format rides run inputs).
- SELFDEV-4 may use a harder subset (files >19KB, no complete-file ceiling)
  with chain and baseline on the SAME output contract — the comparison
  becomes harness-vs-harness rather than format-vs-format.
- New failure classes to watch: chain-side DIFF_INVALID rate (the
  baseline's E3 class) and apply-check rejections; both are per-attempt
  INVALID accounting, not round invalidation.
- The 19,000-byte input-content truncation in the provider prompt
  (`execution.py:1088`) remains in force for BOTH modes in this ADR;
  removing it is a separate decision.
- Deferred: changing the default patch_format for Agent OS selfdev targets
  (needs its own evidence); multi-file diffs (single-file stays).
- Review requirement: independent review before Accepted; implementation
  follows acceptance with tests first.
