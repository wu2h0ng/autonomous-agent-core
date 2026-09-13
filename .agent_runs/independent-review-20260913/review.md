# Independent Review — SRL TaskActivationGate

> Reviewer model: `deepseek/deepseek-v4-pro` (distinct from builder `opencode/deepseek-v4-flash`)
> Diff: `0045aeea..5923fa32` (`066f631e`, `5923fa32`)
> Commands run: targeted pytest (52 passed), ruff (clean), pyright (clean), full product suite (22 failures, all pre-existing/unrelated — see §4)

## Findings (severity + file:line)

### F1 — MEDIUM — Fail-closed contract broken by uncaught exception; idempotency scope is narrower than claimed
`packages/os_core/src/agent_os_core/srl_activation_gate.py:194-196` and `:263-268`

`TrustedTaskActivationGate.decide` calls `self._task_creation.create_task(...)` with no `try/except`. `TaskServiceCreationAdapter.create_task` keys the durable Task on `event_id=f"event:srl-activate:{proposal_goal_id}"` and `occurred_at=authority.authorized_at`. `TaskService.ensure_task` raises `InvalidTransitionError("reserved task identity is bound to different canonical content")` when those keys (or the reconstructed `Goal` constraints) differ.

Consequence: re-activating the *same* `ProposedGoal` with a *different* `ActivationAuthority` — different `authorized_at`, a different `authorization_digest`, or different resolved `TaskRequirements` (which changes the appended `expected-outcome:`/`commitment:`/`capability-scope:` constraints) — raises instead of returning a typed denial. This propagates through `SrlRuntime.activate_goal` (no handler there either), so a legitimate competing authority or a drift in requirements crashes the caller rather than failing closed.

Verified empirically: first activation succeeds (`task:srl:goal-1`); a second activation of the same goal with an authority whose `authorized_at` differs by 30s raises `InvalidTransitionError: reserved task identity is bound to different canonical content`.

This directly contradicts the adapter docstring ("repeated activation of the same proposal is idempotent") — idempotency only holds for byte-identical authority + requirements, which is the trivial case. The gate's claim "enforces every precondition itself" is true, but the failure path is not closed.

### F2 — LOW — Dead checks that can never fire
`packages/os_core/src/agent_os_core/srl_activation_gate.py:155-156`

`authority.mandate_id == ""` and `authority.standing_mission_id == ""` are unreachable: both fields are `NonEmptyStr` (`min_length=1`, `strip_whitespace=True`), so Pydantic rejects empty strings at construction. The `AUTHORITY_BINDING_MISMATCH` branch can only be reached via the `source_proposed_goal_id` mismatch. Indicates a false assumption about the contract; dead code.

### F3 — LOW — Authority binding only partially verified
`packages/os_core/src/agent_os_core/srl_activation_gate.py:152-179`

The gate validates `mandate_id` (via `get_mandate` + tenant/workspace scope) but never checks that `authority.standing_mission_id` is the mandate's *current ratified* mission, nor that `authority.source_assessment_id` binds a real assessment. Not currently exploitable to reach `TaskService` because the adapter does not materialize `standing_mission_id`/`source_assessment_id` into the `Goal`, but it is a latent authority-binding gap that will matter the moment those fields are used downstream.

### F4 — LOW — C7 clearance identity consumed but ignored
`packages/os_core/src/agent_os_core/srl_activation_gate.py:42-43, 186-191, 259`

Only `clearance.correction_epoch` is compared to `mandate.correction_epoch`; `clearance_digest` and `cleared_at` are neither verified nor recorded. The adapter stores `c7-epoch:{epoch}` but not the digest, so the resulting Task carries no traceable clearance identity. Consistent with the brief's "C7 semantics not implemented" boundary, but a clearance whose digest is garbage (or from a different correction lineage) still passes as long as the epoch matches — worth noting for the eventual C7 promotion.

