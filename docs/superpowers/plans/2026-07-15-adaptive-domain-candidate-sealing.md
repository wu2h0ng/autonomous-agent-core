# Adaptive Domain Candidate Sealing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Execution status:** Completed locally through `fb8593b10091953b61b6bea982953e3682215243`; Kimi follow-up review returned `TECHNICAL_APPROVE` with no blockers. The reviewed checkboxes below are preserved as the immutable plan text, not a live task tracker.

**Goal:** Deliver ADM-P1, a real local Product entry point that seals and lists immutable, provenance-bound R-channel `DomainCandidate` records without changing Task/Run/Workflow state or granting activation authority.

**Architecture:** Add a closed contract family in `agent_os_contracts`, a logically separate SQLite-backed `CandidateStore`, and a deterministic Product-owned sealer that validates task/run/principal/C7 scope, provenance, content digests, idempotency and parent-version CAS. Expose it through `AgentOSApplication` and a narrow HTTP endpoint. This slice intentionally stops before evaluation, promotion, priors, graph application or new-run activation.

**Tech Stack:** Python 3.12, Pydantic v2 frozen contracts, stdlib SQLite, existing `TaskService`/`CorrectionAuthority`, stdlib HTTP server, pytest, ruff, pyright.

## Global Constraints

- Authority: ADR-0057 plus parent `founder-decision-2026-07-15-accelerated-multi-lane-execution.md`.
- Claim ceiling: `IMPLEMENTED_LOCAL_CANDIDATE_SEALING_ONLY`.
- The draft carries one closed `requested_channel`. `R` may yield `CANDIDATE`, `ASK`, `UNKNOWN` or `NOT_SUPPORTED`; B/T/P are representable only as typed `NOT_SUPPORTED` records in ADM-P1; K/S and unknown channels fail decoding.
- Candidate storage is separate from `TaskEventStore`; sealing cannot append Task events or modify Task, Run, Workflow, workspace files, capability grants, policy, approval, audit or C7.
- Materialization run must already exist and match the draft; C7 halt fails closed.
- Every sealed candidate binds the observed C7 correction epoch vector. The sealer must reject a halt or epoch change immediately before the append linearization point; later slices must reject stale epochs again before evaluation or activation.
- No Research Track or `OntologyEngine` imports.
- No UI/CLI, Postgres, evaluation, promotion, `DomainPriorArtifact`, `TaskConfigurationSnapshot`, L3 code execution, migration or release in ADM-P1.
- Baseline full suite at exact base `e3cdacb`: `2183 passed, 14 skipped, 2 failed`; both failures are pre-existing result-presence assumptions in `test_lh1a_design.py` and `test_spine_e2e_4_scratch_cli.py`. Do not edit or hide them.

---

### Task 1: Freeze the R-channel contract family

**Files:**

- Create: `packages/contracts/src/agent_os_contracts/materialization.py`
- Modify: `packages/contracts/src/agent_os_contracts/__init__.py`
- Create: `tests/product/test_materialization_contracts.py`

**Interfaces:**

- Produces: `MaterializationOutcome`, `CandidateWriteChannel`, `RepresentationRelationClass`, `RepresentationPatchOperation`, `RepresentationPatch`, `CandidateProvenance`, `DomainCandidateDraft`, `DomainCandidate`.
- Consumes: existing `ContractModel`, `NonEmptyStr`, `UtcDateTime`, `Sha256Digest`, `content_digest`.

- [ ] **Step 1: Write failing contract tests**

Add tests that prove closed schemas, normalized evidence refs and non-self-referential digests:

