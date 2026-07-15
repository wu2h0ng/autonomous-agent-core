# ADM-P3 Promotion Decision and Optional Prior Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Review:** Kimi Code `SPEC_APPROVE`, session `session_4908b8a8-a26a-49bc-bb96-7ecf55ae2fd6`; the three required fixes below are binding.

**Goal:** Add a Product-owned, deterministic and append-only candidate-promotion decision seam that consumes only one ADM-P1 candidate and its complete ADM-P2 receipt chain, while atomically deriving an inert immutable optional prior only for a registered-policy `PROMOTE` result.

**Architecture:** A closed command names route/scope and CAS heads but contains no verdict, threshold, receipt subset or prior bytes. The service loads the candidate and complete receipt chain, enforces fifth-party authority and C7, and delegates to a versioned digest-bound Product policy. A shared SQLite evaluation/promotion ledger rechecks the receipt head and parent decision in one transaction, recomputes the policy result, appends the decision and, only for `PROMOTE`, appends the inert prior before commit. Production policy V1 intentionally returns `DEFER` for every current ADM-P2 chain because ADM-P2 does not mechanically prove evidence-byte custody or evaluator independence.

**Tech Stack:** Python 3.11+, Pydantic v2 frozen contracts, stdlib `sqlite3`, existing `TaskService`/`CorrectionGuard`/`CapabilityGrant`, pytest, ruff, pyright.

## Global Constraints

- Exact implementation base: `9673c4bd9b5ca101c8bee51e806c20d0cb74a746`.
- Work only on `codex/adm-p3-optional-domain-prior-20260715` in its isolated worktree.
- Do not implement until delegated CTO and independent technical review approve the exact Goal Card, Architecture Brief and this plan.
- Semantic inputs are only the exact ADM-P1 `DomainCandidate` and the complete ADM-P2 `CandidateEvaluationReceipt` chain.
- The caller cannot submit verdict, threshold, score override, reason codes, receipt subset, policy, prior payload or activation instruction.
- Product policy is closed, deterministic, versioned, digest-bound and registered in code.
- Production `ADM-P3-POLICY-V1` returns `DEFER` only; opaque evidence refs or identity labels never prove custody or independence.
- Promoter, candidate builder, candidate sealer, every evaluator and every receipt recorder are distinct identities.
- Promotion grant uses separate `capability_id="domain.candidate.promote"` and
  `capability_version="1"`; Commitment authority scope is the raw capability ID.
- No policy may return `PROMOTE` for an empty receipt chain; contracts/store reject it
  independently of policy behavior.
- `SQLiteAdaptationLedger` is the connection owner; internally created ledgers are
  owner-closed, injected shared ledgers are borrowed and never closed by the borrower.
- Decision history and prior history are append-only, derived-idempotent and parent-CAS protected.
- `PROMOTE` plus prior is one SQLite transaction; `REJECT`/`DEFER` produce no prior.
- No evaluator execution, provider/tool call, workspace write, Task event, current Task/Run/Workflow/configuration mutation or activation.
- No Research import, L4/L5, self-approval, migration, push, merge or release.
- Implementation claim ceiling: `IMPLEMENTED_LOCAL_ADM_P3_INFRASTRUCTURE_ONLY / PRODUCTION_POLICY_V1_ALL_DEFER / NO_ACTIVATION`.

---

## File structure

Implementation files:

- Modify `packages/contracts/src/agent_os_contracts/materialization.py` and `__init__.py` for closed contracts/exports.
- Create `packages/os_core/src/agent_os_core/materialization_ledger.py` for the shared SQLite connection/lock.
- Modify `materialization_evaluation_persistence.py` to accept that ledger without changing ADM-P2 semantics.
- Create `materialization_promotion_policy.py`, `materialization_promotion_persistence.py` and `materialization_promotion.py`.
- Modify `packages/os_core/src/agent_os_core/errors.py` and `__init__.py`.
- Modify `apps/api_server/app.py` and `apps/api_server/server.py`.

Test files:

- `tests/product/test_materialization_promotion_contracts.py`
- `tests/product/test_materialization_promotion_policy.py`
- `tests/product/test_materialization_promotion_persistence.py`
- `tests/product/test_materialization_promotion_service.py`
- `tests/product/test_materialization_promotion_api.py`