### F5 — INFO — Unused members
- `ActivationDenialReason.TRUSTED_AUTHORITY_MISSING` (`:26`) is never emitted; the gate uses `AUTHORITY_NOT_RECOGNIZED` for the missing-registry case.
- `CreatedTask.run_id` (`:58`) is declared but never populated.

## Required focus answers

1. **Authority bypass → TaskService**: none found. A caller-minted `ActivationAuthority` is denied unless `resolve()` returns an entry whose `content_digest` equals the caller-supplied record (line 149), binding/scope match (152-179), I-23 (160-166), active mandate (168-179), requirements (181-184), and epoch-matched C7 (186-191). The trust boundary is the injected `authority_registry`/`c7_clearance`/`task_creation`; a compromised composition root would trivially admit minted authorities, but that is out of scope (not integrated).
2. **I-23**: enforced in both `SrlRuntime.activate_goal` (`srl_runtime.py:316-331`) and the gate (`:160-166`). Defense in depth; both reject same-instance propose+accept.
3. **Idempotency**: only for identical authority+requirements (see F1). The `event_id`/`occurred_at` derivation is stable for identical inputs, but diverges otherwise and raises instead of failing closed.
4. **Regression vs 39 invariants**: `tests/product/test_srl_runtime_invariants.py` passes (39/39). The `srl_runtime.py` change replaces an unconditional hardcoded rejection with delegation to the injected `TaskActivationPort`; the default `InMemoryTaskActivation` remains fail-closed, preserving prior observable behavior.
5. **Bypass-detecting tests**: present for caller-minted authority, inactive mandate, missing requirements, missing C7, epoch mismatch, same-instance, goal-binding mismatch, and creation-refusal. Missing: tenant/workspace scope mismatch (`:175-179`), `content_digest(trusted) != content_digest(authority)` (`:149`), `MANDATE_UNAVAILABLE` (`:169-172`), and the different-authority re-activation path that would expose F1.
6. **Scope creep**: none. Change is self-contained (one new module + a 7-line delegation change) and stays within the stated "not integrated, not verified" boundary. `ActivationDenialReason` enumerability is proportionate.

## Full-suite note

`uv run --extra product-test pytest tests/product -q` → 22 failures, 2211 passed, 1 skipped. Inspected failures are time-sensitive (`Task commitment expired before sealing`) or provider/credential/HTTP tests (`test_provider_relevance_assessor`, `test_data_agent_situated_fullstack`); none of the failing files import `srl_activation_gate`/`srl_runtime`, so they are pre-existing and unrelated to this diff.

## Open questions

1. Is there a planned composition root that guarantees the injected `authority_registry`/`c7_clearance`/`task_creation` are trusted (not caller-owned)? The gate provides no independent verification; test fixtures `_AuthorityRegistry` trust whatever they are handed.
2. Should `TaskServiceCreationAdapter` become the default adapter, or is wiring explicitly external pending a real C7/registry integration?

## Required changes

1. (F1) Wrap `create_task` in `try/except` (in `decide` or the adapter) and return a typed denial (e.g. `TASK_CREATION_REFUSED` or a new `TASK_IDENTITY_CONFLICT`) instead of propagating `InvalidTransitionError`/`ConcurrentWriteError`. This restores the fail-closed contract for non-identical re-activation.
2. Add a test for the different-authority re-activation of the same `ProposedGoal` (would currently crash; must return `activated=False`).
3. (F2) Remove or correct the dead `mandate_id == ""` / `standing_mission_id == ""` checks.
4. (Recommended) Add tests for scope mismatch, `content_digest` mismatch, and `MANDATE_UNAVAILABLE` branches.
5. (Recommended) Decide and document whether `clearance_digest` should be recorded in the Task constraints for traceability.

## Approval status

**APPROVE_WITH_CHANGES**

No authority bypass to `TaskService` was found, the default M0 path remains fail-closed, the 39 invariants pass, and the change stays within its stated boundary. F1 is a real defect relative to the module's own "fail-closed" and "idempotent" claims and should be fixed before integration/promotion; F2–F5 are minor and non-blocking.
