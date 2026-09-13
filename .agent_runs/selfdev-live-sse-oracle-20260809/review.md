# Independent Exact-Head Review — SSE Oracle

- Reviewer model identity: `opencode-go/kimi-k3` (differs from builder `opencode`)
- Exact head under review: `51ac8d2feee7a702405eb21da2f2a7c598a09f29` (`51ac8d2f`)
  on `codex/selfdev-live-sse-oracle-20260809`
- Behavioral implementation: `7cc3f6ff`; oracle test pre-committed at `2f44e704`
- Date of review: 2026-08-12
- Verdict: **APPROVE_WITH_P2** (bound to exact head `51ac8d2f`)

## Findings

### P2-1 — Fail-closed branch also kills spec-legal SSE non-data lines (interop narrowing)

`packages/os_core/src/agent_os_core/provider.py:534-537` treats every non-empty
line that does not start with `data:` as a JSON payload. The new fail-closed
branch at `provider.py:540-548` therefore returns non-retryable
`ProviderFailure(MALFORMED)` not only for malformed `data:` JSON (the stated
goal) but also for SSE comment lines (`: keep-alive`) and `event:` / `id:` /
`retry:` field lines, which are legal per the SSE specification and are emitted
as keep-alives by some OpenAI-compatible gateways/proxies. Under the parent
(`2f44e704`, `continue` at old line 543) such lines were silently skipped, so
this head narrows interop tolerance beyond the "malformed JSON" scope described
in the commit message and `verification.md`. OpenAI's own chat-completions
stream emits only `data:` lines, so in-scope behavior is correct and the
fail-closed posture is deliberate; the exposure is limited to
OpenAI-*compatible* endpoints that emit control lines. Severity P2: latent
interop risk, not a correctness defect against the stated contract. Tracked as
open question 1.

### P2-2 — Valid-JSON / wrong-shape stream payloads classify as retryable UNAVAILABLE, not MALFORMED (pre-existing)

A `data:` line containing syntactically valid JSON of the wrong shape (e.g.
`data: 5`, or `choices` as a string) raises `AttributeError` at
`provider.py:549-550` (`payload.get(...)`). `AttributeError` is not in the
`(KeyError, TypeError, ValueError, json.JSONDecodeError)` handler at
`provider.py:489`, so it falls through to `except Exception` at
`provider.py:503-509` and is classified `ProviderErrorCode.UNAVAILABLE` with
`retryable=True`. Empirically confirmed against this exact head with a
throwaway probe (no source modification): `data: 5` →
`FAILURE code=UNAVAILABLE retryable=True`. Consequences:

- Inconsistent with the non-streaming path, where wrong-shape payloads map to
  non-retryable MALFORMED (`provider.py:489-495`), and with the fail-closed
  intent of this lane.
- `retryable=True` makes `agent_loop.py:516-517` retry the request
  (`max_provider_retries + 1` attempts, `agent_loop.py:459-461`), re-emitting
  partial deltas on each attempt before the turn finally fails.

This gap predates `7cc3f6ff` (the `.get` chain and `_invoke` handlers are
unchanged by this head) and is not worsened by it, so it does not block the
exact head; it is recorded because review scope item 2 covers exception
classification and retryability consistency. Recommended follow-up: type-check
`payload` / `choices[0]` / `delta` in `_parse_sse_stream` (or catch
`AttributeError`) and map to non-retryable MALFORMED.

### P2-3 — Oracle test under-pins the failure contract

`tests/product/test_agent_cli_stream.py:233-234` asserts only
`isinstance(result, ProviderFailure)` and `code is ProviderErrorCode.MALFORMED`.
It does not pin `result.retryable is False`, the request binding
(`result.request_id == "request-sse-malformed"`), or the partial-delta
guarantee (deltas emitted before the malformed line exactly once, lines after
it ignored — currently `["Hel"]` at `test_agent_cli_stream.py:226` via
`provider.py:558-560`). Retryability and request binding are part of what this
review was asked to declare safe and consistent, and the caller-side safety
(`agent_loop.py:512-518`) depends on them; a regression to `retryable=True`
would pass the current oracle. Suggested, not blocking.

No P0 or P1 findings.

## What was verified at the exact head (independently rerun)

