# FINAL ADVERSARIAL REVIEW — M1 kernel slices S1–S5

> Reviewer role: final adversarial reviewer (one branch).
> Worktree: `autonomous-agent-core/.worktrees/m1-danger-cmd-20260915`
> Branch: `feature/m1-dangerous-command-classification-20260915` @ `b0bd7c72`
> Base: `origin/main` @ `18d7b9b0` (note: `origin/main` has since advanced to `fe29a5a4`; the
> branch is based on an ancestor of the current main, not on current main — see F0).
> Claim ceiling: this review authorizes at most "implemented/tested/integrated for the
> reviewed slices"; no parity / Alpha / Autonomy(S,E,O,V,T) / release claim.
> Verdict: **APPROVE_WITH_CHANGES**

This review treated every source/test file as read-only and wrote only this report.

---

## 0. What was reviewed

`git diff 18d7b9b0..b0bd7c72 --stat` → 37 files, +4109 / −38. Code changes:

| Slice | Files |
|---|---|
| S1 | `domain_packs/developer_agent/shell_denial.py` (new), `workspace_capability.py` |
| S2 | `packages/os_core/src/agent_os_core/permission_rules.py` (new), `permission_gate.py`, `agent_loop.py` (gate + pending path), `apps/api_server/app.py`, `responsibility_surface.py`, `__init__.py` |
| S3 | `agent_context.py`, `apps/api_server/app.py` |
| S4 | `agent_loop.py` (`_compact_history`, `_maybe_record_compaction`), `packages/contracts/.../runtime.py`, `session_projection.py`, `task_aggregate.py` |
| S5 | `.agent_runs/m1-s5-sandbox-recon-20260915/verdict.md` (docs-only) |

Test/artifact additions: `tests/product/{test_shell_denial,test_permission_deny_rules,test_agents_markdown_layers,test_context_compaction}.py` plus the committed `.agent_runs/*` packets.

## 1. Commands run (exact)

```
uv run --extra product-test pytest tests/product/test_shell_denial.py \
  tests/product/test_permission_deny_rules.py tests/product/test_agents_markdown_layers.py \
  tests/product/test_context_compaction.py tests/product/test_chat_agents_markdown.py -q
  => 53 passed in 2.23s

uv run --extra product-test pytest tests/product/test_permission_mode_matrix.py \
  tests/product/test_permission_mode_protocol.py tests/product/test_terminal_chat_loop.py -q
  => 50 passed in 5.63s

uv run --extra product-test pytest tests/product -q            # branch
  => 24 failed, 2566 passed, 1 skipped
uv run --extra product-test pytest tests/product -q            # base 18d7b9b0 (throwaway worktree)
  => 23 failed

uv run --extra product-test ruff check apps packages/contracts/src packages/os_core/src \
  tests/product domain_packs/developer_agent/shell_denial.py   => All checks passed

uv run --extra product-test pyright  (pyproject include = branch's)
  => 118 errors, 0 warnings — ZERO in any new/changed source file (all pre-existing test-file errors)
```

Regression check: the 23 base failures and the 24 branch failures are the same set except
`test_surface_stream_http.py::test_stream_resume_via_last_event_id_yields_no_duplicates`,
which **passes in isolation and as a whole file on the branch** (7 passed) and is an
HTTP/ordering flake. Net branch-introduced real regressions: **0**.

---

## 2. Per-slice boundary verification

### (a) S1 — typed enumerable shell denial — PASS
- `require_allowlisted_command` reproduces the old exact-match check verbatim; the
  messages are byte-identical to base (`"command is not in the shell allowlist"`,
  `"only the allowlisted test commands are permitted"`), and the run-tests set is the
  same `{"pytest","python -m pytest","python3 -m pytest"}` (`workspace_capability.py:44`).
- Fail-closed is preserved: unlisted ⇒ raise. `ShellCommandDenied` subclasses
  `CapabilityDenied`, so existing callers/error handling are unchanged
  (`test_denial_is_still_a_capability_denied`).
- Enforced at BOTH the preflight (`:451`,`:459`) and the execution sites (`_shell`
  `:1216`, `_run_tests` `:1245`), so reaching execution without a preflight cannot
  bypass the allowlist. Bypass-detecting test present.
- No regex/classifier remains (no ReDoS surface); the descope is real.

### (b) S2 — durable DENY-only rules — PASS
- `PermissionRuleKind` has exactly `DENY` (`test_only_the_deny_kind_exists`). There is no
  ALLOW kind, so a persisted rule can never grant authority.
- `apply_deny_rules` returns **either the input decision unchanged or `DENY_BY_RULE`** —
  it never produces `TIER_DEFAULT_AUTO_PASS` / `MODE_AUTO_ALLOW`
  (`test_apply_deny_rules_never_produces_an_allow_outcome`). It cannot auto-approve
  tier-3 and cannot pre-empt C7: it only adds denial.