After exact-diff approval, update branch-local evidence only:

- `docs/product/PM-ADM-P3-PROMOTION-AND-OPTIONAL-PRIOR-2026-07-15.md`
- `docs/CURRENT_STATE.yaml`
- `codebase_index.md`

Do not edit parent/root truth files from this worktree.

---

### Task 1: Closed promotion and prior contracts

**Files:**

- Modify: `packages/contracts/src/agent_os_contracts/materialization.py`
- Modify: `packages/contracts/src/agent_os_contracts/__init__.py`
- Test: `tests/product/test_materialization_promotion_contracts.py`

**Interfaces:**

- Consumes: existing `DomainCandidate`, `CandidateEvaluationReceipt`, `RepresentationPatch`, `CandidateProvenance`, `CorrectionEpochVector`, `Sha256Digest`.
- Produces: `CandidatePromotionCommand`, `CandidatePromotionDisposition`, `CandidatePromotionDecision`, `DomainPriorArtifact`, `CandidatePromotionResult`, and two canonical digest helpers.

- [ ] **Step 1: Write failing tests that reject caller-owned decision semantics**

```python
@pytest.mark.parametrize(
    "forbidden",
    (
        {"disposition": "PROMOTE"},
        {"threshold": 0.9},
        {"evaluation_receipt_digests": (DIGEST_A,)},
        {"reason_codes": ("CALLER_REASON",)},
        {"policy_version": "caller-policy"},
        {"prior": {"state": "ACTIVE"}},
        {"activate": True},
    ),
)
def test_promotion_command_forbids_caller_decision_fields(
    forbidden: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        CandidatePromotionCommand(**_command_values(), **forbidden)
```

Also test invalid SHA heads, empty identifiers, duplicate decision receipt digests,
decision/head mismatch, active prior literals and mutation-sensitive decision/prior
digests.

- [ ] **Step 2: Run the contract test and confirm RED**

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest \
  tests/product/test_materialization_promotion_contracts.py -q
```

Expected: import/collection failure because ADM-P3 contracts do not exist.

- [ ] **Step 3: Add the exact closed contract family**

```python
class CandidatePromotionDisposition(str, Enum):
    REJECT = "REJECT"
    DEFER = "DEFER"
    PROMOTE = "PROMOTE"


class CandidatePromotionCommand(ContractModel):
    candidate_digest: Sha256Digest
    candidate_task_id: NonEmptyStr
    promotion_task_id: NonEmptyStr
    promotion_run_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    expected_evaluation_head_digest: Sha256Digest | None = None
    expected_parent_promotion_digest: Sha256Digest | None = None


class CandidatePromotionDecision(ContractModel):
    promotion_id: NonEmptyStr
    promotion_version: int = Field(ge=1)
    promotion_digest: Sha256Digest
    payload_digest: Sha256Digest
    idempotency_key: Sha256Digest
    candidate_digest: Sha256Digest
    candidate_task_id: NonEmptyStr
    promotion_task_id: NonEmptyStr
    promotion_run_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    evaluation_head_digest: Sha256Digest | None = None
    evaluation_receipt_digests: tuple[Sha256Digest, ...] = ()
    receipt_chain_digest: Sha256Digest
    disposition: CandidatePromotionDisposition
    reason_codes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    policy_version: NonEmptyStr
    policy_digest: Sha256Digest
    decided_by: NonEmptyStr
    decided_at: UtcDateTime
    observed_correction_epochs: CorrectionEpochVector
    parent_promotion_digest: Sha256Digest | None = None
    prior_artifact_id: NonEmptyStr | None = None


class DomainPriorArtifact(ContractModel):
    prior_artifact_id: NonEmptyStr
    prior_version: int = Field(ge=1)
    prior_digest: Sha256Digest
    payload_digest: Sha256Digest
    parent_prior_digest: Sha256Digest | None = None
    candidate_digest: Sha256Digest
    candidate_payload_digest: Sha256Digest
    promotion_digest: Sha256Digest
    evaluation_head_digest: Sha256Digest
    evaluation_receipt_digests: tuple[Sha256Digest, ...] = Field(min_length=1)
    receipt_chain_digest: Sha256Digest
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    representation_patch: RepresentationPatch
    provenance: tuple[CandidateProvenance, ...] = Field(min_length=1)
    policy_digest: Sha256Digest
    published_by: NonEmptyStr
    published_at: UtcDateTime
    observed_correction_epochs: CorrectionEpochVector
    state: Literal["INERT"] = "INERT"
    activation_authority: Literal["NONE"] = "NONE"
    uncertainty_behavior: Literal["PRESERVE"] = "PRESERVE"