```python
def test_representation_patch_digest_is_canonical() -> None:
    patch = RepresentationPatch(
        base_artifact_digest=None,
        operations=(
            RepresentationPatchOperation(
                operation_id="op:company-kind",
                operation="UPSERT",
                assertion_id="assertion:company-kind",
                subject_ref="entity:acme",
                predicate="rdf:type",
                object_ref="type:Company",
                relation_class=RepresentationRelationClass.ASSERTED,
                evidence_refs=("evidence:filing", "evidence:filing"),
                expected_prior_digest=None,
            ),
        ),
    )
    assert patch.channel is CandidateWriteChannel.R
    assert patch.operations[0].evidence_refs == ("evidence:filing",)
    assert len(patch.patch_digest()) == 64


@pytest.mark.parametrize("channel", ["K", "S", "X", "UNKNOWN"])
def test_candidate_contract_rejects_forbidden_channels(channel: str) -> None:
    with pytest.raises(ValidationError):
        RepresentationPatch.model_validate({"channel": channel, "operations": []})


def test_candidate_outcome_requires_exact_patch_shape() -> None:
    with pytest.raises(ValidationError, match="CANDIDATE requires"):
        DomainCandidateDraft(**valid_draft_values(outcome="CANDIDATE", representation_patch=None))
    with pytest.raises(ValidationError, match="must not carry"):
        DomainCandidateDraft(**valid_draft_values(outcome="UNKNOWN", representation_patch=valid_patch()))
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest tests/product/test_materialization_contracts.py -q
```

Expected: collection fails because `agent_os_contracts.materialization` does not exist.

- [ ] **Step 3: Implement the closed contracts**

Use only typed fields—no arbitrary executable JSON:

```python
class MaterializationOutcome(str, Enum):
    CANDIDATE = "CANDIDATE"
    ASK = "ASK"
    UNKNOWN = "UNKNOWN"
    NOT_SUPPORTED = "NOT_SUPPORTED"


class CandidateWriteChannel(str, Enum):
    B = "B"
    R = "R"
    T = "T"
    P = "P"


class RepresentationRelationClass(str, Enum):
    OBSERVED = "OBSERVED"
    ASSERTED = "ASSERTED"
    INFERRED = "INFERRED"
    CORRELATIONAL = "CORRELATIONAL"
    CAUSAL_CANDIDATE = "CAUSAL_CANDIDATE"
    INTERVENTION_VERIFIED = "INTERVENTION_VERIFIED"


class RepresentationPatchOperation(ContractModel):
    operation_id: NonEmptyStr
    operation: Literal["UPSERT", "RETRACT"]
    assertion_id: NonEmptyStr
    subject_ref: NonEmptyStr
    predicate: NonEmptyStr
    object_ref: NonEmptyStr
    relation_class: RepresentationRelationClass
    evidence_refs: tuple[NonEmptyStr, ...] = Field(min_length=1)
    expected_prior_digest: Sha256Digest | None = None


class RepresentationPatch(ContractModel):
    channel: Literal[CandidateWriteChannel.R] = CandidateWriteChannel.R
    base_artifact_digest: Sha256Digest | None = None
    operations: tuple[RepresentationPatchOperation, ...] = Field(min_length=1)

    def patch_digest(self) -> str:
        return content_digest(self)


class CandidateProvenance(ContractModel):
    source_id: NonEmptyStr
    source_ref: NonEmptyStr
    source_type: NonEmptyStr
    source_digest: Sha256Digest
    accessed_at: UtcDateTime
    effective_at: UtcDateTime
    license_or_terms_id: NonEmptyStr
    permitted_use: NonEmptyStr
    redistribution_allowed: bool
    custodian_verified_by: NonEmptyStr | None = None
    derivation_input_digests: tuple[Sha256Digest, ...] = ()
    output_patch_digest: Sha256Digest
    expires_at: UtcDateTime


class DomainCandidateDraft(ContractModel):
    task_id: NonEmptyStr
    materialization_run_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    submitted_by: NonEmptyStr
    mechanism_digest: Sha256Digest
    source_snapshot_digest: Sha256Digest
    parent_candidate_digest: Sha256Digest | None = None
    requested_channel: CandidateWriteChannel
    outcome: MaterializationOutcome
    representation_patch: RepresentationPatch | None = None
    provenance: tuple[CandidateProvenance, ...] = ()
    submitted_at: UtcDateTime


class DomainCandidate(ContractModel):
    candidate_id: NonEmptyStr
    candidate_version: int = Field(ge=1)
    candidate_digest: Sha256Digest
    payload_digest: Sha256Digest
    idempotency_key: Sha256Digest
    sealed_by: NonEmptyStr
    sealed_at: UtcDateTime
    observed_correction_epochs: CorrectionEpochVector
    draft: DomainCandidateDraft
```

