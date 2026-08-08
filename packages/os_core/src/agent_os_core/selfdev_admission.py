from __future__ import annotations

import fcntl
import hashlib
import json
import sqlite3
import subprocess
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from agent_os_contracts import (
    Commitment,
    EdgeSpec,
    ExpectedOutcome,
    Goal,
    IdempotencyMode,
    MandateTaskLinkCommand,
    NodeKind,
    NodeSpec,
    PersistentCommitmentAttachCommand,
    PersistentCommitmentState,
    ResourceBudget,
    ResponsibilityWorkRoute,
    RunStatus,
    SelfDevelopmentAdmissionCommand,
    SelfDevelopmentAdmissionReceipt,
    SelfDevelopmentVerifierBinding,
    SelfDevelopmentWorkSpec,
    TaskEventType,
    TaskStatus,
    WorkflowGraph,
    canonical_json,
    content_digest,
)

from .responsibility_surface import (
    ResponsibilitySurfaceError,
    resolve_responsibility_authority_context,
)
from .self_development_organ import (
    SelfDevelopmentOrganBlocked,
    inspect_selfdev_workspace,
)
from .task_configuration import TASK_CONFIGURATION_CAPABILITY, TaskConfigurationRuntime
from .governance import POLICY_KERNEL_V1_DIGEST


class SelfDevelopmentAdmissionError(ResponsibilitySurfaceError):
    """Stable, fail-closed SELFDEV admission error."""

    def __init__(self, code: str, details: str) -> None:
        self.code = code
        self.details = details
        super().__init__(f"{code}: {details}")


class SelfDevelopmentAdmissionPhase(str, Enum):
    RESERVED = "RESERVED"
    TASK_CREATED = "TASK_CREATED"
    TASK_COMMITTED = "TASK_COMMITTED"
    CONFIGURATION_SEALED = "CONFIGURATION_SEALED"
    RUN_STARTED = "RUN_STARTED"
    LINKED = "LINKED"
    COMMITMENT_ATTACHED = "COMMITMENT_ATTACHED"
    ADMITTED = "ADMITTED"


_PHASE_ORDER = tuple(SelfDevelopmentAdmissionPhase)
_ADMISSION_TABLE = "selfdev_admissions_v1"
_POLICY_EXPIRY_DAYS = 30
_UNRESERVED_RUN_ID = "run:selfdev-admission:unreserved"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_workspace(
    workspace: Path,
    command: SelfDevelopmentAdmissionCommand,
    *,
    allowed_dirty_paths: tuple[str, ...],
) -> tuple[str, tuple[str, ...]]:
    workspace = workspace.resolve()
    normalized = tuple(sorted(command.selfdev_spec.allowed_write_paths))
    try:
        dirty_paths = inspect_selfdev_workspace(workspace, command.selfdev_spec)
    except SelfDevelopmentOrganBlocked as exc:
        code = (
            "ADMISSION_WORKTREE_DRIFT"
            if exc.code
            in {
                "SELFDEV_BRANCH_MISMATCH",
                "SELFDEV_HEAD_MISMATCH",
                "SELFDEV_WORKTREE_SCOPE_MISMATCH",
            }
            else "ADMISSION_WORKTREE_INVALID"
        )
        raise SelfDevelopmentAdmissionError(code, str(exc)) from exc
    if dirty_paths and not dirty_paths.issubset(allowed_dirty_paths):
        code = (
            "ADMISSION_WORKTREE_DIRTY"
            if not allowed_dirty_paths
            else "ADMISSION_WORKTREE_DRIFT"
        )
        raise SelfDevelopmentAdmissionError(
            code,
            "worktree contains writes outside replay allowance: "
            f"{sorted(dirty_paths)!r}",
        )
    return command.selfdev_spec.repository_head, normalized