- The frozen E2 matrix `evaluate_permission_gate` body is **unchanged**; only the enum,
  the `basis` Literal and the new `apply_deny_rules` were added. `test_permission_mode_matrix.py`
  and `test_permission_mode_protocol.py` are untouched and pass.
- Existing denials are never relabelled (out-of-allowlist keeps its audit provenance,
  `test_apply_deny_rules_preserves_an_existing_denial`).
- Pending-approval path blocks **APPROVE only** (`agent_loop.py:578-596`); REJECT stays
  resolvable and the pending entry clears (`test_deny_rule_does_not_wedge_a_reject`),
  and APPROVE is refused with a durable `POLICY_VERDICT_RECORDED(DENY, basis=rule, rule_id)`
  (`test_deny_rule_blocks_resolving_a_pending_approval`). Rules are re-read from the store
  on every `restore_chat_session`, so a rule added after escalation is honoured.
- Scope: tenant+workspace+capability with `*` capability wildcard; revocation durable
  across reopen (`test_store_save_list_and_revoke`, `test_store_is_tenant_scoped`).

### (c) S3 — layered AGENTS.md/CLAUDE.md — PASS (one nuance, F2)
- Bounded: root probe first, then `os.walk` with sorted, hidden-pruned dirs; caps on
  layers, total chars, dirs, entries, per-file bytes. Per-layer `sha256`.
- Fail-closed per layer: symlink, out-of-workspace, unreadable, non-UTF-8 or oversized
  file is skipped (never raises). `O_NOFOLLOW` closes the symlink→read TOCTOU.
- Root-only render is byte-identical to legacy `agents_markdown_system_section` for
  files within the hard cap (`test_root_only_matches_the_legacy_single_layer_render`).
- No authority change: only prompt text is injected; the LLM output path is unchanged.

### (d) S4 — deterministic compaction — PASS
- Never drops the active request: cut is bounded by the last USER index; a single
  over-budget turn yields no cut and is **not** recorded (`test_single_turn_records_no_compaction_event`).
- Never splits tool groups: cuts only at USER boundaries.
- Only real compactions recorded: `cut <= 1` ⇒ `None`; dedup on the stable drop boundary
  avoids per-step re-recording (`test_maybe_record_compaction_writes_exactly_one_event`,
  `test_same_boundary_is_recorded_once_across_steps`, `test_two_distinct_compactions_are_both_recorded`).
- Deterministic digest over roles/ids/tool_calls/content; deterministic across runs.
- No authority added; it only selects which messages are sent.

### (e) New contract event — PASS
- `SESSION_CONTEXT_COMPACTED` is a no-op in `session_projection._strict_project`
  (`:476`, `continue`) and in `TaskAggregate.apply` (audit-marker branch, `:456`); it only
  advances `sequence`/`last_event_id`. Replay-safe
  (`test_projection_ignores_a_recorded_compaction`). Not added to `PROTECTED_TRUTH_EVENTS`
  (correct — it is not a truth event).
- Enum addition caused no exhaustiveness break: full-suite regression set identical to base.

### (f) Authority / product-research boundary — PASS
- S1 lives in `domain_packs/developer_agent/` (domain pack), not os_core. S2/S3/S4 are
  in-repo kernel/product code, self-developed, behind the existing gate. No research
  import, no cross-repo import, no C7/`op_*` touch, no secret handling. No slice widens
  authority; S2/S3/S4 are strictly restrictive/ephemeral/audit-only.

---

## 3. Findings