Add validators:

- normalize/deduplicate sorted evidence and derivation digests;
- require `expires_at > accessed_at` and `effective_at <= accessed_at`;
- require `CANDIDATE` to carry one R patch and provenance;
- require `CANDIDATE` to use `requested_channel=R`; B/T/P require `NOT_SUPPORTED` and cannot carry a patch or provenance;
- require all abstention outcomes to carry neither patch nor provenance;
- ensure every provenance `output_patch_digest` equals the R patch digest;
- define one `domain_candidate_digest(payload)` helper that hashes the final canonical candidate payload after version assignment and before adding `candidate_digest`;
- validate that a constructed `DomainCandidate.candidate_digest` equals that helper's result, so version/digest drift is rejected;
- never compute candidate digest from a model that already contains `candidate_digest`.

Export every public type from `agent_os_contracts.__init__`.

- [ ] **Step 4: Run contract tests and adjacent contract tests**

Run:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest \
  tests/product/test_materialization_contracts.py \
  tests/product/test_authority_contracts.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the contract slice**

```bash
git add packages/contracts/src/agent_os_contracts/materialization.py \
  packages/contracts/src/agent_os_contracts/__init__.py \
  tests/product/test_materialization_contracts.py
git commit -m "feat(product): add domain candidate contracts"
```

### Task 2: Implement the isolated CandidateStore and deterministic sealer

**Files:**

- Create: `packages/os_core/src/agent_os_core/materialization_persistence.py`
- Create: `packages/os_core/src/agent_os_core/materialization.py`
- Modify: `packages/os_core/src/agent_os_core/errors.py`
- Modify: `packages/os_core/src/agent_os_core/__init__.py`
- Create: `tests/product/test_materialization_service.py`

**Interfaces:**

- Consumes: TaskService, CorrectionAuthority and TaskAggregate read paths only.
- Produces: `CandidateStore`, `SQLiteCandidateStore`, internal `CandidateSealRequest`, `DomainCandidateSealer.seal(principal, draft)`, `DomainCandidateSealer.list_for_task(principal, task_id)`.

- [ ] **Step 1: Write failing service tests**

Cover the real invariants, not constant-return success:

```python
def test_seal_is_idempotent_for_same_payload(running_task, sealer) -> None:
    first = sealer.seal(running_task.principal, running_task.draft)
    second = sealer.seal(running_task.principal, running_task.draft)
    assert second == first


def test_same_key_different_payload_is_conflict(running_task, sealer) -> None:
    sealer.seal(running_task.principal, running_task.draft)
    changed = running_task.draft.model_copy(
        update={"representation_patch": another_patch_same_source_and_mechanism()}
    )
    with pytest.raises(CandidateIdempotencyConflict):
        sealer.seal(running_task.principal, changed)


def test_stale_parent_is_rejected(running_task, sealer) -> None:
    first = sealer.seal(running_task.principal, running_task.draft)
    second = next_version_draft(first.candidate_digest)
    sealer.seal(running_task.principal, second)
    with pytest.raises(CandidateConcurrentWrite):
        sealer.seal(running_task.principal, sibling_of(first))


def test_sealing_is_blocked_by_c7(running_task, sealer, correction) -> None:
    correction.correct("task", running_task.task_id, "operator halt")
    with pytest.raises(CandidateSealingDenied, match="halted"):
        sealer.seal(running_task.principal, running_task.draft)


def test_final_digest_binds_transactionally_assigned_version(running_task, sealer) -> None:
    first = sealer.seal(running_task.principal, running_task.draft)
    second = sealer.seal(
        running_task.principal,
        next_version_draft(first.candidate_digest),
    )
    assert second.candidate_version == 2
    assert second.candidate_digest == domain_candidate_digest(
        second.model_dump(mode="json", exclude={"candidate_digest"})
    )


def test_epoch_change_before_append_fails_closed(running_task, store) -> None:
    correction = ScriptedCorrectionAuthority(
        snapshots=(ZERO_EPOCHS, ZERO_EPOCHS.model_copy(update={"run_epoch": 1})),
        halted=(False, False),
    )
    sealer = build_sealer(running_task.tasks, correction, store)
    with pytest.raises(CandidateSealingDenied, match="correction epoch changed"):
        sealer.seal(running_task.principal, running_task.draft)
```