def _seal_verifier_bindings(
    workspace: Path,
    command: SelfDevelopmentAdmissionCommand,
) -> tuple[SelfDevelopmentVerifierBinding, ...]:
    if command.selfdev_spec.verifier_bindings:
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_VERIFIER_INVALID",
            "caller cannot supply server-computed verifier bindings",
        )
    bindings: list[SelfDevelopmentVerifierBinding] = []
    write_paths = set(command.selfdev_spec.allowed_write_paths)
    for verifier_path in command.verifier_paths:
        if verifier_path in write_paths:
            raise SelfDevelopmentAdmissionError(
                "ADMISSION_VERIFIER_INVALID",
                "verifier path cannot overlap the SELFDEV write set",
            )
        tree = subprocess.run(
            [
                "git",
                "-C",
                str(workspace),
                "ls-tree",
                command.selfdev_spec.repository_head,
                "--",
                verifier_path,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        records = tuple(line for line in tree.stdout.splitlines() if line)
        if tree.returncode != 0 or len(records) != 1 or "\t" not in records[0]:
            raise SelfDevelopmentAdmissionError(
                "ADMISSION_VERIFIER_INVALID",
                f"verifier path is not one exact base Git blob: {verifier_path}",
            )
        metadata, recorded_path = records[0].split("\t", 1)
        parts = metadata.split()
        if (
            len(parts) != 3
            or parts[0] not in {"100644", "100755"}
            or parts[1] != "blob"
            or recorded_path != verifier_path
        ):
            raise SelfDevelopmentAdmissionError(
                "ADMISSION_VERIFIER_INVALID",
                f"verifier path is not a regular base Git blob: {verifier_path}",
            )
        blob = subprocess.run(
            ["git", "-C", str(workspace), "cat-file", "blob", parts[2]],
            check=False,
            capture_output=True,
        )
        oracle = workspace / verifier_path
        if (
            blob.returncode != 0
            or not oracle.is_file()
            or oracle.is_symlink()
            or hashlib.sha256(oracle.read_bytes()).digest()
            != hashlib.sha256(blob.stdout).digest()
        ):
            raise SelfDevelopmentAdmissionError(
                "ADMISSION_VERIFIER_INVALID",
                f"verifier worktree bytes differ from the sealed base blob: {verifier_path}",
            )
        bindings.append(
            SelfDevelopmentVerifierBinding(
                path=verifier_path,
                base_blob_sha256=hashlib.sha256(blob.stdout).hexdigest(),
            )
        )
    return tuple(bindings)


def _identity(kind: str, identity_digest: str) -> str:
    return f"{kind}:selfdev-admission:{identity_digest}"


def _grant_authority_projection(grants: dict[str, Any]) -> dict[str, Any]:
    security_fields = (
        "grant_id",
        "principal_id",
        "tenant_id",
        "workspace_id",
        "capability_id",
        "capability_version",
        "max_risk_tier",
        "budget_limit",
        "status",
        "granted_by",
    )
    return {
        capability_id: {field: grant[field] for field in security_fields}
        for capability_id, grant in grants.items()
    }


def _plan(
    *,
    command: SelfDevelopmentAdmissionCommand,
    selfdev_spec: SelfDevelopmentWorkSpec,
    command_digest: str,
    semantic_key: str,
    mandate_id: str,
    portfolio_id: str,
    principal_id: str,
    tenant_id: str,
    workspace_id: str,
    responsibility_binding: dict[str, Any],
    portfolio_record: dict[str, Any],
    provider_profile: dict[str, Any],
    provider_profile_digest: str,
    policy_version: str,
    configuration_grants: dict[str, Any],
    created_at: datetime,
) -> dict[str, Any]:
    identity_digest = content_digest(
        {
            "mandate_id": mandate_id,
            "admission_id": command.admission_id,
            "command_digest": command_digest,
        }
    )
    task_id = _identity("task", identity_digest)
    goal = Goal(
        goal_id=_identity("goal", identity_digest),
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        created_by=principal_id,
        created_at=created_at,
        statement=command.statement,
        constraints=(
            "bounded to the frozen SELFDEV work spec",
            "no main, push, merge, promotion, release, or self-approval",
        ),
    )
    commitment = Commitment(
        commitment_id=_identity("commitment", identity_digest),
        task_id=task_id,
        goal_id=goal.goal_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        accepted_by=principal_id,
        accepted_at=created_at,
        deliverables=command.deliverables,
        acceptance_criteria=command.acceptance_criteria,
        authority_scopes=(TASK_CONFIGURATION_CAPABILITY,),
        budget=ResourceBudget(
            max_cost_usd=Decimal("5.00"),
            max_duration_seconds=24 * 60 * 60,
            max_provider_tokens=32_000,
            max_tool_calls=128,
        ),
        risk_tier=1,
        exit_conditions=("pytest verified", "bounded failure recorded"),
        expires_at=created_at + timedelta(days=_POLICY_EXPIRY_DAYS),
    )
    expected = ExpectedOutcome(
        expected_outcome_id=_identity("expected", identity_digest),
        task_id=task_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        evaluator_type="pytest",
        evaluator_version="1",
        evidence_requirements=("test-report",),
        failure_semantics=("tests fail",),
        threshold=1.0,
        observation_window_seconds=_POLICY_EXPIRY_DAYS * 24 * 60 * 60,
        frozen_at=created_at,
    )
    workflow = WorkflowGraph(
        workflow_id=_identity("workflow", identity_digest),
        version=1,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        created_by=principal_id,
        created_at=created_at,
        policy_version="policy-1",
        evaluator_refs=("evaluator:pytest:1",),
        nodes=(
            NodeSpec(node_id="agent-loop-handoff", kind=NodeKind.TRANSFORM),
            NodeSpec(
                node_id="tests",
                kind=NodeKind.TOOL,
                capability="workspace.run_tests",
                risk_tier=0,
                idempotency=IdempotencyMode.IDEMPOTENT,
            ),
            NodeSpec(node_id="evaluate", kind=NodeKind.EVALUATION),
            NodeSpec(node_id="done", kind=NodeKind.TERMINAL),
        ),
        edges=(
            EdgeSpec(source="agent-loop-handoff", target="tests"),
            EdgeSpec(source="tests", target="evaluate"),
            EdgeSpec(source="evaluate", target="done"),
        ),
    )
    return {
        "admission_id": command.admission_id,
        "command_digest": command_digest,
        "semantic_key": semantic_key,
        "mandate_id": mandate_id,
        "portfolio_id": portfolio_id,
        "principal_id": principal_id,
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "responsibility_binding": responsibility_binding,
        "portfolio_record": portfolio_record,
        "provider_profile": provider_profile,
        "provider_profile_digest": provider_profile_digest,
        "policy_version": policy_version,
        "configuration_grants": configuration_grants,
        "configuration_grant_authority": _grant_authority_projection(
            configuration_grants
        ),
        "created_at": created_at.isoformat(),
        "task_id": task_id,
        "task_event_id": _identity("event-created", identity_digest),
        "goal": goal.model_dump(mode="json"),
        "commitment": commitment.model_dump(mode="json"),
        "expected_outcome": expected.model_dump(mode="json"),
        "workflow": workflow.model_dump(mode="json"),
        "selfdev_spec": selfdev_spec.model_dump(mode="json"),
    }


class SQLiteSelfDevelopmentAdmissionStore:
    def __init__(self, database: Path) -> None:
        self.database = Path(database).resolve()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database), timeout=30.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        connection = self._connect()
        try:
            connection.execute(
                f"CREATE TABLE IF NOT EXISTS {_ADMISSION_TABLE} ("
                "mandate_id TEXT NOT NULL, admission_id TEXT NOT NULL, "
                "command_digest TEXT NOT NULL, source_digest TEXT NOT NULL, "
                "semantic_key TEXT NOT NULL, plan_json TEXT NOT NULL, "
                "plan_digest TEXT NOT NULL, reservation_digest TEXT NOT NULL, "
                "phase TEXT NOT NULL, "
                "PRIMARY KEY (mandate_id, admission_id), "
                "UNIQUE (mandate_id, semantic_key))"
            )
            connection.commit()
        finally:
            connection.close()

    def reserve(
        self,
        *,
        mandate_id: str,
        admission_id: str,
        command_digest: str,
        source_digest: str,
        semantic_key: str,
        plan: dict[str, Any],
    ) -> tuple[sqlite3.Row, bool]:
        plan_json = canonical_json(plan)
        plan_digest = hashlib.sha256(plan_json.encode("utf-8")).hexdigest()
        reservation_digest = content_digest(
            {
                "mandate_id": mandate_id,
                "admission_id": admission_id,
                "command_digest": command_digest,
                "source_digest": source_digest,
                "semantic_key": semantic_key,
                "plan_digest": plan_digest,
            }
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                f"SELECT * FROM {_ADMISSION_TABLE} WHERE mandate_id=? AND admission_id=?",
                (mandate_id, admission_id),
            ).fetchone()
            if existing is not None:
                self._validate_row(existing)
                if str(existing["command_digest"]) != command_digest:
                    raise SelfDevelopmentAdmissionError(
                        "ADMISSION_COMMAND_CONFLICT",
                        "admission_id is already reserved for a different typed command",
                    )
                connection.commit()
                return existing, True
            collision = connection.execute(
                f"SELECT admission_id FROM {_ADMISSION_TABLE} "
                "WHERE mandate_id=? AND semantic_key=?",
                (mandate_id, semantic_key),
            ).fetchone()
            if collision is not None:
                raise SelfDevelopmentAdmissionError(
                    "ADMISSION_SEMANTIC_DUPLICATE",
                    "the same Mandate, repository HEAD, and write set are active "
                    f"under {collision['admission_id']}",
                )
            connection.execute(
                f"INSERT INTO {_ADMISSION_TABLE} "
                "(mandate_id, admission_id, command_digest, source_digest, "
                "semantic_key, plan_json, plan_digest, reservation_digest, phase) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    mandate_id,
                    admission_id,
                    command_digest,
                    source_digest,
                    semantic_key,
                    plan_json,
                    plan_digest,
                    reservation_digest,
                    SelfDevelopmentAdmissionPhase.RESERVED.value,
                ),
            )
            row = connection.execute(
                f"SELECT * FROM {_ADMISSION_TABLE} WHERE mandate_id=? AND admission_id=?",
                (mandate_id, admission_id),
            ).fetchone()
            assert row is not None
            connection.commit()
            return row, False
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get(self, mandate_id: str, admission_id: str) -> sqlite3.Row:
        connection = self._connect()
        try:
            row = connection.execute(
                f"SELECT * FROM {_ADMISSION_TABLE} WHERE mandate_id=? AND admission_id=?",
                (mandate_id, admission_id),
            ).fetchone()
            if row is None:
                raise SelfDevelopmentAdmissionError(
                    "ADMISSION_STATE_DRIFT", "durable reservation disappeared"
                )
            self._validate_row(row)
            return row
        finally:
            connection.close()

    def advance(
        self,
        mandate_id: str,
        admission_id: str,
        expected: SelfDevelopmentAdmissionPhase,
        target: SelfDevelopmentAdmissionPhase,
    ) -> None:
        if _PHASE_ORDER.index(target) != _PHASE_ORDER.index(expected) + 1:
            raise ValueError("admission phases must advance one step")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"SELECT * FROM {_ADMISSION_TABLE} WHERE mandate_id=? AND admission_id=?",
                (mandate_id, admission_id),
            ).fetchone()
            if row is None:
                raise SelfDevelopmentAdmissionError(
                    "ADMISSION_STATE_DRIFT", "durable reservation disappeared"
                )
            self._validate_row(row)
            current = SelfDevelopmentAdmissionPhase(str(row["phase"]))
            if current is target:
                connection.commit()
                return
            if current is not expected:
                raise SelfDevelopmentAdmissionError(
                    "ADMISSION_STATE_DRIFT",
                    f"phase expected {expected.value}, found {current.value}",
                )
            connection.execute(
                f"UPDATE {_ADMISSION_TABLE} SET phase=? "
                "WHERE mandate_id=? AND admission_id=?",
                (target.value, mandate_id, admission_id),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _validate_row(row: sqlite3.Row) -> None:
        try:
            plan = json.loads(str(row["plan_json"]))
            phase = SelfDevelopmentAdmissionPhase(str(row["phase"]))
        except Exception:
            raise SelfDevelopmentAdmissionError(
                "ADMISSION_STATE_DRIFT", "reservation row is malformed"
            ) from None
        del phase
        plan_json = canonical_json(plan)
        plan_digest = hashlib.sha256(plan_json.encode("utf-8")).hexdigest()
        expected_reservation = content_digest(
            {
                "mandate_id": str(row["mandate_id"]),
                "admission_id": str(row["admission_id"]),
                "command_digest": str(row["command_digest"]),
                "source_digest": str(row["source_digest"]),
                "semantic_key": str(row["semantic_key"]),
                "plan_digest": plan_digest,
            }
        )
        if (
            plan_digest != str(row["plan_digest"])
            or expected_reservation != str(row["reservation_digest"])
            or plan.get("command_digest") != str(row["command_digest"])
            or plan.get("semantic_key") != str(row["semantic_key"])
        ):
            raise SelfDevelopmentAdmissionError(
                "ADMISSION_STATE_DRIFT", "reservation or immutable plan digest drift"
            )


@contextmanager
def _admission_lock(workspace: Path, database: Path):
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(Path(workspace).resolve()),
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_LOCK_INVALID", "Git common directory is unavailable"
        )
    git_common_dir = Path(completed.stdout.strip())
    if not git_common_dir.is_dir() or git_common_dir.is_symlink():
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_LOCK_INVALID", "Git common directory is not a trusted directory"
        )
    control_root = git_common_dir / "agent-os-admission-locks"
    if control_root.exists() and control_root.is_symlink():
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_LOCK_INVALID", "admission lock directory cannot be a symlink"
        )
    control_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    database_digest = content_digest(
        {"canonical_database": str(Path(database).resolve())}
    )
    lock_path = control_root / f"{database_digest}.lock"
    if lock_path.exists() and lock_path.is_symlink():
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_LOCK_INVALID", "admission lock file cannot be a symlink"
        )
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _phase_hook(hook: Callable[[str], None] | None, name: str) -> None:
    if hook is not None:
        hook(name)


