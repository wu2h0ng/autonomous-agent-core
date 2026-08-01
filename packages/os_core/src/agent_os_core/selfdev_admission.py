from __future__ import annotations

import fcntl
import hashlib
import json
import sqlite3
import subprocess
from collections.abc import Callable
from contextlib import contextmanager
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
    ResourceBudget,
    ResponsibilityWorkRoute,
    SelfDevelopmentAdmissionCommand,
    SelfDevelopmentAdmissionReceipt,
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
from .task_configuration import TASK_CONFIGURATION_CAPABILITY


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
    LINKED = "LINKED"
    COMMITMENT_ATTACHED = "COMMITMENT_ATTACHED"
    CONFIGURATION_SEALED = "CONFIGURATION_SEALED"
    RUN_STARTED = "RUN_STARTED"
    ADMITTED = "ADMITTED"


_PHASE_ORDER = tuple(SelfDevelopmentAdmissionPhase)
_ADMISSION_TABLE = "selfdev_admissions_v1"
_POLICY_EXPIRY_DAYS = 30


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _git(workspace: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(workspace), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_WORKTREE_INVALID",
            completed.stderr.strip() or f"git {' '.join(args)} failed",
        )
    return completed.stdout.strip()


def _validate_workspace(
    workspace: Path,
    command: SelfDevelopmentAdmissionCommand,
    *,
    require_clean: bool,
) -> tuple[str, tuple[str, ...]]:
    workspace = workspace.resolve()
    if not (workspace / ".git").is_file():
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_WORKTREE_INVALID",
            "workspace must be a linked Git worktree, not a primary checkout",
        )
    head = _git(workspace, "rev-parse", "HEAD")
    branch = _git(workspace, "symbolic-ref", "--quiet", "--short", "HEAD")
    if head != command.selfdev_spec.repository_head:
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_WORKTREE_DRIFT",
            "repository HEAD differs from the frozen SELFDEV spec",
        )
    if branch != command.selfdev_spec.isolated_branch:
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_WORKTREE_DRIFT",
            "isolated branch differs from the frozen SELFDEV spec",
        )
    status = _git(workspace, "status", "--porcelain=v1", "--untracked-files=all")
    if require_clean and status:
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_WORKTREE_DIRTY",
            f"linked worktree must be clean at first admission: {status}",
        )
    normalized = tuple(sorted(command.selfdev_spec.allowed_write_paths))
    for relative in normalized:
        candidate = workspace / relative
        if candidate.is_symlink() or not candidate.is_file():
            raise SelfDevelopmentAdmissionError(
                "ADMISSION_WORKTREE_INVALID",
                f"write target is missing, non-file, or symlink: {relative}",
            )
        try:
            candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise SelfDevelopmentAdmissionError(
                "ADMISSION_WORKTREE_INVALID",
                f"write target is not readable UTF-8: {relative}",
            ) from None
    return head, normalized


def _identity(kind: str, identity_digest: str) -> str:
    return f"{kind}:selfdev-admission:{identity_digest}"