The production service must not expose a test hook. `ScriptedCorrectionAuthority` is a test-only fake of the existing read interface and proves the second snapshot is enforced. Also test missing/expired provenance, source snapshot drift, wrong task/run/tenant/workspace/principal, `submitted_by` mismatch, task/run not exactly `RUNNING`, B/T/P `NOT_SUPPORTED`, K/S schema rejection and no TaskEvent append.

The B/T/P cases construct `DomainCandidateDraft(requested_channel=<channel>, outcome=NOT_SUPPORTED)` and must seal an inert abstention record. Any B/T/P `CANDIDATE`, patch or provenance fails contract validation. The derived idempotency key includes `requested_channel`, so different channel requests do not collide.

- [ ] **Step 2: Run service tests and verify RED**

Run:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest tests/product/test_materialization_service.py -q
```

Expected: imports fail because store and sealer do not exist.

- [ ] **Step 3: Add typed errors**

```python
class CandidateError(AgentOSCoreError):
    pass

class CandidateScopeMismatch(CandidateError):
    pass

class CandidateSealingDenied(CandidateError):
    pass

class CandidateIdempotencyConflict(CandidateError):
    pass

class CandidateConcurrentWrite(CandidateError):
    pass

class CandidateProvenanceError(CandidateError):
    pass
```

- [ ] **Step 4: Implement a separate append-only SQLite store**

`SQLiteCandidateStore` owns tables that are not Task events:

```sql
CREATE TABLE IF NOT EXISTS domain_candidates (
  tenant_id TEXT NOT NULL,
  workspace_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  candidate_version INTEGER NOT NULL,
  candidate_digest TEXT NOT NULL UNIQUE,
  parent_candidate_digest TEXT,
  idempotency_key TEXT NOT NULL,
  payload_digest TEXT NOT NULL,
  candidate_json TEXT NOT NULL,
  sealed_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, workspace_id, task_id, candidate_version),
  UNIQUE (tenant_id, workspace_id, idempotency_key)
);
```

Use a frozen internal value object that has no provisional version or digest:

```python
@dataclass(frozen=True, slots=True)
class CandidateSealRequest:
    candidate_id: str
    tenant_id: str
    workspace_id: str
    task_id: str
    idempotency_key: str
    payload_digest: str
    sealed_by: str
    sealed_at: datetime
    observed_correction_epochs: CorrectionEpochVector
    draft: DomainCandidateDraft
```

Expose only:

```python
class CandidateStore(Protocol):
    def get_by_idempotency(self, tenant_id: str, workspace_id: str, key: str) -> DomainCandidate | None: ...
    def latest(self, tenant_id: str, workspace_id: str, task_id: str) -> DomainCandidate | None: ...
    def append(self, request: CandidateSealRequest, *, expected_parent_digest: str | None) -> DomainCandidate: ...
    def list_for_task(self, tenant_id: str, workspace_id: str, task_id: str) -> tuple[DomainCandidate, ...]: ...
```

`append` is the sole version/digest linearization point. Under one `BEGIN IMMEDIATE` transaction it must:

1. look up `(tenant_id, workspace_id, idempotency_key)`; return the existing row only when its `payload_digest` matches, otherwise raise `CandidateIdempotencyConflict`;
2. read the latest row for the scoped task and compare its digest exactly with `expected_parent_digest`;
3. assign `candidate_version = latest.version + 1`, or `1` when no parent exists;
4. form the final payload from `CandidateSealRequest + candidate_version`, compute `candidate_digest = domain_candidate_digest(final_payload)`, validate a fresh `DomainCandidate`, and insert that exact JSON;
5. commit and return the exact stored model; on any integrity race, re-read the idempotency row and apply step 1 rather than returning last-write-wins.

There is no provisional `DomainCandidate`. Tests must assert that version 2 has a digest computed from version 2, and that concurrent identical submissions converge on one stored row.

- [ ] **Step 5: Implement deterministic sealing**

The sealer algorithm is fixed:

```python
IDEMPOTENCY_SCHEMA = "ADM-P1-IDEMPOTENCY-V1"
SEALER_ID = "system:domain-candidate-sealer:v1"
MATERIALIZATION_CAPABILITY = "domain.materialize"