def _assert_authority_plan(
    plan: dict[str, Any],
    authority: Any,
    execution_app: Any,
    configuration: tuple[bool, TaskConfigurationRuntime],
) -> None:
    provider_configured, runtime = configuration
    current_grants = {
        capability_id: grant.model_dump(mode="json")
        for capability_id, grant in sorted(runtime.grants.items())
    }
    task_id = str(plan["task_id"])
    if not provider_configured:
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_PROVIDER_UNCONFIGURED",
            "a configured provider is required before admitting a Run",
        )
    comparisons = (
        (
            "provider profile",
            runtime.provider_profile.model_dump(mode="json"),
            plan["provider_profile"],
        ),
        (
            "ResponsibilityLoopBinding",
            asdict(authority.binding),
            plan["responsibility_binding"],
        ),
        (
            "OutcomePortfolio",
            authority.portfolio.model_dump(mode="json"),
            plan["portfolio_record"],
        ),
        ("policy version", runtime.policy_version, plan["policy_version"]),
        (
            "configuration grants",
            _grant_authority_projection(current_grants),
            plan["configuration_grant_authority"],
        ),
        (
            "correction authority",
            execution_app.correction.snapshot(
                task_id,
                _UNRESERVED_RUN_ID,
                TASK_CONFIGURATION_CAPABILITY,
            ).model_dump(mode="json"),
            plan["correction_authority"],
        ),
    )
    for name, actual, expected in comparisons:
        if actual != expected:
            raise SelfDevelopmentAdmissionError(
                "ADMISSION_STATE_DRIFT",
                f"authority preflight: {name} differs from immutable reservation",
            )