class CandidatePromotionResult(ContractModel):
    decision: CandidatePromotionDecision
    prior: DomainPriorArtifact | None = None
```

Validators enforce ordered unique receipt digests; head equals last receipt (or both are
empty); `PROMOTE` requires a non-empty receipt tuple, non-null head, prior ID and result
prior; other dispositions forbid both;
prior/decision candidate, scope, chain, policy, actor and C7 bindings match; canonical
digest helpers exclude only their own digest fields.

- [ ] **Step 4: Run contract and adjacent ADM-P1/P2 tests**

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest \
  tests/product/test_materialization_contracts.py \
  tests/product/test_materialization_evaluation_contracts.py \
  tests/product/test_materialization_promotion_contracts.py -q
```

Expected: all pass; every final-field mutation breaks validation.

- [ ] **Step 5: Commit the contract slice**

```bash
git add packages/contracts/src/agent_os_contracts/materialization.py \
  packages/contracts/src/agent_os_contracts/__init__.py \
  tests/product/test_materialization_promotion_contracts.py
git commit -m "feat(product): define ADM-P3 promotion contracts"
```

---

### Task 2: Versioned deterministic Product policy

**Files:**

- Create: `packages/os_core/src/agent_os_core/materialization_promotion_policy.py`
- Test: `tests/product/test_materialization_promotion_policy.py`

**Interfaces:**

- Consumes: exact candidate plus complete ordered receipt tuple.
- Produces: `PromotionReduction`, `ProductPromotionPolicy`, `PromotionPolicyRegistry`, `PromotionPolicyV1`, `PROMOTION_POLICY_V1_SPEC`, `PROMOTION_POLICY_V1_DIGEST`.

- [ ] **Step 1: Write exhaustive V1 all-DEFER tests**

```python
@pytest.mark.parametrize(
    "dispositions",
    itertools.product(tuple(CandidateEvaluationDisposition), repeat=3),
)
def test_v1_never_promotes_current_adm_p2_receipts(
    dispositions: tuple[CandidateEvaluationDisposition, ...],
) -> None:
    receipts = tuple(
        _receipt(index + 1, disposition)
        for index, disposition in enumerate(dispositions)
    )
    reduction = PromotionPolicyV1().reduce(_candidate(), receipts)
    assert reduction.disposition is CandidatePromotionDisposition.DEFER
```

Test exact reason grammar for empty/pass/fail/invalid/unresolved observations. Every
chain remains `DEFER`; multiple names/providers/digests and plausible `artifact:` refs
must not change the result. Test immutable registry rejection of duplicate, unknown or
mismatched version/digest. Add a defective test policy that proposes `PROMOTE` for an
empty chain and prove the persistence boundary rejects it.

- [ ] **Step 2: Run the policy test and confirm RED**

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest \
  tests/product/test_materialization_promotion_policy.py -q
```

Expected: import failure because the policy module does not exist.

- [ ] **Step 3: Implement the pure closed policy**

```python
@dataclass(frozen=True, slots=True)
class PromotionReduction:
    disposition: CandidatePromotionDisposition
    reason_codes: tuple[str, ...]


class ProductPromotionPolicy(Protocol):
    version: str
    digest: str

    def reduce(
        self,
        candidate: DomainCandidate,
        receipts: tuple[CandidateEvaluationReceipt, ...],
    ) -> PromotionReduction:
        pass