### F0 — Base is stale relative to current `origin/main` — INFO
The branch base `18d7b9b0` is an ancestor of the current `origin/main` (`fe29a5a4`,
2 commits ahead: #55–#57). Rebase/refresh is a release decision, not a slice defect, but
the merge gate must re-run against current main.

### F1 — S1 goal card body is internally inconsistent / contains a false verification claim — MEDIUM (claim discipline)
`.agent_runs/m1-danger-cmd-20260915/goal-card-cp-ab.md` has a `DESCOPED` header that
correctly explains the classifier removal, but the body was not updated:
- §3 Architecture still describes `classify_dangerous_command(command)` running FIRST;
- §4 CTO conditions 1/3/4 still require the classifier and a
  `test_dangerous_command_is_denied_even_when_allowlisted` test;
- §5 Verification claims `tests/product/test_dangerous_command.py: 31 tests` — that file
  does not exist on the branch (only `test_shell_denial.py`, 8 tests, exists).
A reader could believe a dangerous-command classifier shipped. This violates the repo's
claim-discipline rules (no "implemented" claim from artifacts that don't exist).
**Required change:** rewrite §3/§4/§5 to the shipped typed-denial-only contract and the
real file/test counts.

### F2 — S3 "root-only byte-identical" is false for files > 128 KiB — LOW/MEDIUM
`discover_agents_markdown_layers` → `_read_layer` **skips** a file larger than
`_MAX_BYTES_PER_FILE` (128 KiB), whereas legacy `discover_agents_markdown` read it fully
and truncated to `max_chars` (12000). Since `app.py` switched to the layered function, a
workspace with a >128 KiB root `AGENTS.md` now loses **all** instruction context instead
of the first 12000 chars. `test_oversized_layer_is_skipped` asserts the skip, so the
behavior is intentional and fail-closed, but the acceptance criterion "root-only output is
byte-identical to legacy" holds only for ≤128 KiB. (No test covers the >128 KiB *root*
case against the legacy render.)
**Required change:** either preserve legacy truncation for the root layer, or state the
behavior change explicitly in the goal card/verdict and amend the "byte-identical" claim
to "for files ≤128 KiB".

### F3 — S4 dedup key is boundary-only and loop-scoped — LOW
`_maybe_record_compaction` keys on `(dropped_messages, kept_from_index)` and ignores
`retained_digest`; `_last_compaction` resets whenever the loop is rebuilt (each turn).
Within a turn the boundary is stable, so no per-step duplication; across turns the
boundary normally advances, so duplication is unlikely but not structurally impossible if
two genuinely distinct retained contexts shared a boundary. Also `max_context_chars <= 0`
now disables compaction entirely, where legacy would still cut. Both are documented or
benign, but the "exactly once per real compaction" property rests on an unstated
invariant. **Suggested change:** bind dedup to `retained_digest` as well, or document the
invariant; and add a test/comment for the `<= 0` branch.

### F4 — S2 authoring surface is programmatic only — LOW (coverage scope)
`SQLitePermissionRuleStore` (save/revoke/list) is the only way to author rules; there is
no typed HTTP/Surface command or CLI path, and no test proves a rule authored through a
*product entry point* round-trips into a live loop (tests call the store directly). The
kernel integration is real and tested; the user-facing entry point is not part of this
slice. **Suggested change:** note this explicitly as `implemented/tested`,
`entry point = programmatic`, and track the operator surface as follow-up (do not claim
"integrated" end-to-end).

### F5 — Pre-existing repo failures (not branch) — INFO
23 deterministic failures exist on base `18d7b9b0` (task-configuration snapshot tests,
openai provider binding, data-agent fullstack, wave2 SSE fixture, etc.); the full product
suite is **not green at base**. The branch adds no real failure. Green-slice claims must
not be read as a green full gate. The configured pyright run has 118 pre-existing errors
(0 in new/changed files); the branch adds no new ones.

### F6 — C7-vs-rule provenance ordering on the pending path — INFO
On the pending-approval APPROVE path the deny-rule check runs before
`_validate_pending_runtime(require_current_c7=True)`, so a stale-C7 action with a matching
rule is recorded as `DENY (basis=rule)` rather than a C7-staleness denial. The action is
still denied (no bypass, no authority widening); only provenance differs. Optional polish.

---

## 4. Test count

**53 passed** for the five required files (0 failures, 2.23s). Adjacent frozen-matrix +
chat-loop suites: **50 passed**. Full product suite: 24 failed / 2566 passed / 1 skipped,
matching base (23) up to one verified HTTP flake → **0 real branch regressions**.

## 5. Independence limitation (stated honestly)

I am the model **`deepseek/deepseek-flash` (provider: DeepSeek)** operating as an
opencode CLI agent. I am not the author of these commits, but I am a **single LLM reviewer
in a shared harness**, not an independent human, and I cannot cryptographically verify the
provider/identity of the earlier builders or the `review-subagent*.md` authors in
`.agent_runs/*`. This is therefore a same-family-of-tooling, model-mediated review; it
satisfies `builder_id != reviewed_by` only in the weak sense of a different agent
identity/session, not in the strong sense of a guaranteed independent provider. The red
tests, the diff read, and the base-vs-branch failure diff above are the compensating
evidence; they are reproducible by any reviewer.

## 6. Verdict

**APPROVE_WITH_CHANGES**

Required before promote/merge:
- **S1:** fix the goal-card body (F1) — remove the stale classifier architecture/conditions
  and the non-existent `test_dangerous_command.py` / 31-test claim; state the real typed
  denial contract and 8-test file.
- **S3:** resolve the >128 KiB root-file semantics and amend the "byte-identical" claim, or
  restore legacy truncation (F2).
- **S4:** bind dedup to `retained_digest` or document the boundary/loop invariant (F3).
- **S2:** label the rule-authoring surface as programmatic-only and track the operator
  entry point as follow-up (F4).

Non-blocking: F0 (base refresh), F5 (pre-existing base failures), F6 (provenance ordering).
No slice widens authority, crosses the product/research boundary, weakens C7, or alters the
frozen E2 matrix.
