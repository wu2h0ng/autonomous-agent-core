# T-P-OS-SPINE-0 P0A Contracts and Run Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. All checklist steps are now executed.

**Goal:** Build the first real Product Track call path from versioned Goal/Commitment/Workflow/Outcome contracts through an append-only event store into a rehydratable Task/AgentRun aggregate.

**Architecture:** Add new Product Track packages under `packages/`; never import `src/aac` or `experiments`. Pydantic contracts reject unknown fields and provide stable SHA-256 canonical digests. `TaskService` executes create/commit/start commands against an event-store port; the in-memory adapter is a test/local adapter only and is explicitly not the SPINE-0 PostgreSQL durability claim.

**Tech Stack:** Python 3.11+, Pydantic 2, pytest 9, stdlib `hashlib/json/datetime/enum/uuid`, existing setuptools root metadata.

## Global Constraints

- Product Track only; do not modify `src/aac`, `experiments`, research verdicts or frozen gates.
- No Data Agent donor import and no `_migration` path.
- Tests are written and observed failing before every production behavior.
- All public contracts use `extra="forbid"`, immutable values, timezone-aware UTC timestamps and `schema_version="1.0"`.
- Product code has no import from `aac`, `experiments` or external agent frameworks.
- An in-memory event store may prove port semantics and rehydration only; it must not be described as process-durable or Product Done.
- Invalid graph, invalid transition, scope mismatch and optimistic-concurrency mismatch fail closed.
- Update `docs/CURRENT_STATE.yaml`, `docs/PROJECT_PLAN.md` and `codebase_index.md` only after code and tests pass.

---

## File Map

```text
packages/contracts/src/agent_os_contracts/
  __init__.py       public contract exports
  common.py         immutable base model, UTC validation, canonical JSON/digest
  task.py           Goal and Commitment
  workflow.py       node/edge enums, WorkflowGraph validation and digest
  outcome.py        ExpectedOutcome and ObservedOutcome
  runtime.py        Task/Run state and TaskEvent contracts

packages/os_core/src/agent_os_core/
  __init__.py       public kernel exports
  errors.py         typed domain/concurrency/not-found errors
  event_store.py    TaskEventStore protocol + in-memory adapter
  task_aggregate.py event-rehydrated Task aggregate and command invariants
  task_service.py   public create/commit/start/get call path

tests/product/
  conftest.py                       deterministic IDs, clock and contract fixtures
  test_contracts.py                 immutable/strict/canonical contract behavior
  test_workflow_graph.py            graph semantics and digest behavior
  test_event_store.py               append ordering/concurrency behavior
  test_task_service.py              real lifecycle, rehydration and failures
  test_product_research_boundary.py import-boundary regression
```

---

### Task 1: Product Package Wiring and Strict Base Contracts

**Files:**
- Modify: `pyproject.toml`
- Create: `packages/contracts/src/agent_os_contracts/__init__.py`
- Create: `packages/contracts/src/agent_os_contracts/common.py`
- Create: `packages/contracts/src/agent_os_contracts/task.py`
- Create: `packages/contracts/src/agent_os_contracts/outcome.py`
- Create: `tests/product/conftest.py`
- Create: `tests/product/test_contracts.py`

**Interfaces:**
- Produces: `ContractModel`, `canonical_json`, `content_digest`, `Goal`, `Commitment`, `ExpectedOutcome`, `ObservedOutcome`.
- Consumes: Pydantic 2 only.

- [x] **Step 1: Add failing strict-contract tests**

```python
def test_goal_rejects_unknown_fields(now):
    with pytest.raises(ValidationError):
        Goal(
            goal_id="goal-1", tenant_id="tenant-1", workspace_id="ws-1",
            created_by="user-1", created_at=now, statement="Ship a verified patch",
            hidden_authority="forbidden",
        )

def test_goal_requires_timezone_aware_timestamp():
    with pytest.raises(ValidationError, match="timezone-aware"):
        Goal(
            goal_id="goal-1", tenant_id="tenant-1", workspace_id="ws-1",
            created_by="user-1", created_at=datetime(2026, 7, 10),
            statement="Ship a verified patch",
        )

def test_contract_is_immutable(goal):
    with pytest.raises(ValidationError):
        goal.statement = "changed"
```

- [x] **Step 2: Run RED**

Run:

```bash
python3 -m pytest tests/product/test_contracts.py -q
```

Expected: collection fails because `agent_os_contracts` does not exist.