def _revalidate_authority_plan(
    *,
    plan: dict[str, Any],
    app: Any,
    execution_app: Any,
    workspace: Path,
    database: Path,
    configuration: tuple[bool, TaskConfigurationRuntime] | None = None,
) -> Any:
    if configuration is None:
        with execution_app.selfdev_admission_configuration_lease() as leased:
            return _revalidate_authority_plan(
                plan=plan,
                app=app,
                execution_app=execution_app,
                workspace=workspace,
                database=database,
                configuration=leased,
            )
    _, runtime = configuration
    authority = resolve_responsibility_authority_context(
        app=app,
        execution_app=execution_app,
        workspace=workspace,
        database=database,
        configuration=runtime,
    )
    _assert_authority_plan(plan, authority, execution_app, configuration)
    return authority


def _assert_equal(phase: str, object_name: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_STATE_DRIFT",
            f"{phase}: {object_name} differs from the immutable admission plan",
        )


@dataclass(frozen=True)
class _AdmissionGraph:
    task: Any
    goal: Goal
    commitment: Commitment
    expected: ExpectedOutcome
    workflow: WorkflowGraph
    snapshot: Any
    run: Any
    link: Any
    persistent: Any | None
    task_created_event_digest: str


def _preflight_admission_graph(
    *,
    plan: dict[str, Any],
    app: Any,
    execution_app: Any,
    database: Path,
    require_persistent: bool,
) -> _AdmissionGraph:
    task_id = str(plan["task_id"])
    goal = Goal.model_validate(plan["goal"])
    commitment = Commitment.model_validate(plan["commitment"])
    expected = ExpectedOutcome.model_validate(plan["expected_outcome"])
    workflow = WorkflowGraph.model_validate(plan["workflow"])
    try:
        events = execution_app.tasks._event_store.read(task_id)
        task = execution_app.tasks.get_task(task_id)
    except Exception as exc:
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_STATE_DRIFT", "PREFLIGHT: exact Task stream is unavailable"
        ) from exc
    expected_types = (
        TaskEventType.TASK_CREATED,
        TaskEventType.TASK_COMMITTED,
        TaskEventType.TASK_CONFIGURATION_SNAPSHOT_SEALED,
        TaskEventType.RUN_STARTED,
    )
    if tuple(event.event_type for event in events) != expected_types:
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_STATE_DRIFT",
            "PREFLIGHT: Task event stream is not the exact four-event admission stream",
        )
    if events[0].event_id != plan["task_event_id"]:
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_STATE_DRIFT", "PREFLIGHT: TASK_CREATED identity drift"
        )
    for index, event in enumerate(events):
        if (
            event.task_id != task_id
            or event.sequence != index + 1
            or event.correlation_id != task_id
            or event.causation_id
            != (events[index - 1].event_id if index else None)
        ):
            raise SelfDevelopmentAdmissionError(
                "ADMISSION_STATE_DRIFT",
                "PREFLIGHT: Task event chain scope or causation drift",
            )
    _assert_equal("PREFLIGHT", "Goal", task.goal, goal)
    _assert_equal("PREFLIGHT", "Commitment", task.commitment, commitment)
    _assert_equal("PREFLIGHT", "ExpectedOutcome", task.expected_outcome, expected)
    _assert_equal("PREFLIGHT", "WorkflowGraph", task.workflow, workflow)
    _assert_equal(
        "PREFLIGHT",
        "TASK_CREATED payload",
        events[0].decoded_payload(),
        {"goal": goal.model_dump(mode="json")},
    )
    _assert_equal(
        "PREFLIGHT",
        "TASK_COMMITTED payload",
        events[1].decoded_payload(),
        {
            "commitment": commitment.model_dump(mode="json"),
            "workflow": workflow.model_dump(mode="json"),
            "workflow_digest": workflow.canonical_digest(),
            "expected_outcome": expected.model_dump(mode="json"),
        },
    )
    if task.configuration_snapshot is None or task.run is None:
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_STATE_DRIFT", "PREFLIGHT: snapshot-bound Run is missing"
        )
    snapshot = task.configuration_snapshot
    run = task.run
    expected_grant = plan["configuration_grants"].get("workspace.run_tests")
    immutable_fields = {
        "task.status": (task.status, TaskStatus.RUNNING),
        "run.status": (run.status, RunStatus.QUEUED),
        "run.active_node_id": (run.active_node_id, None),
        "run.attempt": (run.attempt, 1),
        "run.wait_condition": (run.wait_condition, None),
        "run.replan_count": (run.replan_count, 0),
        "run.configuration_snapshot_id": (
            run.configuration_snapshot_id,
            snapshot.snapshot_id,
        ),
        "run.configuration_snapshot_digest": (
            run.configuration_snapshot_digest,
            snapshot.snapshot_digest,
        ),
        "run.run_id": (run.run_id, snapshot.reserved_run_id),
        "run.provider_profile_id": (
            run.provider_profile_id,
            snapshot.provider_profile.profile_id,
        ),
        "snapshot.consumer_task_id": (snapshot.consumer_task_id, task_id),
        "snapshot.commitment_id": (
            snapshot.commitment_id,
            commitment.commitment_id,
        ),
        "snapshot.principal_id": (snapshot.principal_id, plan["principal_id"]),
        "snapshot.tenant_id": (snapshot.tenant_id, plan["tenant_id"]),
        "snapshot.workspace_id": (snapshot.workspace_id, plan["workspace_id"]),
        "snapshot.workflow": (snapshot.workflow, workflow),
        "snapshot.workflow_digest": (
            snapshot.workflow_digest,
            workflow.canonical_digest(),
        ),
        "snapshot.expected_outcome": (snapshot.expected_outcome, expected),
        "snapshot.expected_outcome_digest": (
            snapshot.expected_outcome_digest,
            content_digest(expected),
        ),
        "snapshot.provider_profile": (
            snapshot.provider_profile.model_dump(mode="json"),
            plan["provider_profile"],
        ),
        "snapshot.provider_profile_digest": (
            snapshot.provider_profile_digest,
            plan["provider_profile_digest"],
        ),
        "snapshot.policy_version": (snapshot.policy_version, plan["policy_version"]),
        "snapshot.policy_digest": (snapshot.policy_digest, POLICY_KERNEL_V1_DIGEST),
        "snapshot.execution_grants": (
            tuple(
                grant.model_dump(mode="json") for grant in snapshot.execution_grants
            ),
            (expected_grant,),
        ),
        "snapshot.optional_prior": (snapshot.optional_prior, None),
    }
    mismatched = tuple(
        name for name, (actual, expected_value) in immutable_fields.items()
        if actual != expected_value
    )
    if expected_grant is None or mismatched:
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_STATE_DRIFT",
            "PREFLIGHT: snapshot or initial Run differs from immutable reservation: "
            + ", ".join(mismatched or ("workspace.run_tests grant missing",)),
        )
    _assert_equal(
        "PREFLIGHT",
        "snapshot event payload",
        events[2].decoded_payload(),
        {"configuration_snapshot": snapshot.model_dump(mode="json")},
    )
    _assert_equal(
        "PREFLIGHT",
        "Run event payload",
        events[3].decoded_payload(),
        {"run": run.model_dump(mode="json")},
    )
    current_epochs = execution_app.correction.snapshot(
        task_id, run.run_id, TASK_CONFIGURATION_CAPABILITY
    )
    if (
        snapshot.observed_correction_epochs != current_epochs
        or execution_app.correction.halted(
            task_id, run.run_id, TASK_CONFIGURATION_CAPABILITY
        )
    ):
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_STATE_DRIFT",
            "PREFLIGHT: correction authority differs from sealed snapshot",
        )
    all_links = tuple(
        link
        for link in app.mandate_responsibility_store.list_links(
            str(plan["mandate_id"]), app.principal, include_revoked=True
        )
        if link.task_id == task_id
    )
    active_links = tuple(
        link
        for link in app.mandate_responsibility_store.list_links(
            str(plan["mandate_id"]), app.principal, include_revoked=False
        )
        if link.task_id == task_id
    )
    if len(all_links) != 1 or len(active_links) != 1 or all_links[0] != active_links[0]:
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_STATE_DRIFT",
            "PREFLIGHT: one unique, never-revoked active MandateTaskLink is required",
        )
    link = active_links[0]
    expected_link_command = MandateTaskLinkCommand(
        task_id=task_id,
        reason=f"SELFDEV admission {plan['admission_id']}",
        work_route=ResponsibilityWorkRoute.SELFDEV,
        selfdev_spec=plan["selfdev_spec"],
    )
    _assert_equal(
        "PREFLIGHT",
        "MandateTaskLink command digest",
        link.command_digest,
        content_digest(expected_link_command),
    )
    portfolio = app.mandate_outcome_portfolio_store.get_view(
        str(plan["mandate_id"]), app.principal, include_resolved_help=True
    )
    _assert_equal(
        "PREFLIGHT",
        "OutcomePortfolio id",
        portfolio.portfolio.portfolio_id,
        plan["portfolio_id"],
    )
    commitments = tuple(
        item for item in portfolio.commitments if item.task_id == task_id
    )
    if len(commitments) > 1 or (require_persistent and len(commitments) != 1):
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_STATE_DRIFT",
            "PREFLIGHT: persistent commitment count is invalid",
        )
    persistent = commitments[0] if commitments else None
    if persistent is not None and (
        persistent.commitment_digest != content_digest(commitment)
        or persistent.expected_outcome_digest != content_digest(expected)
        or persistent.state is not PersistentCommitmentState.OPEN
        or persistent.portfolio_id != plan["portfolio_id"]
    ):
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_STATE_DRIFT",
            "PREFLIGHT: PersistentCommitment differs from immutable reservation",
        )
    if any(item.task_id == task_id for item in portfolio.settlements) or any(
        item.task_id == task_id for item in portfolio.help_requests
    ):
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_STATE_DRIFT",
            "PREFLIGHT: settlement or Help truth already exists for admission Task",
        )
    if task.approval is not None or task.observed_outcome is not None:
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_STATE_DRIFT",
            "PREFLIGHT: approval or outcome truth already exists",
        )
    connection = sqlite3.connect(str(Path(database).resolve()))
    try:
        tables = {
            str(item[0])
            for item in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        task_tables = {
            "responsibility_loop_effects_v2": "task_id",
            "operator_work_events": "task_id",
            "responsibility_cycle_receipts": "task_id",
            "responsibility_cycle_settlements_v2": "task_id",
        }
        for table, column in task_tables.items():
            if table in tables and connection.execute(
                f"SELECT 1 FROM {table} WHERE {column}=? LIMIT 1", (task_id,)
            ).fetchone() is not None:
                raise SelfDevelopmentAdmissionError(
                    "ADMISSION_STATE_DRIFT",
                    f"PREFLIGHT: {table} already contains admission Task truth",
                )
    finally:
        connection.close()
    return _AdmissionGraph(
        task=task,
        goal=goal,
        commitment=commitment,
        expected=expected,
        workflow=workflow,
        snapshot=snapshot,
        run=run,
        link=link,
        persistent=persistent,
        task_created_event_digest=content_digest(events[0]),
    )


def _receipt(
    *,
    row: sqlite3.Row,
    plan: dict[str, Any],
    graph: _AdmissionGraph,
    replayed: bool,
) -> SelfDevelopmentAdmissionReceipt:
    task_id = str(plan["task_id"])
    persistent = graph.persistent
    if persistent is None:
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_STATE_DRIFT", "receipt requires a PersistentCommitment"
        )
    commitment = graph.commitment
    expected = graph.expected
    workflow = graph.workflow
    snapshot = graph.snapshot
    run = graph.run
    link = graph.link
    admission_digest = content_digest(
        {
            "reservation_digest": str(row["reservation_digest"]),
            "task_id": task_id,
            "run_id": run.run_id,
            "link_digest": link.record_digest,
            "persistent_commitment_digest": persistent.record_digest,
        }
    )
    return SelfDevelopmentAdmissionReceipt(
        admission_id=str(plan["admission_id"]),
        admission_digest=admission_digest,
        command_digest=str(row["command_digest"]),
        semantic_key=str(row["semantic_key"]),
        mandate_id=str(plan["mandate_id"]),
        portfolio_id=str(plan["portfolio_id"]),
        task_id=task_id,
        task_created_event_digest=graph.task_created_event_digest,
        commitment_id=commitment.commitment_id,
        commitment_digest=content_digest(commitment),
        expected_outcome_id=expected.expected_outcome_id,
        expected_outcome_digest=content_digest(expected),
        workflow_id=workflow.workflow_id,
        workflow_digest=workflow.canonical_digest(),
        link_id=link.link_id,
        link_digest=link.record_digest,
        persistent_commitment_id=persistent.commitment_record_id,
        persistent_commitment_digest=persistent.record_digest,
        snapshot_id=snapshot.snapshot_id,
        snapshot_digest=snapshot.snapshot_digest,
        run_id=run.run_id,
        work_spec_digest=content_digest(
            SelfDevelopmentWorkSpec.model_validate(plan["selfdev_spec"])
        ),
        replayed=replayed,
    )