def seal(self, principal: PrincipalIdentity, draft: DomainCandidateDraft) -> DomainCandidate:
    task = self._tasks.get_task(draft.task_id)
    self._require_scope_and_running_materialization(task, principal, draft)
    if self._correction.halted(draft.task_id, draft.materialization_run_id, MATERIALIZATION_CAPABILITY):
        raise CandidateSealingDenied("materialization is halted by correction authority")
    observed_epochs = self._correction.snapshot(
        draft.task_id,
        draft.materialization_run_id,
        MATERIALIZATION_CAPABILITY,
    )
    self._validate_r_only_and_provenance(draft)
    payload_digest = content_digest(draft)
    key = content_digest({
        "schema": IDEMPOTENCY_SCHEMA,
        "tenant_id": draft.tenant_id,
        "workspace_id": draft.workspace_id,
        "task_id": draft.task_id,
        "run_id": draft.materialization_run_id,
        "source_snapshot_digest": draft.source_snapshot_digest,
        "mechanism_digest": draft.mechanism_digest,
        "parent_candidate_digest": draft.parent_candidate_digest,
        "requested_channel": draft.requested_channel,
        "contract_schema_version": draft.schema_version,
    })
    existing = self._store.get_by_idempotency(draft.tenant_id, draft.workspace_id, key)
    if existing is not None:
        if existing.payload_digest != payload_digest:
            raise CandidateIdempotencyConflict("same derived key has different payload")
        return existing
    request = CandidateSealRequest(
        candidate_id=f"domain-candidate:{payload_digest[:24]}",
        tenant_id=draft.tenant_id,
        workspace_id=draft.workspace_id,
        task_id=draft.task_id,
        payload_digest=payload_digest,
        idempotency_key=key,
        sealed_by=SEALER_ID,
        sealed_at=self._clock(),
        observed_correction_epochs=observed_epochs,
        draft=draft,
    )
    current_epochs = self._correction.snapshot(
        draft.task_id,
        draft.materialization_run_id,
        MATERIALIZATION_CAPABILITY,
    )
    if current_epochs != observed_epochs or self._correction.halted(
        draft.task_id,
        draft.materialization_run_id,
        MATERIALIZATION_CAPABILITY,
    ):
        raise CandidateSealingDenied("correction epoch changed before candidate append")
    return self._store.append(
        request,
        expected_parent_digest=draft.parent_candidate_digest,
    )
```

No dict unpacking or provisional model is permitted. `DomainCandidateSealer.__init__` must accept a clock dependency. Tests must prove reopen persistence and digest stability.

`_require_scope_and_running_materialization` is exact, not interpretive. It rejects unless all are true:

- `task.task_id == draft.task_id`;
- `task.commitment` and `task.run` exist;
- `task.status is TaskStatus.RUNNING` and `task.run.status is RunStatus.RUNNING`;
- `draft.materialization_run_id == task.run.run_id`;
- principal, draft, commitment and run tenant/workspace IDs are identical;
- `draft.submitted_by == principal.principal_id`.

`DomainCandidateSealer.list_for_task(principal, task_id)` first loads the Task, applies the same principal/commitment tenant and workspace scope checks, then calls the store's tenant/workspace/task method. The store does not receive or interpret principals.

- [ ] **Step 6: Run service and persistence tests**

Run:

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest \
  tests/product/test_materialization_contracts.py \
  tests/product/test_materialization_service.py \
  tests/product/test_spine0_security_and_persistence.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit the service slice**

```bash
git add packages/os_core/src/agent_os_core/materialization.py \
  packages/os_core/src/agent_os_core/materialization_persistence.py \
  packages/os_core/src/agent_os_core/errors.py \
  packages/os_core/src/agent_os_core/__init__.py \
  tests/product/test_materialization_service.py