- [x] **Step 3: Add product test paths and minimal strict contracts**

`pyproject.toml` adds optional Product Track dependencies and pytest paths without changing
Research Track runtime dependencies:

```toml
[project.optional-dependencies]
product-core = ["pydantic>=2.13,<3"]
product-test = ["pytest>=9,<10"]

[tool.pytest.ini_options]
pythonpath = [
  ".",
  "src",
  "packages/contracts/src",
  "packages/os_core/src",
]
```

`common.py` defines:

```python
class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0"] = "1.0"

def require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)

def canonical_json(value: BaseModel | Mapping[str, Any]) -> str:
    payload = value.model_dump(mode="json", exclude_none=True) if isinstance(value, BaseModel) else value
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

def content_digest(value: BaseModel | Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
```

`task.py` and `outcome.py` define the fields frozen in the architecture packet. Non-empty
tuple fields use Pydantic validators; authority scopes are unique/sorted.

- [x] **Step 4: Run GREEN**

Run: `python3 -m pytest tests/product/test_contracts.py -q`

Expected: all contract tests pass.

- [x] **Step 5: Commit**

```bash
git add pyproject.toml packages/contracts tests/product/conftest.py tests/product/test_contracts.py
git commit -m "feat(product): add strict Agent OS contracts"
```

---

### Task 2: Canonical WorkflowGraph v1

**Files:**
- Create: `packages/contracts/src/agent_os_contracts/workflow.py`
- Modify: `packages/contracts/src/agent_os_contracts/__init__.py`
- Create: `tests/product/test_workflow_graph.py`

**Interfaces:**
- Produces: `NodeKind`, `IdempotencyMode`, `NodeSpec`, `EdgeSpec`, `WorkflowGraph`, `WorkflowValidationError` through Pydantic validation.
- Consumes: `ContractModel`, `content_digest`.

- [x] **Step 1: Add failing graph tests**

```python
def test_graph_digest_ignores_node_and_edge_input_order(graph_factory):
    first = graph_factory(reverse=False)
    second = graph_factory(reverse=True)
    assert first.canonical_digest() == second.canonical_digest()

def test_graph_rejects_cycle(graph_factory):
    with pytest.raises(ValidationError, match="acyclic"):
        graph_factory(extra_edges=(("verify", "inspect"),))

def test_tool_node_requires_capability():
    with pytest.raises(ValidationError, match="capability"):
        NodeSpec(node_id="patch", kind=NodeKind.TOOL)
```

- [x] **Step 2: Run RED**

Run: `python3 -m pytest tests/product/test_workflow_graph.py -q`

Expected: import failure because `workflow.py` does not exist.

- [x] **Step 3: Implement graph validation and canonical digest**

Validation must reject duplicate node IDs, unknown edge endpoints, self-edges, cycles,
missing terminal nodes and tool nodes without a capability. Digest payload sorts nodes by
`node_id` and edges by `(source, target, condition or "")`:

```python
def canonical_digest(self) -> str:
    payload = self.model_dump(mode="json", exclude_none=True)
    payload["nodes"] = sorted(payload["nodes"], key=lambda item: item["node_id"])
    payload["edges"] = sorted(
        payload["edges"],
        key=lambda item: (item["source"], item["target"], item.get("condition") or ""),
    )
    return content_digest(payload)
```

Cycle detection uses Kahn's algorithm over the outer static graph. Looping remains an
explicit bounded node kind; no arbitrary graph cycle is accepted.

- [x] **Step 4: Run GREEN**

Run: `python3 -m pytest tests/product/test_workflow_graph.py -q`

Expected: graph tests pass.

- [x] **Step 5: Commit**

```bash
git add packages/contracts/src/agent_os_contracts tests/product/test_workflow_graph.py
git commit -m "feat(product): add canonical WorkflowGraph v1"
```

---

### Task 3: Append-Only Event Store and Task Aggregate

**Files:**
- Create: `packages/contracts/src/agent_os_contracts/runtime.py`
- Modify: `packages/contracts/src/agent_os_contracts/__init__.py`
- Create: `packages/os_core/src/agent_os_core/__init__.py`
- Create: `packages/os_core/src/agent_os_core/errors.py`
- Create: `packages/os_core/src/agent_os_core/event_store.py`
- Create: `packages/os_core/src/agent_os_core/task_aggregate.py`
- Create: `tests/product/test_event_store.py`
- Create: `tests/product/test_task_aggregate.py`

