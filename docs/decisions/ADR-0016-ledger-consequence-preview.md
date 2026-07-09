# ADR-0016: Evidence-bound ledger consequence preview (symbolic world-model-lite)

- Status: **DRAFT / Proposed — awaiting CTO gate. Not merged, not pushed.**
- Date: 2026-07-10
- Layer: deployment (product runtime contract + evidence chain + approval detail surface)
- Release state: written under `DEPLOYMENT_PUSH: HOLD`; this ADR authorizes nothing about `origin/main`,
  tags, product-main promotion, or external claims. Product-main promotion is a separate CTO gate.
- Slice: P2-B (test-first) built ON TOP of P2-A head `e445992`, branch
  `feat/p2b-ledger-consequence-preview-20260710`.
- Relation: strengthens **ADR-0008** (the outcome moat = governed action closed to measured outcome +
  compounding per-tenant history) by making that history visible at decision time. Consistent with
  ADR-0014 (human choice set), ADR-0015 (rubber-stamp analytics), ADR-0012 (R4/R5 default proposal-only),
  and the OS-Core domain-independence boundary (repo CLAUDE.md #3/#15/#18).

## Context

An approver deciding an action_record proposal today decides **blind**: the approval surface shows the
proposed action and its choice set (ADR-0014), but not the action's own track record. The durable
`action_records` ledger already records every governed execution per tenant, yet nothing surfaces "this
action type has run N times before, M of which resolved cleanly." The compounding-history half of the
ADR-0008 moat exists in the ledger but never reaches the human at the moment of decision.

We want to turn "decide blind" into "decide with the action's track record" — **without** crossing into
prediction. Predictive consequence modelling (a learned model over history, a probability of success) is
a separately-gated future capability, explicitly NOT this slice. P2-B delivers an **honest count the
human reads**; the disposer/human still decides.

## Decision

### 1. A typed, symbolic `ConsequencePreview` contract

`agent_os_contracts.ConsequencePreview{action_type, prior_executions:int, resolved_intended:int,
resolved_other:int, last_outcomes:tuple[str,...], available:bool}`. It is a **count, not a prediction**:
no model, no probability, no score. `available=False` (with zero counts) is the honest signal for "no
prior history OR the ledger could not be read" — a novel or unreadable action renders "no prior history",
never a fabricated `0/0` dressed as real data. The surface can therefore distinguish "no history" from
"0 of N resolved."

### 2. Derivation is domain-independent and lives in OS Core; the ledger shape does not

`agent_os_core.consequence_preview` owns the **generic** half: a read-only `ActionHistoryPort`
(`outcomes_for(action_type, tenant_id) -> tuple[str, ...]`, oldest→newest, tenant-scoped) and a pure
`build_consequence_preview(...)` that only ever **counts generic outcome strings**. OS Core stays unaware
of the `action_records` ledger (which is connector-specific state, per `repositories.py`): a caller
injects a concrete adapter.

The concrete `ActionRecordHistoryAdapter` (in the `action_record` connector package — the true owner of
the record shape, and import-light so the memory backend stays SQLAlchemy-free) is the **only** place that
knows the ledger record shape. Mapping uses the ledger's OWN signals, no business semantics:

- a record → `INTENDED_EXECUTION_OUTCOME` (`"executed"`, a clean ACK-observed execution), UNLESS
- its write ACK was lost (`uncertain_execution_count > 0`) → `"execution_uncertain"` (executed, but did
  not cleanly resolve to the intended outcome).

So `prior_executions` = ledger records for that `action_type`; `resolved_intended` = the clean ones;
`resolved_other` = the ACK-uncertain remainder; `last_outcomes` = the most-recent K. Counts are read
**live from the ledger** every derivation — there is deliberately **no parallel cached counter** to drift.

**Keying by `action_type` only** (not `target`): the durable ledger records `action_type` as a
first-class column; it does not record a `target` as a first-class field (only inside the opaque,
domain-specific `parameters` JSON). Reaching into `parameters` for a target would put domain assumptions
into a generic reader, so target-narrowing is deferred until the ledger records target first-class. This
is an honest limitation, documented, not a silent gap.

### 3. Attached AS evidence, and snapshotted durably for the surface

On proposal build (when a history port is wired), the runtime derives the preview from
`proposal.action_type` + the run's `tenant_id` and attaches the **same** object to BOTH the
`ActionProposal` (`+consequence_preview`) and the `EvidenceChain` (`+consequence_preview`) — it is
evidence ABOUT the action, auditable in the chain, not decorative free text. It is also snapshotted onto
the `ApprovalRecord` (mirroring the ADR-0014 alternatives snapshot), so `GET /approvals/{id}` renders the
track record durably even after the approval-resume context is deleted post-execution.

### 4. Fail-safe, advisory, never a gate

`build_consequence_preview` wraps the port read: any ledger read error degrades to `available=False` —
never a crash, never a fabricated count. The approval is still creatable; the preview never blocks a
decision. When no history port is wired the proposal simply carries no preview (`None`), so existing
runs and tests are unchanged (backward compatible).

## Boundaries preserved

- **OS-Core domain independence.** The derivation counts generic outcome strings; the connector adapter
  owns the ledger shape. No Customer-0 / content-commerce / domain semantics enter Core.
- **R4/R5 proposal-only** unchanged. This slice adds a read-only, symbolic advisory; it changes nothing
  about what may auto-execute. The action still halts for the human/disposer.
- **No prediction / no learned model.** Honest counts only. Predictive consequence modelling remains a
  future, separately-gated capability, explicitly out of scope here.
- **Runtime holds only a reader.** The history port READS the ledger; the runtime never writes it.
- **Tenant isolation.** The durable `SqlActionRecordStore` is tenant-scoped (`records(*, tenant_id)`), so
  one tenant's history never counts toward another's preview (proven in `test_action_history.py`). The
  in-memory dev store is single-tenant by construction; the adapter detects which at construction time.
- **Backward compatibility.** All new fields default to `None`/empty; pre-P2-B payloads deserialize
  unchanged (JSON `payload` column — no schema migration).

## Contract changes (surface)

- `agent_os_contracts`: `+ConsequencePreview`; `ActionProposal +consequence_preview`;
  `EvidenceChain +consequence_preview` (both optional, default `None`).
- `agent_os_core.consequence_preview` (new): `+ActionHistoryPort` (ABC), `+build_consequence_preview`,
  `+INTENDED_EXECUTION_OUTCOME`.
- `action_record.action_history` (new): `+ActionRecordHistoryAdapter` (implements `ActionHistoryPort`).
- `agent_os_core.approval_lite.ApprovalRecord`: `+consequence_preview`; `create_pending` threads it.
- `agent_os_core.trusted_loop.TrustedLoopRuntime`: `+action_history_port` (optional); derives + attaches
  the preview at proposal build; snapshots it into the pending approval; records a `consequence_preview`
  Trace event.
- HTTP: `GET /approvals/{approval_id}` response `+consequence_preview` (`ConsequencePreviewItem`);
  `openapi.json` + frontend `schema.d.ts` regenerated.
- Persistence: `approval_{to,from}_payload` extended (JSON payload; no migration).
- Composition: `ContentCommerceRuntimeFactory` retains the action_record store and wires
  `build_action_history_port()` into the runtime (both backends).

## Falsifier / value

The preview makes the ADR-0008 outcome-moat history **usable at decision time**: an approver can see a
low `resolved_intended / prior_executions` ratio before repeating a poorly-resolving action. The tests
are bypass-detecting by construction — the 5/3/2 split (`test_preview_counts_derived_from_ledger`) and the
end-to-end `0 → 1` shift after a real ledger write (`test_approval_detail_exposes_ledger_consequence_preview`)
can only come from reading the ledger; a constant or ignored-ledger implementation fails them. Turning
these honest counts INTO a predictive signal is a later, separately-gated step, not a claim made here.