PROMOTION_POLICY_V1_SPEC = {
    "schema": "ADM-P3-PROMOTION-POLICY-SPEC-V1",
    "version": "ADM-P3-POLICY-V1",
    "input": "FULL_ADM_P2_RECEIPT_CHAIN",
    "reject_if": "UNREACHABLE_WITH_ADM_P2_V1",
    "promote_if": "UNREACHABLE_WITH_ADM_P2_V1",
    "default_disposition": "DEFER",
    "required_missing_proofs": (
        "EVIDENCE_BYTES_CUSTODY",
        "EVALUATOR_INDEPENDENCE",
    ),
}
PROMOTION_POLICY_V1_DIGEST = content_digest(PROMOTION_POLICY_V1_SPEC)
```

The reducer has no clock, store, provider, model, tool, randomness or mutable
configuration. The registry resolves only an exact `(version, digest)`.

- [ ] **Step 4: Run policy and lint checks**

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest \
  tests/product/test_materialization_promotion_policy.py -q
../../.venv/bin/python -m ruff check \
  packages/os_core/src/agent_os_core/materialization_promotion_policy.py \
  tests/product/test_materialization_promotion_policy.py
```

Expected: all tests pass and ruff is clean.

- [ ] **Step 5: Commit the policy slice**

```bash
git add packages/os_core/src/agent_os_core/materialization_promotion_policy.py \
  tests/product/test_materialization_promotion_policy.py
git commit -m "feat(product): add fail-closed ADM-P3 policy"
```

---

### Task 3: Shared ledger and atomic promotion persistence

**Files:**

- Create: `packages/os_core/src/agent_os_core/materialization_ledger.py`
- Modify: `packages/os_core/src/agent_os_core/materialization_evaluation_persistence.py`
- Create: `packages/os_core/src/agent_os_core/materialization_promotion_persistence.py`
- Test: `tests/product/test_materialization_promotion_persistence.py`

**Interfaces:**

- Consumes: exact candidate, complete receipt chain, policy registry and Product-derived record request.
- Produces: `SQLiteAdaptationLedger`, `CandidatePromotionRecordRequest`, `CandidatePromotionStore`, `SQLiteCandidatePromotionStore`, chain/payload/idempotency digest helpers.

- [ ] **Step 1: Write failing chain, CAS and atomicity tests**

Create exact tests named:

- `test_store_rejects_receipt_subset_even_when_subset_head_is_valid`;
- `test_store_rejects_stale_latest_evaluation_head`;
- `test_store_rejects_gap_reorder_parent_break_and_cross_scope_receipt`;
- `test_exact_old_replay_returns_original_before_parent_cas`;
- `test_same_derived_key_with_changed_payload_conflicts`;
- `test_new_decision_requires_latest_parent_and_new_receipt_head`;
- `test_reject_and_defer_never_insert_prior`;
- `test_registered_test_promote_policy_inserts_decision_and_prior_atomically`;
- `test_sqlite_abort_on_prior_insert_rolls_back_promote_decision`;
- `test_restart_preserves_decision_prior_and_digests`.

The test-only promote policy is deterministic, has a fixed canonical spec/digest and is
defined/registered only in this test module. For rollback, install a temporary SQLite
trigger that raises `ABORT` on `domain_prior_artifacts` insert, then assert both tables
remain unchanged. Do not add a production failure flag.

- [ ] **Step 2: Run persistence tests and confirm RED**

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest \
  tests/product/test_materialization_promotion_persistence.py -q
```

Expected: import failure because the ledger/store modules do not exist.

- [ ] **Step 3: Add the shared SQLite ledger without changing ADM-P2 bytes**

```python
class SQLiteAdaptationLedger:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self.lock = RLock()
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")

    def close(self) -> None:
        with self.lock:
            self.connection.close()
```

Change `SQLiteCandidateEvaluationStore` to accept
`ledger: SQLiteAdaptationLedger | None = None`, create one only when absent, initialize
its existing table on `ledger.connection`, record `_owns_ledger = ledger is None`, and
expose read-only `.ledger`. Its `close()` closes the ledger only when `_owns_ledger` is
true. `SQLiteCandidatePromotionStore` follows the same owner/borrower rule. A borrowed
store close must leave the shared ledger usable by its owner and sibling store. Existing
ADM-P2 transaction order, signatures, JSON and digests must remain unchanged.

- [ ] **Step 4: Implement complete-chain digest and one atomic append**

```python
@dataclass(frozen=True, slots=True)
class CandidatePromotionRecordRequest:
    command: CandidatePromotionCommand
    candidate: DomainCandidate
    receipt_chain_digest: str
    policy_version: str
    policy_digest: str
    reduction: PromotionReduction
    payload_digest: str
    idempotency_key: str
    decided_by: str
    decided_at: datetime
    observed_correction_epochs: CorrectionEpochVector