**Interfaces:**
- Produces: `TaskStatus`, `RunStatus`, `TaskEventType`, `TaskEventDraft`, `TaskEvent`, `AgentRun`, `TaskEventStore`, `InMemoryTaskEventStore`, `TaskAggregate`.
- Consumes: Task/workflow/outcome contracts from Tasks 1-2.

- [x] **Step 1: Add failing event-store tests**

```python
def test_append_assigns_monotonic_sequences(event_store, event_draft):
    first = event_store.append("task-1", expected_sequence=0, drafts=(event_draft,))
    second = event_store.append("task-1", expected_sequence=1, drafts=(event_draft.model_copy(update={"event_id": "event-2"}),))
    assert [event.sequence for event in (*first, *second)] == [1, 2]

def test_append_rejects_stale_expected_sequence(event_store, event_draft):
    event_store.append("task-1", expected_sequence=0, drafts=(event_draft,))
    with pytest.raises(ConcurrentWriteError):
        event_store.append("task-1", expected_sequence=0, drafts=(event_draft.model_copy(update={"event_id": "event-2"}),))
```

- [x] **Step 2: Run event-store RED**

Run: `python3 -m pytest tests/product/test_event_store.py -q`

Expected: import failure because `agent_os_core` does not exist.

- [x] **Step 3: Implement event contracts and in-memory port adapter**

The store copies immutable events, assigns sequence numbers atomically under a reentrant
lock and rejects stale sequence or duplicate event IDs. It exposes `read(task_id)` only;
callers cannot mutate its internal lists.

- [x] **Step 4: Run event-store GREEN**

Run: `python3 -m pytest tests/product/test_event_store.py -q`

Expected: event-store tests pass.

- [x] **Step 5: Add failing aggregate tests**

```python
def test_rehydrate_create_commit_start(task_events):
    aggregate = TaskAggregate.rehydrate(task_events)
    assert aggregate.status is TaskStatus.RUNNING
    assert aggregate.run.workflow_digest == aggregate.workflow.canonical_digest()

def test_start_before_commit_fails(draft_aggregate, run):
    with pytest.raises(InvalidTransitionError, match="DRAFT"):
        draft_aggregate.start(run, event_id="event-run", occurred_at=NOW)

def test_commit_rejects_cross_tenant_scope(draft_aggregate, foreign_commitment, workflow, expected):
    with pytest.raises(ScopeMismatchError):
        draft_aggregate.commit(foreign_commitment, workflow, expected, event_id="event-commit", occurred_at=NOW)
```

- [x] **Step 6: Run aggregate RED**

Run: `python3 -m pytest tests/product/test_task_aggregate.py -q`

Expected: fails because `TaskAggregate` is missing.

- [x] **Step 7: Implement aggregate commands and event replay**

The aggregate accepts only:

```text
none --TASK_CREATED--> DRAFT
DRAFT --TASK_COMMITTED--> COMMITTED
COMMITTED --RUN_STARTED--> RUNNING
```

Every command returns a `TaskEventDraft`; state changes only by applying persisted events.
Rehydration rejects sequence gaps, duplicate creation, unknown event types and invalid
historical transitions. Commit validates tenant/workspace/goal bindings; start validates
commitment/workflow/outcome bindings and graph digest.

- [x] **Step 8: Run aggregate GREEN**

Run: `python3 -m pytest tests/product/test_task_aggregate.py -q`

Expected: aggregate tests pass.

- [x] **Step 9: Commit**

```bash
git add packages/contracts/src/agent_os_contracts packages/os_core tests/product/test_event_store.py tests/product/test_task_aggregate.py
git commit -m "feat(product): add replayable task run kernel"
```

---

### Task 4: Public TaskService Vertical and Boundary Tests

**Files:**
- Create: `packages/os_core/src/agent_os_core/task_service.py`
- Modify: `packages/os_core/src/agent_os_core/__init__.py`
- Create: `tests/product/test_task_service.py`
- Create: `tests/product/test_product_research_boundary.py`

**Interfaces:**
- Produces: `TaskService.create_task`, `TaskService.commit_task`, `TaskService.start_run`, `TaskService.get_task`.
- Consumes: `TaskEventStore`, `TaskAggregate`, exact Product Track contracts.

- [x] **Step 1: Add failing service lifecycle test**