git commit -m "feat(product): seal immutable domain candidates"
```

### Task 3: Expose the Product entry point without generic-cache bypass

**Files:**

- Modify: `apps/api_server/app.py`
- Modify: `apps/api_server/server.py`
- Create: `tests/product/test_materialization_api.py`

**Interfaces:**

- Produces: `AgentOSApplication.seal_domain_candidate`, `AgentOSApplication.list_domain_candidates`.
- Produces HTTP: `POST /v1/tasks/{task_id}/domain-candidates:seal`, `GET /v1/tasks/{task_id}/domain-candidates`.

- [ ] **Step 1: Write failing HTTP integration tests**

Build a real running Task through the existing application, record its event sequence/status/workflow digest/workspace files, then call the endpoint.

```python
status, sealed = request_json(
    base,
    f"/v1/tasks/{task_id}/domain-candidates:seal",
    method="POST",
    body=valid_r_candidate_body(task_id=task_id, run_id=run_id),
)
assert status == 201
assert sealed["draft"]["materialization_run_id"] == run_id

status, listed = request_json(base, f"/v1/tasks/{task_id}/domain-candidates")
assert status == 200
assert [item["candidate_digest"] for item in listed["candidates"]] == [sealed["candidate_digest"]]
```

Required negative tests: wrong path task ID, cross-tenant principal, same derived key/different payload returns 409, C7 halt returns 403, stale parent returns 409, malformed/forbidden channel returns 400.

- [ ] **Step 2: Run API tests and verify RED**

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest tests/product/test_materialization_api.py -q
```

Expected: endpoint returns 404.

- [ ] **Step 3: Wire the application composition root**

In `AgentOSApplication.__init__` construct `SQLiteCandidateStore(database)` and `DomainCandidateSealer(self.tasks, self.correction, self.candidates)`. Add:

```python
def seal_domain_candidate(self, task_id: str, payload: dict[str, Any]) -> DomainCandidate:
    values = dict(payload)
    if values.get("task_id", task_id) != task_id:
        raise CandidateScopeMismatch("path task does not match candidate task")
    values["task_id"] = task_id
    values.setdefault("tenant_id", self.principal.tenant_id)
    values.setdefault("workspace_id", self.principal.workspace_id)
    values.setdefault("submitted_by", self.principal.principal_id)
    draft = DomainCandidateDraft.model_validate(values)
    return self.domain_candidates.seal(self.principal, draft)

def list_domain_candidates(self, task_id: str) -> tuple[DomainCandidate, ...]:
    return self.domain_candidates.list_for_task(self.principal, task_id)
```

- [ ] **Step 4: Add explicit HTTP routing and status mapping**

Candidate sealing must bypass the server's generic response cache because that cache does not bind payload digests. Add `_uses_generic_http_idempotency(path)` returning false for `domain-candidates:seal`, and do not store candidate responses there.

Map errors:

```python
CandidateScopeMismatch, CandidateSealingDenied -> 403
CandidateIdempotencyConflict, CandidateConcurrentWrite -> 409
CandidateProvenanceError, ValidationError, ValueError -> 400
TaskNotFoundError -> 404
```

The service-derived idempotency contract remains authoritative even when the HTTP header is repeated or absent.

- [ ] **Step 5: Prove no Task/Run/Graph/workspace mutation**

The integration test captures before/after:

- TaskEvent sequence and exact event IDs;
- TaskStatus and RunStatus;
- Run ID and WorkflowGraph digest;
- workspace file inventory/content digest;
- grants and correction snapshot.

All values must be identical after sealing and listing.

- [ ] **Step 6: Run API and adjacent surface tests**

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest \
  tests/product/test_materialization_api.py \
  tests/product/test_api_surface.py \
  tests/product/test_product_research_boundary.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit the Product entry point**

```bash
git add apps/api_server/app.py apps/api_server/server.py \
  tests/product/test_materialization_api.py
git commit -m "feat(product): expose domain candidate sealing API"
```