class CandidatePromotionStore(Protocol):
    def append(
        self,
        request: CandidatePromotionRecordRequest,
    ) -> CandidatePromotionResult:
        pass

    def list_decisions(
        self,
        tenant_id: str,
        workspace_id: str,
        candidate_digest: str,
    ) -> tuple[CandidatePromotionDecision, ...]:
        pass

    def list_priors(
        self,
        tenant_id: str,
        workspace_id: str,
        candidate_digest: str,
    ) -> tuple[DomainPriorArtifact, ...]:
        pass
```

`append` uses one `BEGIN IMMEDIATE` transaction in this fixed order:

1. reload all evaluation rows ordered by version;
2. validate contiguous versions, parent links, candidate/task/scope and canonical
   receipt models; compare full-chain digest and expected head;
3. resolve idempotency first and return only an exact payload match;
4. require exact latest parent-decision CAS and a changed receipt head for new decision;
5. resolve exact registered policy and recompute reduction over the reloaded chain;
6. reject `PROMOTE` if the reloaded chain is empty, regardless of policy output;
7. assign decision version and deterministic prior ID only for `PROMOTE`, then insert;
8. for `PROMOTE`, assign prior version/parent, derive the inert prior from candidate R
   patch/provenance, validate and insert;
9. commit; roll back the entire transaction on every exception.

Tables use unique decision/prior digests, per-candidate version primary keys and unique
derived decision idempotency keys. No update/delete method exists. Prior version/parent
are transaction-assigned and never caller-selected.

Implement these exact digest inputs:

```python
receipt_chain_digest = content_digest({
    "schema": "ADM-P3-RECEIPT-CHAIN-V1",
    "candidate_digest": candidate.candidate_digest,
    "receipts": receipts,
})

payload_digest = content_digest({
    "schema": "ADM-P3-BOUND-PAYLOAD-V1",
    "command": command,
    "candidate": candidate,
    "receipt_chain_digest": receipt_chain_digest,
    "policy_version": policy.version,
    "policy_digest": policy.digest,
    "reduction": reduction,
    "decided_by": principal.principal_id,
})

idempotency_key = content_digest({
    "schema": "ADM-P3-IDEMPOTENCY-V1",
    "tenant_id": command.tenant_id,
    "workspace_id": command.workspace_id,
    "candidate_digest": command.candidate_digest,
    "promotion_task_id": command.promotion_task_id,
    "promotion_run_id": command.promotion_run_id,
    "evaluation_head": command.expected_evaluation_head_digest,
    "parent_promotion": command.expected_parent_promotion_digest,
    "policy_version": policy.version,
    "policy_digest": policy.digest,
    "decided_by": principal.principal_id,
    "contract_schema_version": command.schema_version,
})
```

Callers cannot provide any of these digests.

- [ ] **Step 5: Run persistence and ADM-P2 regression tests**

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest \
  tests/product/test_materialization_evaluation_persistence.py \
  tests/product/test_materialization_promotion_persistence.py -q
```

Expected: all pass and ADM-P2 receipt bytes/digests are stable.

- [ ] **Step 6: Commit the persistence slice**

```bash
git add packages/os_core/src/agent_os_core/materialization_ledger.py \
  packages/os_core/src/agent_os_core/materialization_evaluation_persistence.py \
  packages/os_core/src/agent_os_core/materialization_promotion_persistence.py \
  tests/product/test_materialization_promotion_persistence.py
git commit -m "feat(product): persist ADM-P3 decisions atomically"
```

---

### Task 4: Product promotion service, fifth-party separation and C7

**Files:**

- Create: `packages/os_core/src/agent_os_core/materialization_promotion.py`
- Modify: `packages/os_core/src/agent_os_core/errors.py`
- Modify: `packages/os_core/src/agent_os_core/__init__.py`
- Test: `tests/product/test_materialization_promotion_service.py`

**Interfaces:**