def _plan(
    *,
    command: SelfDevelopmentAdmissionCommand,
    command_digest: str,
    semantic_key: str,
    mandate_id: str,
    portfolio_id: str,
    principal_id: str,
    tenant_id: str,
    workspace_id: str,
    provider_profile_digest: str,
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
        "provider_profile_digest": provider_profile_digest,
        "created_at": created_at.isoformat(),
        "task_id": task_id,
        "task_event_id": _identity("event-created", identity_digest),
        "goal": goal.model_dump(mode="json"),
        "commitment": commitment.model_dump(mode="json"),
        "expected_outcome": expected.model_dump(mode="json"),
        "workflow": workflow.model_dump(mode="json"),
        "selfdev_spec": command.selfdev_spec.model_dump(mode="json"),
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
                "phase TEXT NOT NULL, receipt_json TEXT, "
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
                if (
                    str(existing["command_digest"]) != command_digest
                    or str(existing["source_digest"]) != source_digest
                ):
                    raise SelfDevelopmentAdmissionError(
                        "ADMISSION_COMMAND_CONFLICT",
                        "admission_id is already reserved for different command bytes",
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
        *,
        receipt: SelfDevelopmentAdmissionReceipt | None = None,
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
            receipt_json = (
                receipt.model_dump_json() if receipt is not None else row["receipt_json"]
            )
            connection.execute(
                f"UPDATE {_ADMISSION_TABLE} SET phase=?, receipt_json=? "
                "WHERE mandate_id=? AND admission_id=?",
                (target.value, receipt_json, mandate_id, admission_id),
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
def _admission_lock(database: Path):
    lock_path = Path(f"{Path(database).resolve()}.selfdev-admission.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _phase_hook(hook: Callable[[str], None] | None, name: str) -> None:
    if hook is not None:
        hook(name)


def _assert_equal(phase: str, object_name: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_STATE_DRIFT",
            f"{phase}: {object_name} differs from the immutable admission plan",
        )


def _created_event_digest(execution_app: Any, task_id: str) -> str:
    events = execution_app.tasks._event_store.read(task_id)
    if not events or events[0].event_type is not TaskEventType.TASK_CREATED:
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_STATE_DRIFT", "TASK_CREATED: canonical event is missing"
        )
    return content_digest(events[0])


def _receipt(
    *,
    row: sqlite3.Row,
    plan: dict[str, Any],
    app: Any,
    execution_app: Any,
    replayed: bool,
) -> SelfDevelopmentAdmissionReceipt:
    task_id = str(plan["task_id"])
    task = execution_app.tasks.get_task(task_id)
    goal = Goal.model_validate(plan["goal"])
    commitment = Commitment.model_validate(plan["commitment"])
    expected = ExpectedOutcome.model_validate(plan["expected_outcome"])
    workflow = WorkflowGraph.model_validate(plan["workflow"])
    _assert_equal("ADMITTED", "Goal", task.goal, goal)
    _assert_equal("ADMITTED", "Commitment", task.commitment, commitment)
    _assert_equal("ADMITTED", "ExpectedOutcome", task.expected_outcome, expected)
    _assert_equal("ADMITTED", "WorkflowGraph", task.workflow, workflow)
    if task.configuration_snapshot is None or task.run is None:
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_STATE_DRIFT", "ADMITTED: snapshot-bound Run is missing"
        )
    snapshot = task.configuration_snapshot
    run = task.run
    if (
        run.configuration_snapshot_id != snapshot.snapshot_id
        or run.configuration_snapshot_digest != snapshot.snapshot_digest
        or run.run_id != snapshot.reserved_run_id
        or run.provider_profile_id != snapshot.provider_profile.profile_id
    ):
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_STATE_DRIFT", "ADMITTED: Run/snapshot binding drift"
        )
    links = tuple(
        link
        for link in app.mandate_responsibility_store.list_links(
            str(plan["mandate_id"]), app.principal
        )
        if link.task_id == task_id
    )
    if len(links) != 1:
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_STATE_DRIFT", "ADMITTED: exact active MandateTaskLink missing"
        )
    link = links[0]
    expected_link_command = MandateTaskLinkCommand(
        task_id=task_id,
        reason=f"SELFDEV admission {plan['admission_id']}",
        work_route=ResponsibilityWorkRoute.SELFDEV,
        selfdev_spec=plan["selfdev_spec"],
    )
    _assert_equal(
        "ADMITTED", "MandateTaskLink command digest", link.command_digest,
        content_digest(expected_link_command)
    )
    portfolio = app.mandate_outcome_portfolio_store.get_view(
        str(plan["mandate_id"]), app.principal, include_resolved_help=True
    )
    _assert_equal("ADMITTED", "OutcomePortfolio id", portfolio.portfolio.portfolio_id, plan["portfolio_id"])
    commitments = tuple(item for item in portfolio.commitments if item.task_id == task_id)
    if len(commitments) != 1:
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_STATE_DRIFT", "ADMITTED: exact PersistentCommitment missing"
        )
    persistent = commitments[0]
    _assert_equal("ADMITTED", "PersistentCommitment commitment digest", persistent.commitment_digest, content_digest(commitment))
    _assert_equal("ADMITTED", "PersistentCommitment expected digest", persistent.expected_outcome_digest, content_digest(expected))
    if task.approval is not None or task.observed_outcome is not None:
        raise SelfDevelopmentAdmissionError(
            "ADMISSION_STATE_DRIFT", "ADMITTED: admission created execution truth"
        )
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
        task_created_event_digest=_created_event_digest(execution_app, task_id),
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
            SelfDevelopmentAdmissionCommand.model_validate(
                {
                    "admission_id": plan["admission_id"],
                    "statement": goal.statement,
                    "deliverables": commitment.deliverables,
                    "acceptance_criteria": commitment.acceptance_criteria,
                    "selfdev_spec": plan["selfdev_spec"],
                }
            ).selfdev_spec
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
    with _admission_lock(database):
        authority = resolve_responsibility_authority_context(
            app=app,
            execution_app=execution_app,
            workspace=workspace,
            database=database,
        )
        if not execution_app.provider_configured:
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
            if (
                str(existing["command_digest"]) != command_digest
                or str(existing["source_digest"]) != source_digest
            ):
                raise SelfDevelopmentAdmissionError(
                    "ADMISSION_COMMAND_CONFLICT",
                    "admission_id is already reserved for different command bytes",
                )
        head, write_set = _validate_workspace(
            workspace, command, require_clean=existing is None
        )
        repository_root_digest = content_digest({"repository_root": str(workspace)})
        semantic_key = content_digest(
            {
                "mandate_id": authority.mandate_id,
                "repository_root_digest": repository_root_digest,
                "repository_head": head,
                "write_set": write_set,
            }
        )
        provider_profile_digest = content_digest(execution_app.provider_profile)
        created_at = clock()
        proposed_plan = _plan(
            command=command,
            command_digest=command_digest,
            semantic_key=semantic_key,
            mandate_id=authority.mandate_id,
            portfolio_id=authority.portfolio.portfolio_id,
            principal_id=authority.binding.principal_id,
            tenant_id=authority.binding.tenant_id,
            workspace_id=authority.binding.workspace_id,
            provider_profile_digest=provider_profile_digest,
            created_at=created_at,
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
        if (
            plan["portfolio_id"] != authority.portfolio.portfolio_id
            or plan["principal_id"] != authority.binding.principal_id
            or plan["provider_profile_digest"] != provider_profile_digest
        ):
            raise SelfDevelopmentAdmissionError(
                "ADMISSION_STATE_DRIFT",
                "authority, portfolio, or provider differs from immutable reservation",
            )
        phase = SelfDevelopmentAdmissionPhase(str(row["phase"]))
        task_id = str(plan["task_id"])
        goal = Goal.model_validate(plan["goal"])
        commitment = Commitment.model_validate(plan["commitment"])
        expected_outcome = ExpectedOutcome.model_validate(plan["expected_outcome"])
        workflow = WorkflowGraph.model_validate(plan["workflow"])

        if _PHASE_ORDER.index(phase) <= _PHASE_ORDER.index(SelfDevelopmentAdmissionPhase.RESERVED):
            task = execution_app.tasks.ensure_task(
                task_id,
                goal,
                event_id=str(plan["task_event_id"]),
                occurred_at=goal.created_at,
            )
            _assert_equal("TASK_CREATED", "Goal", task.goal, goal)
            _phase_hook(phase_hook, "AFTER_TASK_CREATED")
            existing_store.advance(authority.mandate_id, command.admission_id, SelfDevelopmentAdmissionPhase.RESERVED, SelfDevelopmentAdmissionPhase.TASK_CREATED)
            phase = SelfDevelopmentAdmissionPhase.TASK_CREATED

        if _PHASE_ORDER.index(phase) <= _PHASE_ORDER.index(SelfDevelopmentAdmissionPhase.TASK_CREATED):
            task = execution_app.tasks.get_task(task_id)
            if task.status is TaskStatus.DRAFT:
                task = execution_app.tasks.commit_task(task_id, commitment, workflow, expected_outcome)
            _assert_equal("TASK_COMMITTED", "Commitment", task.commitment, commitment)
            _assert_equal("TASK_COMMITTED", "ExpectedOutcome", task.expected_outcome, expected_outcome)
            _assert_equal("TASK_COMMITTED", "WorkflowGraph", task.workflow, workflow)
            _phase_hook(phase_hook, "AFTER_TASK_COMMITTED")
            existing_store.advance(authority.mandate_id, command.admission_id, SelfDevelopmentAdmissionPhase.TASK_CREATED, SelfDevelopmentAdmissionPhase.TASK_COMMITTED)
            phase = SelfDevelopmentAdmissionPhase.TASK_COMMITTED

        link_command = MandateTaskLinkCommand(
            task_id=task_id,
            reason=f"SELFDEV admission {command.admission_id}",
            work_route=ResponsibilityWorkRoute.SELFDEV,
            selfdev_spec=command.selfdev_spec,
        )
        if _PHASE_ORDER.index(phase) <= _PHASE_ORDER.index(SelfDevelopmentAdmissionPhase.TASK_COMMITTED):
            link = app.mandate_responsibility_store.create_link(link_command, authority.mandate_id, app.principal)
            _assert_equal("LINKED", "MandateTaskLink command digest", link.command_digest, content_digest(link_command))
            _phase_hook(phase_hook, "AFTER_LINKED")
            existing_store.advance(authority.mandate_id, command.admission_id, SelfDevelopmentAdmissionPhase.TASK_COMMITTED, SelfDevelopmentAdmissionPhase.LINKED)
            phase = SelfDevelopmentAdmissionPhase.LINKED

        attach_command = PersistentCommitmentAttachCommand(
            task_id=task_id,
            commitment_digest=content_digest(commitment),
            expected_outcome_digest=content_digest(expected_outcome),
            reason=f"SELFDEV admission {command.admission_id}",
        )
        if _PHASE_ORDER.index(phase) <= _PHASE_ORDER.index(SelfDevelopmentAdmissionPhase.LINKED):
            persistent = app.mandate_outcome_portfolio_store.attach_commitment(attach_command, authority.mandate_id, app.principal)
            _assert_equal("COMMITMENT_ATTACHED", "commitment digest", persistent.commitment_digest, attach_command.commitment_digest)
            _phase_hook(phase_hook, "AFTER_COMMITMENT_ATTACHED")
            existing_store.advance(authority.mandate_id, command.admission_id, SelfDevelopmentAdmissionPhase.LINKED, SelfDevelopmentAdmissionPhase.COMMITMENT_ATTACHED)
            phase = SelfDevelopmentAdmissionPhase.COMMITMENT_ATTACHED

        if _PHASE_ORDER.index(phase) <= _PHASE_ORDER.index(SelfDevelopmentAdmissionPhase.COMMITMENT_ATTACHED):
            snapshot = execution_app.seal_task_configuration(task_id, {})
            if content_digest(snapshot.provider_profile) != provider_profile_digest:
                raise SelfDevelopmentAdmissionError("ADMISSION_STATE_DRIFT", "CONFIGURATION_SEALED: provider profile drift")
            _phase_hook(phase_hook, "AFTER_CONFIGURATION_SEALED")
            existing_store.advance(authority.mandate_id, command.admission_id, SelfDevelopmentAdmissionPhase.COMMITMENT_ATTACHED, SelfDevelopmentAdmissionPhase.CONFIGURATION_SEALED)
            phase = SelfDevelopmentAdmissionPhase.CONFIGURATION_SEALED

        if _PHASE_ORDER.index(phase) <= _PHASE_ORDER.index(SelfDevelopmentAdmissionPhase.CONFIGURATION_SEALED):
            task = execution_app.tasks.get_task(task_id)
            if task.configuration_snapshot is None:
                raise SelfDevelopmentAdmissionError("ADMISSION_STATE_DRIFT", "RUN_STARTED: configuration snapshot missing")
            if task.run is None:
                task = execution_app.start_run(task_id, task.configuration_snapshot.snapshot_id)
            if task.run is None or task.run.run_id != task.configuration_snapshot.reserved_run_id:
                raise SelfDevelopmentAdmissionError("ADMISSION_STATE_DRIFT", "RUN_STARTED: reserved Run binding drift")
            _phase_hook(phase_hook, "AFTER_RUN_STARTED")
            existing_store.advance(authority.mandate_id, command.admission_id, SelfDevelopmentAdmissionPhase.CONFIGURATION_SEALED, SelfDevelopmentAdmissionPhase.RUN_STARTED)
            phase = SelfDevelopmentAdmissionPhase.RUN_STARTED

        row = existing_store.get(authority.mandate_id, command.admission_id)
        receipt = _receipt(row=row, plan=plan, app=app, execution_app=execution_app, replayed=replayed)
        if phase is SelfDevelopmentAdmissionPhase.RUN_STARTED:
            _phase_hook(phase_hook, "BEFORE_ADMITTED")
            existing_store.advance(authority.mandate_id, command.admission_id, SelfDevelopmentAdmissionPhase.RUN_STARTED, SelfDevelopmentAdmissionPhase.ADMITTED, receipt=receipt)
        elif phase is not SelfDevelopmentAdmissionPhase.ADMITTED:
            raise SelfDevelopmentAdmissionError("ADMISSION_STATE_DRIFT", f"unexpected final phase {phase.value}")
        _phase_hook(phase_hook, "AFTER_ADMITTED")
        row = existing_store.get(authority.mandate_id, command.admission_id)
        return _receipt(row=row, plan=plan, app=app, execution_app=execution_app, replayed=replayed)