### Task 4: Run bypass, restart and full Product verification

**Files:**

- Modify if a missing bypass case is found: `tests/product/test_materialization_service.py`
- Modify if a missing surface case is found: `tests/product/test_materialization_api.py`
- Do not modify unrelated failing Product-eval tests.

- [ ] **Step 1: Run mutation-style bypass checks**

Temporarily verify the tests fail if the implementation is locally altered to:

- return a constant candidate;
- omit the C7 check;
- accept a stale parent;
- append a TaskEvent;
- use generic HTTP idempotency only;
- ignore tenant/workspace scope.

Restore the implementation after each check; no mutation remains in Git.

- [ ] **Step 2: Verify SQLite restart behavior**

Create application A, seal candidate, close both stores, create application B on the same database, list and reseal. Assert same candidate digest/version and no duplicate row.

- [ ] **Step 3: Run targeted acceptance**

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest \
  tests/product/test_materialization_contracts.py \
  tests/product/test_materialization_service.py \
  tests/product/test_materialization_api.py \
  tests/product/test_product_research_boundary.py -q
```

Expected: all pass.

- [ ] **Step 4: Run the complete Product suite and quality tools**

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest tests/product -q
../../.venv/bin/python -m ruff check \
  apps packages/os_core/src packages/contracts/src tests/product
../../.venv/bin/python -m pyright \
  apps packages/os_core/src packages/contracts/src
```

Expected: Product suite passes; ruff and pyright report zero errors. Do not claim the repository-wide suite is green while its two recorded Product-eval baseline failures remain.

- [ ] **Step 5: Commit any test-only hardening**

```bash
git add tests/product/test_materialization_service.py \
  tests/product/test_materialization_api.py
git diff --cached --quiet || git commit -m "test(product): harden candidate sealing boundaries"
```

### Task 5: Record exact implementation truth

**Files:**

- Modify: `docs/CURRENT_STATE.yaml`
- Modify: `codebase_index.md`
- Create: `docs/product/PM-ADM-P1-CANDIDATE-SEALING-2026-07-15.md`

- [ ] **Step 1: Write the acceptance record from actual evidence**

Record exact HEAD, commands, pass counts, entry point, contract, failures, integration and the unchanged Task/Run/Graph evidence. Use:

```text
IMPLEMENTED_LOCAL_CANDIDATE_SEALING_ONLY
```

Do not use `adaptive competence`, `domain learned`, `self-improvement`, `Product Alpha` or `autonomy`.

- [ ] **Step 2: Update CURRENT_STATE and index minimally**

Move P-CORE-ADAPT-1 from implementation-plan status only after the target tests and Product suite pass. Keep evaluation, promotion, activation, priors, training, SPINE-1 and release as unimplemented/gated.

- [ ] **Step 3: Verify documentation and Git state**

```bash
git diff --check
rg -n "adaptive competence|self-improv|general autonomy|Product Alpha" \
  docs/product/PM-ADM-P1-CANDIDATE-SEALING-2026-07-15.md \
  docs/CURRENT_STATE.yaml codebase_index.md
git status --short
```

Expected: no whitespace errors; prohibited claim scan has no unauthorized positive assertion; only scoped files are changed.

- [ ] **Step 4: Commit the acceptance truth**

```bash
git add docs/CURRENT_STATE.yaml codebase_index.md \
  docs/product/PM-ADM-P1-CANDIDATE-SEALING-2026-07-15.md
git commit -m "docs(product): record ADM-P1 candidate sealing evidence"
```

## Deferred successor slices

The following require new independently reviewable tasks and are not implementation leftovers in ADM-P1:

- ADM-P2: independent `EvaluationReceipt` and evaluator isolation;
- ADM-P3: Product-owned promotion decisions and immutable optional priors;
- ADM-P4: `TaskConfigurationSnapshot`, narrowing-only grant sets and new-Task activation;
- ADM-P5: materializer acquisition engine and one-way Research observation adapter;
- Research falsifier: two-domain or black-box transfer evidence against direct/retrieval/thin-prior baselines.