```python
def test_service_rehydrates_across_service_instances(store, id_factory, clock, contracts):
    first = TaskService(store, id_factory=id_factory, clock=clock)
    created = first.create_task(contracts.goal)
    first.commit_task(created.task_id, contracts.commitment, contracts.workflow, contracts.expected)

    restarted = TaskService(store, id_factory=id_factory, clock=clock)
    running = restarted.start_run(created.task_id)

    assert running.status is TaskStatus.RUNNING
    assert len(store.read(created.task_id)) == 3
    assert running.run.workflow_digest == contracts.workflow.canonical_digest()
```

- [x] **Step 2: Run service RED**

Run: `python3 -m pytest tests/product/test_task_service.py -q`

Expected: import failure because `TaskService` does not exist.

- [x] **Step 3: Implement minimal public service**

`TaskService` loads and rehydrates before every command, generates typed IDs with the
injected factory, appends with the aggregate's exact sequence and returns a freshly
rehydrated aggregate. `get_task` raises `TaskNotFoundError`; duplicate task IDs and stale
writes fail closed.

- [x] **Step 4: Run service GREEN**

Run: `python3 -m pytest tests/product/test_task_service.py -q`

Expected: service tests pass.

- [x] **Step 5: Add and run Product/Research import-boundary test**

```python
def test_product_packages_do_not_import_research_modules():
    forbidden = {"aac", "experiments"}
    for path in PRODUCT_PYTHON_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        roots = imported_roots(tree)
        assert roots.isdisjoint(forbidden), f"{path}: {roots & forbidden}"
```

Run: `python3 -m pytest tests/product/test_product_research_boundary.py -q`

Expected: pass.

- [x] **Step 6: Run all Product Track tests**

Run: `python3 -m pytest tests/product -q`

Expected: all Product Track tests pass.

- [x] **Step 7: Commit**

```bash
git add packages/os_core tests/product
git commit -m "feat(product): expose task lifecycle service"
```

---

### Task 5: State Documentation and Regression Verification

**Files:**
- Modify: `docs/CURRENT_STATE.yaml`
- Modify: `docs/PROJECT_PLAN.md`
- Modify: `codebase_index.md`
- Create: `.agent_runs/t-p-os-spine-0-p0a-20260710/verification.md` outside Git

**Interfaces:**
- Consumes: verified commands from Tasks 1-4.
- Produces: honest staged-capability status; does not claim Postgres durability, provider,
  tool execution, API/UI or SPINE-0 completion.

- [x] **Step 1: Run fresh Product Track verification**

Run: `python3 -m pytest tests/product -q`

Expected: all Product Track tests pass.

- [x] **Step 2: Run full Research Track regression**

Run: `PYTHONPATH=src python3 -m unittest discover -s tests -v`

Expected: existing research suite passes with only documented skips.

- [x] **Step 3: Run static boundary and whitespace checks**

```bash
git diff --check
rg -n "from (aac|experiments)|import (aac|experiments)" packages apps domain_packs
```

Expected: `git diff --check` exits 0; import search has no Product Track matches.

- [x] **Step 4: Update authoritative docs**

Record:

```text
P0A_CONTRACTS_AND_RUN_KERNEL_IMPLEMENTED
storage: IN_MEMORY_PORT_ADAPTER_ONLY
postgres/provider/tool/api/ui: NOT_IMPLEMENTED
SPINE-0 Product Done: NOT_MET
```

Include exact commands/counts and no research claim.

- [x] **Step 5: Commit**

```bash
git add docs/CURRENT_STATE.yaml docs/PROJECT_PLAN.md codebase_index.md
git commit -m "docs(product): record P0A run kernel evidence"
```

---

## Self-Review

- Spec coverage: P0A covers canonical contracts, WorkflowGraph validation/digest, append-only
  events, lifecycle transitions, replay, concurrency and a public call path.
- Deliberate gaps: provider/CredentialRef resolution, PolicyKernel/CorrectionAuthority,
  sandbox tools, PostgreSQL, API/CLI/UI and complete SPINE-0 acceptance belong to subsequent
  implementation packets and remain `NOT_IMPLEMENTED`.
- No placeholders: every task names exact files, signatures, test behavior, commands and
  expected results.
- Type consistency: `TaskEventDraft -> TaskEventStore.append -> TaskEvent ->
  TaskAggregate.rehydrate -> TaskService` is the only lifecycle data path.
- Boundary consistency: Product Track never imports Research Track or Data Agent donor code.