- Consumes: `TaskService`, `CorrectionGuard`, candidate/evaluation/promotion stores, exact grant mapping, production policy registry.
- Produces: `DomainCandidatePromotionService`, `PROMOTION_CAPABILITY = "domain.candidate.promote"`, typed promotion errors.

- [ ] **Step 1: Write failing authority and non-mutation tests**

Add one test for each bypass:

- wrong candidate route Task/digest, non-`CANDIDATE`, or non-R candidate;
- promotion Task/Run absent, non-running, same as candidate or any evaluation Task/Run;
- wrong tenant/workspace;
- promoter role `WORKER`, `MODEL` or `PLUGIN`;
- Goal creator or Commitment acceptor mismatch;
- missing authority scope;
- missing/revoked/expired/wrong-version/wrong-principal/wrong-scope promotion grant;
- combined `capability_id="domain.candidate.promote@1"` or combined Commitment scope;
- promoter equals candidate builder, fixed sealer, any evaluator or any recorder;
- command head is not exact latest receipt head;
- C7 halt, epoch drift and correction interleaving while store append blocks;
- Task events, Task/Run/Workflow, candidate, receipts and workspace bytes unchanged;
- exploding evaluator/provider/tool stubs are never called.

The interleaving test must fail before the same authority guard is held through
`store.append`.

- [ ] **Step 2: Run service tests and confirm RED**

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest \
  tests/product/test_materialization_promotion_service.py -q
```

Expected: import failure because the service does not exist.

- [ ] **Step 3: Implement the exact service surface**

```text
PROMOTION_CAPABILITY = "domain.candidate.promote"

DomainCandidatePromotionService.__init__(
  tasks: TaskService,
  correction: CorrectionGuard,
  candidates: CandidateStore,
  evaluations: CandidateEvaluationStore,
  promotions: CandidatePromotionStore,
  grants: Mapping[str, CapabilityGrant],
  policies: PromotionPolicyRegistry,
  clock: Clock = _utc_now
) -> None

DomainCandidatePromotionService.decide(
  principal: PrincipalIdentity,
  candidate_task_id: str,
  candidate_digest: str,
  command: CandidatePromotionCommand
) -> CandidatePromotionResult

DomainCandidatePromotionService.list_decisions(
  principal: PrincipalIdentity,
  candidate_task_id: str,
  candidate_digest: str
) -> tuple[CandidatePromotionDecision, ...]

DomainCandidatePromotionService.list_priors(
  principal: PrincipalIdentity,
  candidate_task_id: str,
  candidate_digest: str
) -> tuple[DomainPriorArtifact, ...]
```

`decide` performs this order:

1. load exact candidate/route; require `CANDIDATE`, R patch and exact scope;
2. load/validate complete receipt chain, exact head and all scope/task/run bindings;
3. load promotion Task/Run; require running, distinct and same scope;
4. require promoter role `PRINCIPAL`/`TENANT_ADMIN`, Goal/Commitment ownership and exact
   authority scope;
5. validate active unexpired exact grant with raw ID
   `domain.candidate.promote`, separate version `1`, and raw Commitment scope;
6. reject promoter identity against builder, fixed sealer, every evaluator/recorder;
7. resolve production policy V1 and derive reduction/payload/idempotency;
8. C7 halt check and epoch snapshot for promotion Task/Run/capability;
9. enter `guard_unchanged`, recheck and hold through atomic append;
10. return immutable result without a Task event or any other effect.

Add errors:

```python
class CandidatePromotionError(CandidateError):
    pass


class CandidatePromotionNotFound(CandidatePromotionError):
    pass


class CandidatePromotionDenied(CandidatePromotionError):
    pass


class CandidatePromotionScopeMismatch(CandidatePromotionError):
    pass
```

Use existing `CandidateConcurrentWrite` and `CandidateIdempotencyConflict` for CAS and
derived-key conflicts.

- [ ] **Step 4: Run service and adjacent regression tests**

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest \
  tests/product/test_materialization_service.py \
  tests/product/test_materialization_evaluation_service.py \
  tests/product/test_materialization_promotion_service.py -q
```

Expected: all pass, including correction interleaving.

- [ ] **Step 5: Commit the service slice**

