# Independent Adversarial Re-Review — SRL TaskActivationGate (round 4)

> Reviewer model: `deepseek/deepseek-v4-pro` (builder was `opencode/deepseek-v4-flash`)
> Prior reviews: `review-subagent.md` (H1–H5), `review-r2.md` (F1–F5), `review-r3.md` (H1 PARTIALLY_CLOSED empty-producer fail-open)
> Fix under review: `c76f28fa` (parent `ce21e318`; diff `ce21e318..c76f28fa`)
> Read-only: no source/test edits, no worktrees, no /tmp. Only `review-r4.md` written.

## Verification (reviewer-run)

- `pytest tests/product/test_srl_task_activation_gate.py tests/product/test_srl_runtime_invariants.py` — **62 passed** (`-p no:cacheprovider`).
- `ruff check` on the three touched files — **clean**.
- `pyright` on `srl_activation_gate.py` + `srl_runtime.py` — **0 errors / 0 warnings**.
- `git show c76f28fa --stat` — exactly 3 files, 59 insertions / 4 deletions; source delta confined to `srl_activation_gate.py` (+6/−2) and `srl_runtime.py` (+8/−3) plus one test file. No contract/port drift.

## Fix delta (correctness)

Both producer-extraction helpers now strip the value and treat an empty/whitespace value as absent:

- `srl_activation_gate.py:180` — `if not producer_instance_id:` (falsy) instead of `is None`.
- `srl_activation_gate.py:252-258` — `_goal_constraint` returns `value.strip() or None`.
- `srl_runtime.py:449-452` — `_extract_producer_instance_id` returns `value.strip() or None`.

The gate helper (`_goal_constraint`) is shared by all three constraint lookups, so the strip/`or None` change also applies to `mandate-ref:` and `assessment-ref:`. The two helpers remain consistent (gate uses `constraint[len(prefix):]`, runtime uses `split(":", 1)[1]`; both `.strip()` the value).

## Verdict per prior finding

### H1 (round 3 blocker) — empty/whitespace producer fail-open → **CLOSED**

Reproduced end-to-end (reviewer-run, inline) with a trusted authority:

| Constraint form | Gate result | Runtime result |
|---|---|---|
| `assessor-instance:` (empty) | `denied:PRODUCER_IDENTITY_UNAVAILABLE` | `I-23: producer identity unavailable` |
| `assessor-instance:   ` (whitespace) | `denied:PRODUCER_IDENTITY_UNAVAILABLE` | rejected |
| baseline (non-empty) | `activated=True` | `activated=True` |

The empty case is caught twice-over: the `NonEmptyStr` contract (`strip_whitespace=True`) already normalizes a trailing-whitespace constraint to `assessor-instance:`, and the extraction helpers return `None` for an empty value, which both entry points fail closed on. The two new tests (`test_gate_rejects_empty_producer_value`, `test_runtime_rejects_empty_producer_value`) pass and cover the gate + runtime paths.

### H2/H3/H4/H5 — unchanged from round 3 (CLOSED / latent, not part of this fix)
No source outside the producer helpers changed; the mandate/assessment binding, cross-scope, mission, and C7 epoch checks are byte-identical to `ce21e318` and still pass their regression tests.

## New bypass attempts

| Bypass | Result |
|---|---|
| Empty `mandate-ref:` | **rejected** (`AUTHORITY_BINDING_MISMATCH`) |
| Whitespace `mandate-ref:   ` | **rejected** (`AUTHORITY_BINDING_MISMATCH`) |
| Empty `assessment-ref:` | **rejected** (`AUTHORITY_BINDING_MISMATCH`) |
| Whitespace `assessment-ref:   ` | **rejected** (`AUTHORITY_BINDING_MISMATCH`) |
| Whitespace-padded producer with **same** instance accepting (`assessor-instance:assessor-instance-1   `) | **rejected** (`SAME_INSTANCE_PROPOSE_AND_ACCEPT`) |
| Cross-tenant goal (`tenant_id="t-2"`) | **rejected** (`AUTHORITY_BINDING_MISMATCH`) |
| Cross-workspace goal (`workspace_id="w-2"`) | **rejected** (`AUTHORITY_BINDING_MISMATCH`) |
| **Zero-width-padded producer with same instance accepting (`assessor-instance:assessor-instance-1\u200b`)** | **ADMITTED — `activated=True`** (see N1) |

The whitespace-padded producer case is now genuinely closed: `.strip()` removes the padding and the `SAME_INSTANCE_PROPOSE_AND_ACCEPT` check fires (previously the trailing-space value mismatched and the I-23 check was silently skipped).

### N1 — NEW (LOW, non-blocking residual) — non-whitespace producer padding defeats I-23 equality

The producer equality check (`authority.authority_instance_id == producer_instance_id`) compares the trusted authority instance id against a caller-supplied constraint string, normalized only by `.strip()`. `.strip()` removes Python-whitespace (`isspace()==True`), so a zero-width space `U+200B` (or any non-whitespace homoglyph) survives:

```
assessor-instance:assessor-instance-1\u200b   →  value "assessor-instance-1\u200b" ≠ "assessor-instance-1"
                                                →  SAME_INSTANCE check skipped → activated=True
```

Reproduced with a same-instance authority (`authority_instance_id="assessor-instance-1"`): the gate returns `activated=True`.

Assessment:
- **Not a regression** — the equality check has always used exact string comparison; this vector existed before `c76f28fa`.
- **Same class as the pre-existing, already-documented limitation** that the producer is derived from forgeable `ProposedGoal.constraints` (review-subagent H1 recommended "derive producer from the trusted `source_assessment_id` registry rather than forgeable goal constraints"; review-r3 H3 recorded the analogous assessment-registry latent). It is a sub-case of "producer is caller-forgeable", which three prior rounds accepted as non-blocking.
- **Reachability is narrow** — it requires an already-trusted, registry-resolved, digest-matched authority that is *also* the assessment producer (the self-acceptance scenario I-23 exists to prevent), plus active injection of an invisible character. It does not re-open the empty/whitespace *fail-open* (that path fails closed).

Recommendation (non-blocking, future round): anchor the producer comparison to a trusted source (e.g. derive producer from the assessment registry / `source_assessment_id`), or normalize the producer string beyond `.strip()` (e.g. strip `isspace()`+zero-width/homoglyph codepoints). This is the same recommendation carried forward from `review-subagent.md` H1.

## Idempotency confirmation

Durable path via `TaskServiceCreationAdapter` stays idempotent (reviewer-run):

```
first  -> activated=True, task_id=task:srl:goal-1
second -> activated=True, task_id=task:srl:goal-1
first.task_id == second.task_id -> True
```

No idempotency regression; the F1 conflict test (`test_conflicting_authority_reactivation_fails_closed`) and the durable idempotency test (`test_task_service_adapter_creates_durable_idempotent_task`) both pass in the 62.

## Approval status

**APPROVE**

The round-3 blocker (empty/whitespace producer fail-open) is genuinely closed in both entry points with passing gate+runtime regression tests; the empty/whitespace `mandate-ref:`/`assessment-ref:` and whitespace-padded producer cases are also closed; cross-scope remains fail-closed; idempotency is intact; ruff/pyright clean and 62 targeted tests pass. The single residual N1 (zero-width/non-whitespace producer padding) is a pre-existing, narrowly-reachable sub-case of the already-documented forgeable-producer limitation — not a regression and not part of this fix's mandate — and is recorded for a future hardening round rather than blocking. No push/merge performed.