def admit_self_development(
    *,
    app: Any,
    execution_app: Any,
    workspace: Path,
    database: Path,
    command: SelfDevelopmentAdmissionCommand,
    source_digest: str | None = None,
    clock: Callable[[], datetime] = _utc_now,
    phase_hook: Callable[[str], None] | None = None,
) -> SelfDevelopmentAdmissionReceipt:
    """Converge one durable responsibility graph; does not execute the Task."""
    workspace = Path(workspace).resolve()
    database = Path(database).resolve()
    command_digest = content_digest(command)
    canonical_source_digest = hashlib.sha256(
        canonical_json(command).encode("utf-8")
    ).hexdigest()
    source_digest = source_digest or canonical_source_digest
    with _admission_lock(workspace, database):
        with execution_app.selfdev_admission_configuration_lease() as configuration:
            provider_configured, runtime = configuration
            authority = resolve_responsibility_authority_context(
                app=app,
                execution_app=execution_app,
                workspace=workspace,
                database=database,
                configuration=runtime,
            )
        if not provider_configured:
            raise SelfDevelopmentAdmissionError(
                "ADMISSION_PROVIDER_UNCONFIGURED",
                "a configured provider is required before admitting a Run",
            )
        existing_store = SQLiteSelfDevelopmentAdmissionStore(database)
        connection = sqlite3.connect(str(database))
        connection.row_factory = sqlite3.Row
        try:
            existing = connection.execute(
                f"SELECT * FROM {_ADMISSION_TABLE} WHERE mandate_id=? AND admission_id=?",
                (authority.mandate_id, command.admission_id),
            ).fetchone()
        finally:
            connection.close()
        if existing is not None:
            existing_store._validate_row(existing)
            if str(existing["command_digest"]) != command_digest:
                raise SelfDevelopmentAdmissionError(
                    "ADMISSION_COMMAND_CONFLICT",
                    "admission_id is already reserved for a different typed command",
                )
        existing_phase = (
            SelfDevelopmentAdmissionPhase(str(existing["phase"]))
            if existing is not None
            else None
        )
        head, write_set = _validate_workspace(
            workspace,
            command,
            allowed_dirty_paths=(
                tuple(sorted(command.selfdev_spec.allowed_write_paths))
                if existing_phase is SelfDevelopmentAdmissionPhase.ADMITTED
                else ()
            ),
        )
        verifier_bindings = _seal_verifier_bindings(workspace, command)
        sealed_selfdev_spec = SelfDevelopmentWorkSpec.model_validate(
            {
                **command.selfdev_spec.model_dump(mode="json"),
                "verifier_bindings": [
                    binding.model_dump(mode="json")
                    for binding in verifier_bindings
                ],
            }
        )
        repository_root_digest = content_digest({"repository_root": str(workspace)})
        semantic_key = content_digest(
            {
                "mandate_id": authority.mandate_id,
                "repository_root_digest": repository_root_digest,
                "repository_head": head,
                "write_set": write_set,
                "verifier_bindings": [
                    binding.model_dump(mode="json")
                    for binding in verifier_bindings
                ],
            }
        )
        provider_profile_digest = content_digest(runtime.provider_profile)
        configuration_grants = {
            capability_id: grant.model_dump(mode="json")
            for capability_id, grant in sorted(runtime.grants.items())
        }
        created_at = clock()
        proposed_plan = _plan(
            command=command,
            selfdev_spec=sealed_selfdev_spec,
            command_digest=command_digest,
            semantic_key=semantic_key,
            mandate_id=authority.mandate_id,
            portfolio_id=authority.portfolio.portfolio_id,
            principal_id=authority.binding.principal_id,
            tenant_id=authority.binding.tenant_id,
            workspace_id=authority.binding.workspace_id,
            responsibility_binding=asdict(authority.binding),
            portfolio_record=authority.portfolio.model_dump(mode="json"),
            provider_profile=runtime.provider_profile.model_dump(mode="json"),
            provider_profile_digest=provider_profile_digest,
            policy_version=runtime.policy_version,
            configuration_grants=configuration_grants,
            created_at=created_at,
        )
        proposed_plan["correction_authority"] = execution_app.correction.snapshot(
            str(proposed_plan["task_id"]),
            _UNRESERVED_RUN_ID,
            TASK_CONFIGURATION_CAPABILITY,
        ).model_dump(mode="json")
        _revalidate_authority_plan(
            plan=proposed_plan,
            app=app,
            execution_app=execution_app,
            workspace=workspace,
            database=database,
        )
        row, replayed = existing_store.reserve(
            mandate_id=authority.mandate_id,
            admission_id=command.admission_id,
            command_digest=command_digest,
            source_digest=source_digest,
            semantic_key=semantic_key,
            plan=proposed_plan,
        )
        plan = json.loads(str(row["plan_json"]))
        authority = _revalidate_authority_plan(
            plan=plan,
            app=app,
            execution_app=execution_app,
            workspace=workspace,
            database=database,
        )
        phase = SelfDevelopmentAdmissionPhase(str(row["phase"]))
        task_id = str(plan["task_id"])
        goal = Goal.model_validate(plan["goal"])
        commitment = Commitment.model_validate(plan["commitment"])
        expected_outcome = ExpectedOutcome.model_validate(plan["expected_outcome"])
        workflow = WorkflowGraph.model_validate(plan["workflow"])
        graph: _AdmissionGraph | None = None

        def revalidate() -> Any:
            return _revalidate_authority_plan(
                plan=plan,
                app=app,
                execution_app=execution_app,
                workspace=workspace,
                database=database,
            )

        def advance(
            expected_phase: SelfDevelopmentAdmissionPhase,
            target_phase: SelfDevelopmentAdmissionPhase,
            *,
            validate: bool = True,
        ) -> None:
            if validate:
                revalidate()
            existing_store.advance(
                authority.mandate_id,
                command.admission_id,
                expected_phase,
                target_phase,
            )

        if _PHASE_ORDER.index(phase) <= _PHASE_ORDER.index(
            SelfDevelopmentAdmissionPhase.RESERVED
        ):
            revalidate()
            task = execution_app.tasks.ensure_task(
                task_id,
                goal,
                event_id=str(plan["task_event_id"]),
                occurred_at=goal.created_at,
            )
            _assert_equal("TASK_CREATED", "Goal", task.goal, goal)
            _phase_hook(phase_hook, "AFTER_TASK_CREATED")
            advance(
                SelfDevelopmentAdmissionPhase.RESERVED,
                SelfDevelopmentAdmissionPhase.TASK_CREATED,
            )
            phase = SelfDevelopmentAdmissionPhase.TASK_CREATED

        if _PHASE_ORDER.index(phase) <= _PHASE_ORDER.index(
            SelfDevelopmentAdmissionPhase.TASK_CREATED
        ):
            task = execution_app.tasks.get_task(task_id)
            if task.status is TaskStatus.DRAFT:
                revalidate()
                task = execution_app.tasks.commit_task(
                    task_id, commitment, workflow, expected_outcome
                )
            _assert_equal("TASK_COMMITTED", "Commitment", task.commitment, commitment)
            _assert_equal(
                "TASK_COMMITTED",
                "ExpectedOutcome",
                task.expected_outcome,
                expected_outcome,
            )
            _assert_equal("TASK_COMMITTED", "WorkflowGraph", task.workflow, workflow)
            _phase_hook(phase_hook, "AFTER_TASK_COMMITTED")
            advance(
                SelfDevelopmentAdmissionPhase.TASK_CREATED,
                SelfDevelopmentAdmissionPhase.TASK_COMMITTED,
            )
            phase = SelfDevelopmentAdmissionPhase.TASK_COMMITTED

        if _PHASE_ORDER.index(phase) <= _PHASE_ORDER.index(
            SelfDevelopmentAdmissionPhase.TASK_COMMITTED
        ):
            revalidate()
            snapshot = execution_app.seal_task_configuration(task_id, {})
            if content_digest(snapshot.provider_profile) != provider_profile_digest:
                raise SelfDevelopmentAdmissionError(
                    "ADMISSION_STATE_DRIFT",
                    "CONFIGURATION_SEALED: provider profile drift",
                )
            _phase_hook(phase_hook, "AFTER_CONFIGURATION_SEALED")
            advance(
                SelfDevelopmentAdmissionPhase.TASK_COMMITTED,
                SelfDevelopmentAdmissionPhase.CONFIGURATION_SEALED,
            )
            phase = SelfDevelopmentAdmissionPhase.CONFIGURATION_SEALED

        if _PHASE_ORDER.index(phase) <= _PHASE_ORDER.index(
            SelfDevelopmentAdmissionPhase.CONFIGURATION_SEALED
        ):
            task = execution_app.tasks.get_task(task_id)
            if task.configuration_snapshot is None:
                raise SelfDevelopmentAdmissionError(
                    "ADMISSION_STATE_DRIFT",
                    "RUN_STARTED: configuration snapshot missing",
                )
            if task.run is None:
                revalidate()
                task = execution_app.start_run(
                    task_id, task.configuration_snapshot.snapshot_id
                )
            if (
                task.run is None
                or task.run.run_id != task.configuration_snapshot.reserved_run_id
            ):
                raise SelfDevelopmentAdmissionError(
                    "ADMISSION_STATE_DRIFT", "RUN_STARTED: reserved Run binding drift"
                )
            _phase_hook(phase_hook, "AFTER_RUN_STARTED")
            advance(
                SelfDevelopmentAdmissionPhase.CONFIGURATION_SEALED,
                SelfDevelopmentAdmissionPhase.RUN_STARTED,
            )
            phase = SelfDevelopmentAdmissionPhase.RUN_STARTED

        link_command = MandateTaskLinkCommand(
            task_id=task_id,
            reason=f"SELFDEV admission {command.admission_id}",
            work_route=ResponsibilityWorkRoute.SELFDEV,
            selfdev_spec=plan["selfdev_spec"],
        )
        if _PHASE_ORDER.index(phase) <= _PHASE_ORDER.index(
            SelfDevelopmentAdmissionPhase.RUN_STARTED
        ):
            revalidate()
            link = app.mandate_responsibility_store.create_link(
                link_command, authority.mandate_id, app.principal
            )
            _assert_equal(
                "LINKED",
                "MandateTaskLink command digest",
                link.command_digest,
                content_digest(link_command),
            )
            _phase_hook(phase_hook, "AFTER_LINKED")
            advance(
                SelfDevelopmentAdmissionPhase.RUN_STARTED,
                SelfDevelopmentAdmissionPhase.LINKED,
            )
            phase = SelfDevelopmentAdmissionPhase.LINKED

        attach_command = PersistentCommitmentAttachCommand(
            task_id=task_id,
            commitment_digest=content_digest(commitment),
            expected_outcome_digest=content_digest(expected_outcome),
            reason=f"SELFDEV admission {command.admission_id}",
        )
        if _PHASE_ORDER.index(phase) <= _PHASE_ORDER.index(
            SelfDevelopmentAdmissionPhase.LINKED
        ):
            graph = _preflight_admission_graph(
                plan=plan,
                app=app,
                execution_app=execution_app,
                database=database,
                require_persistent=False,
            )
            _phase_hook(phase_hook, "AFTER_FINAL_PREFLIGHT")
            with execution_app.selfdev_admission_configuration_lease() as configuration:

                def guarded_pre_insert() -> None:
                    nonlocal graph
                    graph = _preflight_admission_graph(
                        plan=plan,
                        app=app,
                        execution_app=execution_app,
                        database=database,
                        require_persistent=False,
                    )
                    _revalidate_authority_plan(
                        plan=plan,
                        app=app,
                        execution_app=execution_app,
                        workspace=workspace,
                        database=database,
                        configuration=configuration,
                    )
                    _phase_hook(phase_hook, "AFTER_SERIALIZED_CONFIG_GUARD")

                try:
                    persistent = (
                        app.mandate_outcome_portfolio_store.attach_commitment(
                            attach_command,
                            authority.mandate_id,
                            app.principal,
                            pre_insert_guard=guarded_pre_insert,
                        )
                    )
                except SelfDevelopmentAdmissionError:
                    raise
                except Exception as exc:
                    raise SelfDevelopmentAdmissionError(
                        "ADMISSION_STATE_DRIFT",
                        "COMMITMENT_ATTACH: serialized authority or graph validation failed",
                    ) from exc
            _assert_equal(
                "COMMITMENT_ATTACHED",
                "commitment digest",
                persistent.commitment_digest,
                attach_command.commitment_digest,
            )
            graph = replace(graph, persistent=persistent)
            _phase_hook(phase_hook, "AFTER_COMMITMENT_ATTACHED")
            advance(
                SelfDevelopmentAdmissionPhase.LINKED,
                SelfDevelopmentAdmissionPhase.COMMITMENT_ATTACHED,
                validate=False,
            )
            phase = SelfDevelopmentAdmissionPhase.COMMITMENT_ATTACHED

        row = existing_store.get(authority.mandate_id, command.admission_id)
        if graph is None or graph.persistent is None:
            graph = _preflight_admission_graph(
                plan=plan,
                app=app,
                execution_app=execution_app,
                database=database,
                require_persistent=True,
            )
        _receipt(row=row, plan=plan, graph=graph, replayed=replayed)
        if phase is SelfDevelopmentAdmissionPhase.COMMITMENT_ATTACHED:
            _phase_hook(phase_hook, "BEFORE_ADMITTED")
            advance(
                SelfDevelopmentAdmissionPhase.COMMITMENT_ATTACHED,
                SelfDevelopmentAdmissionPhase.ADMITTED,
                validate=False,
            )
        elif phase is not SelfDevelopmentAdmissionPhase.ADMITTED:
            raise SelfDevelopmentAdmissionError(
                "ADMISSION_STATE_DRIFT", f"unexpected final phase {phase.value}"
            )
        _phase_hook(phase_hook, "AFTER_ADMITTED")
        row = existing_store.get(authority.mandate_id, command.admission_id)
        return _receipt(row=row, plan=plan, graph=graph, replayed=replayed)