```bash
git add packages/os_core/src/agent_os_core/materialization_promotion.py \
  packages/os_core/src/agent_os_core/errors.py \
  packages/os_core/src/agent_os_core/__init__.py \
  tests/product/test_materialization_promotion_service.py
git commit -m "feat(product): enforce ADM-P3 promotion authority"
```

---

### Task 5: Application composition and real HTTP entry points

**Files:**

- Modify: `apps/api_server/app.py`
- Modify: `apps/api_server/server.py`
- Test: `tests/product/test_materialization_promotion_api.py`

**Interfaces:**

- Consumes: production `PromotionPolicyV1`, shared evaluation ledger, promotion service and exact grant.
- Produces: three application methods and three HTTP routes.

- [ ] **Step 1: Write failing end-to-end API tests**

Use one file-backed SQLite database and distinct authenticated applications for:

```text
builder -> fixed Product sealer -> evaluator -> receipt recorder -> promoter
```

Prove:

- POST with promotion Task/Run, exact receipt head and parent returns V1 `DEFER` for
  pass receipts and no prior;
- a fail receipt also returns `DEFER` with
  `RECORDED_EVALUATOR_FAIL_UNADJUDICATED` and no prior;
- verdict/threshold/receipt-list/policy/prior/activation fields return 400;
- promoter collision returns 403;
- stale head/parent returns 409;
- exact replay returns the original decision;
- GET decisions survives restart and GET priors is empty under V1;
- POST bypasses generic HTTP idempotency cache;
- no Task event, candidate/receipt/workspace mutation or provider call occurs.

- [ ] **Step 2: Run API tests and confirm RED**

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest \
  tests/product/test_materialization_promotion_api.py -q
```

Expected: 404/attribute/import failure because ADM-P3 routes are absent.

- [ ] **Step 3: Wire shared ledger, production policy and exact grant**

In `AgentOSApplication`:

- construct `SQLiteCandidateEvaluationStore(database)` first;
- construct `SQLiteCandidatePromotionStore(self.evaluation_receipts.ledger, policies)`;
- register production `PromotionPolicyV1` only;
- allow optional `promotion_grant` constructor override for local tests/auth adapters;
- add `_build_promotion_grant` with exact capability/version/scope, zero provider tokens
  and zero tool calls;
- preserve evaluation/promotion grants when `_build_grants` is rebuilt;
- never add promotion to `WorkspaceSandbox.specs()`.

Add application methods:

```text
AgentOSApplication.decide_domain_candidate_promotion(
  candidate_task_id: str,
  candidate_digest: str,
  payload: dict[str, Any]
) -> CandidatePromotionResult

AgentOSApplication.list_domain_candidate_promotions(
  candidate_task_id: str,
  candidate_digest: str
) -> tuple[CandidatePromotionDecision, ...]

AgentOSApplication.list_domain_candidate_priors(
  candidate_task_id: str,
  candidate_digest: str
) -> tuple[DomainPriorArtifact, ...]
```

They bind route candidate fields, default only authenticated tenant/workspace, validate
the closed command and never pass through verdict or prior bytes.

- [ ] **Step 4: Add routes, cache bypass and typed errors**

```text
POST /v1/tasks/{candidate_task_id}/domain-candidates/{candidate_digest}/promotions:decide
GET  /v1/tasks/{candidate_task_id}/domain-candidates/{candidate_digest}/promotions
GET  /v1/tasks/{candidate_task_id}/domain-candidates/{candidate_digest}/domain-priors
```

Make `_uses_generic_http_idempotency(path)` return `False` for
`/promotions:decide`. Map promotion
denial/scope to 403, absence to 404 and CAS/idempotency conflicts to 409. Return the
ledger result directly; never call `run_task`, provider, broker or artifact writer.

- [ ] **Step 5: Run all ADM-P1/P2/P3 targeted tests**

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest \
  tests/product/test_materialization_contracts.py \
  tests/product/test_materialization_service.py \
  tests/product/test_materialization_api.py \
  tests/product/test_materialization_evaluation_contracts.py \
  tests/product/test_materialization_evaluation_persistence.py \
  tests/product/test_materialization_evaluation_service.py \
  tests/product/test_materialization_evaluation_api.py \
  tests/product/test_materialization_promotion_contracts.py \
  tests/product/test_materialization_promotion_policy.py \
  tests/product/test_materialization_promotion_persistence.py \
  tests/product/test_materialization_promotion_service.py \
  tests/product/test_materialization_promotion_api.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit the entry-point slice**

```bash
git add apps/api_server/app.py apps/api_server/server.py \
  tests/product/test_materialization_promotion_api.py