| Check | Claim in `verification.md` | Reproduced |
|---|---|---|
| `pytest tests/product/test_agent_cli_stream.py tests/product/test_provider_http_adapter.py tests/product/test_provider_relevance_assessor.py -q` | 65 passed | 65 passed |
| `pyright packages/os_core/src/agent_os_core/provider.py tests/product/test_agent_cli_stream.py` | 0 errors | 0 errors, 0 warnings |
| `ruff check` on changed files | passed | passed |
| `git diff --check` | passed | passed |
| Full `pytest tests/product -q` | 19 failed, 1814 passed, 1 skipped; failure set identical to baseline | 19 failed, 1814 passed, 1 skipped; the 19 test IDs are line-for-line identical to `/tmp/main_failures.txt` (zero new failures) |
| Oracle genuinely failing pre-implementation | implied by `2f44e704` flow | confirmed: `test_openai_compatible_provider_rejects_malformed_sse_delta` FAILS at `2f44e704` (detached temp worktree, since removed), passes at head |

## Assessment against brief items

1. **Fail-closed typed MALFORMED without changing valid behavior — MET.**
   `provider.py:542-548` returns `ProviderFailure(code=MALFORMED,
   retryable=False)` bound to `request.request_id` via `_failure`
   (`provider.py:616-629`). The success path is byte-for-byte unchanged except
   the return-type widening (`provider.py:517`), which matches the already-
   union-declared caller `_invoke` (`provider.py:375`). The happy-path SSE
   test (`test_agent_cli_stream.py:131-185`) still passes with the new
   `isinstance` narrowing at line 180, which both satisfies Pyright and pins
   that the valid stream still returns `ProviderResponse`.
2. **Classification, binding, retryability, partial deltas — SAFE at this
   head, with P2 caveats.** MALFORMED is non-retryable, consistent with the
   non-streaming path; the caller enforces request binding
   (`agent_loop.py:512-515`), does not retry (`agent_loop.py:516-518`), and
   maps the failure to `stop_reason="provider_failure:MALFORMED"` with
   `final_text=safe_message` (`agent_loop.py:380-383`), so partial streamed
   text is never committed as the assistant turn result. Deltas emitted live
   before the failure remain visible to the user (inherent to streaming; see
   open question 3). P2-2 records the adjacent pre-existing classification
   gap.
3. **Test sufficiency and claim boundary — MET with a P2 suggestion.** The
   oracle uses a genuinely truncated JSON payload
   (`test_agent_cli_stream.py:202-206`), env-var credentials are set/restored
   in `finally` (no secret material persisted), and the failing-test-first
   flow is real (verified). P2-3 suggests pinning retryability/binding. The
   `verification.md` Boundary section correctly disclaims live-provider
   evidence, HCW evidence, self-improvement, autonomy, release readiness, and
   notes the lane is unmerged pending this review; `messages.jsonl` matches
   the actual head and scope. No capability completion is claimed from module
   existence or mocks.
4. **Findings with file/line references** — see Findings above.

## Open questions

1. Should `_parse_sse_stream` skip SSE comment (`:`-prefixed) and
   `event:`/`id:`/`retry:` field lines before JSON parsing (P2-1)? The answer
   depends on whether any targeted OpenAI-compatible endpoint emits keep-alive
   control lines; if yes, the current fail-closed branch will hard-kill those
   streams non-retryably.
2. Should the wrong-shape-JSON classification gap (P2-2) be closed in a
   follow-up on this lane before joint integration with `b32f2cb`, or tracked
   separately? It predates this head.
3. Is the streaming UX acceptable where partial text is printed live and the
   turn then ends as `provider_failure:MALFORMED` with the safe message
   (`agent_loop.py:380-383`)? Inherent to streaming, but the CLI does not
   annotate that the streamed prefix was truncated by a provider failure.

## Required changes

None blocking this exact head. Recommended (all P2, may be follow-ups):

- Pin `result.retryable is False` and `result.request_id` in
  `test_openai_compatible_provider_rejects_malformed_sse_delta`
  (`test_agent_cli_stream.py:233-234`).
- Decide and document the SSE non-data-line policy (P2-1).
- Track the wrong-shape-payload classification fix (P2-2).

## Exact-head verdict

**APPROVE_WITH_P2** — bound to exact head
`51ac8d2feee7a702405eb21da2f2a7c598a09f29` (`51ac8d2f`) on
`codex/selfdev-live-sse-oracle-20260809`.

The head delivers exactly the claimed behavior — malformed SSE `data:` JSON
fails closed as a typed, non-retryable, request-bound
`ProviderFailure(MALFORMED)` with no change to valid streaming/tool-call
behavior — and every verification claim in `verification.md` reproduced under
my own rerun. Three P2 findings (interop narrowing on SSE control lines, a
pre-existing wrong-shape classification gap, oracle test under-pinning) are
recorded for tracking and do not block joint-integration consideration.

Reviewer: `opencode-go/kimi-k3`. No source files were modified; no commits,
pushes, or merges were performed. The only file added by this review is this
`review.md` (untracked, in the run ledger directory).