git commit -m "feat(product): expose ADM-P3 decision endpoints"
```

---

### Task 6: Verification, independent review and truth update

**Files:**

- Create after review: `docs/product/PM-ADM-P3-PROMOTION-AND-OPTIONAL-PRIOR-2026-07-15.md`
- Modify after review: `docs/CURRENT_STATE.yaml`
- Modify after review: `codebase_index.md`

**Interfaces:**

- Consumes: exact implementation range and verification output.
- Produces: bounded evidence record/live branch truth; no activation or release authority.

- [ ] **Step 1: Run the full Product suite**

```bash
PYTHONPATH=packages/contracts/src:packages/os_core/src:. \
../../.venv/bin/python -m pytest tests/product -q
```

Expected: all Product tests pass with only existing intentional skips. Record exact
counts/time; do not infer repository-wide green status.

- [ ] **Step 2: Run static and bytecode checks**

```bash
../../.venv/bin/python -m ruff check \
  apps packages/contracts/src packages/os_core/src tests/product
../../.venv/bin/python -m pyright \
  apps packages/contracts/src packages/os_core/src tests/product
../../.venv/bin/python -m compileall -q \
  apps packages/contracts/src packages/os_core/src
git diff --check
```

Expected: ruff clean, pyright 0 errors, compileall success, no whitespace errors.

- [ ] **Step 3: Run explicit bypass mutations and restore exact bytes**

Mutate one at a time, run the named focused test, confirm failure, then restore:

1. accept caller `disposition="PROMOTE"`;
2. pass only the last receipt to the reducer;
3. make V1 return either `REJECT` or `PROMOTE` for any receipt combination;
4. remove promoter-vs-recorder separation;
5. release C7 guard before append;
6. split decision/prior inserts across transactions.

At least one focused test must fail for every mutation. Never commit mutation bytes.

- [ ] **Step 4: Obtain exact-range independent technical review**

Give the reviewer exact base/head, all three ADM-P3 documents, full diff, verification
output, production V1 all-DEFER invariant, process-local C7 boundary and the known
ADM-P1/P2 Product-eval external-artifact failures. Any P0/P1 or
`TECHNICAL_REVISE` keeps status `NOT_ACCEPTED / HOLD`; fix and re-review the new range.

- [ ] **Step 5: Write evidence and update branch-local truth only after approval**

The evidence record must state exactly:

```text
ADM-P3 is IMPLEMENTED_LOCAL_ADM_P3_INFRASTRUCTURE_ONLY.
Production ADM-P3-POLICY-V1 records DEFER only and can produce neither REJECT nor
PROMOTE.
The atomic PROMOTE/prior invariant is structurally tested under a closed test-only
registered policy; no production prior was created and no activation exists.
```

Update `docs/CURRENT_STATE.yaml` and `codebase_index.md` with exact heads, counts,
review identity/session and the same ceiling. Do not update parent/root truth files.

- [ ] **Step 6: Commit the evidence checkpoint**

```bash
git add docs/product/PM-ADM-P3-PROMOTION-AND-OPTIONAL-PRIOR-2026-07-15.md \
  docs/CURRENT_STATE.yaml codebase_index.md
git commit -m "docs(product): record ADM-P3 structural evidence"
git status --short
git diff --check HEAD~1..HEAD
```

Expected: clean ADM-P3 worktree, local commits only, no push or merge.

## Completion boundary

Passing this plan proves only that Agent OS can deterministically and immutably record a
Product-owned promotion disposition over a complete ADM-P1/ADM-P2 chain and that its
store preserves the atomic `PROMOTE`/inert-prior invariant. Because production policy
V1 cannot mechanically prove custody or independence, it only defers and creates no
production prior. No candidate application, configuration snapshot, new-run activation,
domain adaptation performance, self-improvement, autonomy, production readiness,
migration, push, merge or release follows.
