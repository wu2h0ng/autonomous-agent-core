"""Founder-facing Mandate terminal entry (non-chat).

Distinct from coding-agent / SELFDEV loops: load durable Mandate authority,
print mission/commitments without pasted chat context, emit structured
HelpRequest into a durable inbox, and fail closed without attach/auth.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent_os_contracts import (
    EnvironmentBindingAuthorization,
    HelpRequest,
    MandateCommitmentContext,
    MandateOutcomeContext,
    MandateRelevanceContext,
    RatifiedMandateRef,
    RelevanceAssessorRef,
    canonical_json,
)

from .errors import SituationalTrustDenied
from .situated_persistence import SQLiteSituatedAssessmentStore

ATTACH_FILENAME = "mandate_attach.json"
CONTEXT_FILENAME = "mandate_relevance_context.json"
HELP_INBOX_FILENAME = "mandate_help_inbox.jsonl"


class MandateTerminalError(ValueError):
    """Fail-closed terminal admission / emission error."""


@dataclass(frozen=True)
class MandateAttachSession:
    mandate_id: str
    environment_binding_id: str
    principal_id: str
    tenant_id: str
    workspace_id: str
    database: str
    attached_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "mandate_id": self.mandate_id,
            "environment_binding_id": self.environment_binding_id,
            "principal_id": self.principal_id,
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "database": self.database,
            "attached_at": self.attached_at,
        }


def _require_nonempty(name: str, value: str | None) -> str:
    if value is None or not str(value).strip():
        raise MandateTerminalError(f"{name} is required")
    return str(value).strip()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def attach_path(workspace: Path) -> Path:
    return Path(workspace) / ".agent_os" / ATTACH_FILENAME


def context_path(workspace: Path) -> Path:
    return Path(workspace) / ".agent_os" / CONTEXT_FILENAME


def help_inbox_path(workspace: Path) -> Path:
    return Path(workspace) / ".agent_os" / HELP_INBOX_FILENAME


def bootstrap_mandate(
    *,
    database: Path,
    mandate: RatifiedMandateRef,
    relevance_context: MandateRelevanceContext | None = None,
    workspace: Path | None = None,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    """Persist ratified Mandate into durable situated store; optional context sidecar."""
    when = evaluated_at or _utc_now()
    store = SQLiteSituatedAssessmentStore(Path(database), mandates=(mandate,))
    # reopen verifies durable bytes
    restarted = SQLiteSituatedAssessmentStore(Path(database))
    binding = mandate.allowed_environment_bindings[0]
    resolved, _ = restarted.resolve_active(
        mandate.mandate_id,
        binding.environment_binding_id,
        principal_id=mandate.owner_principal_id,
        tenant_id=mandate.tenant_id,
        workspace_id=mandate.workspace_id,
        evaluated_at=when,
    )
    context_written = None
    if relevance_context is not None:
        if workspace is None:
            raise MandateTerminalError(
                "workspace is required when relevance_context is provided"
            )
        _write_relevance_context(Path(workspace), relevance_context, mandate)
        context_written = str(context_path(Path(workspace)))
    del store
    return {
        "mandate_id": resolved.mandate_id,
        "mandate_version": resolved.version,
        "mandate_digest": resolved.mandate_digest,
        "status": resolved.status.value,
        "database": str(Path(database)),
        "relevance_context_path": context_written,
        "claim_ceiling": "MANDATE_TERMINAL_BOOTSTRAP / NO_AUTONOMY",
    }


def attach_mandate(
    *,
    workspace: Path,
    database: Path,
    mandate_id: str,
    environment_binding_id: str,
    principal_id: str,
    tenant_id: str,
    workspace_id: str,
    evaluated_at: datetime | None = None,
) -> MandateAttachSession:
    """Bind a local terminal session after durable resolve_active succeeds."""
    mandate_id = _require_nonempty("mandate_id", mandate_id)
    environment_binding_id = _require_nonempty(
        "environment_binding_id", environment_binding_id
    )
    principal_id = _require_nonempty("principal_id", principal_id)
    tenant_id = _require_nonempty("tenant_id", tenant_id)
    workspace_id = _require_nonempty("workspace_id", workspace_id)
    when = evaluated_at or _utc_now()
    store = SQLiteSituatedAssessmentStore(Path(database))
    try:
        store.resolve_active(
            mandate_id,
            environment_binding_id,
            principal_id=principal_id,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            evaluated_at=when,
        )
    except SituationalTrustDenied as exc:
        raise MandateTerminalError(f"mandate attach denied: {exc}") from exc
    session = MandateAttachSession(
        mandate_id=mandate_id,
        environment_binding_id=environment_binding_id,
        principal_id=principal_id,
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        database=str(Path(database).resolve()),
        attached_at=when.isoformat(),
    )
    path = attach_path(Path(workspace))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(session.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return session


def load_attach_session(workspace: Path) -> MandateAttachSession:
    path = attach_path(Path(workspace))
    if not path.is_file():
        raise MandateTerminalError(
            f"mandate attach missing: {path} (attach a mandate via the admin API first)"
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    required = (
        "mandate_id",
        "environment_binding_id",
        "principal_id",
        "tenant_id",
        "workspace_id",
        "database",
        "attached_at",
    )
    missing = [k for k in required if not str(raw.get(k) or "").strip()]
    if missing:
        raise MandateTerminalError(f"mandate attach incomplete: {missing}")
    return MandateAttachSession(
        mandate_id=str(raw["mandate_id"]),
        environment_binding_id=str(raw["environment_binding_id"]),
        principal_id=str(raw["principal_id"]),
        tenant_id=str(raw["tenant_id"]),
        workspace_id=str(raw["workspace_id"]),
        database=str(raw["database"]),
        attached_at=str(raw["attached_at"]),
    )


def mandate_status(
    *,
    workspace: Path,
    evaluated_at: datetime | None = None,
    session: MandateAttachSession | None = None,
) -> dict[str, Any]:
    """Print durable Mandate + optional open commitments without chat paste."""
    sess = session or load_attach_session(workspace)
    when = evaluated_at or _utc_now()
    store = SQLiteSituatedAssessmentStore(Path(sess.database))
    try:
        mandate, binding = store.resolve_active(
            sess.mandate_id,
            sess.environment_binding_id,
            principal_id=sess.principal_id,
            tenant_id=sess.tenant_id,
            workspace_id=sess.workspace_id,
            evaluated_at=when,
        )
    except SituationalTrustDenied as exc:
        raise MandateTerminalError(f"mandate status denied: {exc}") from exc
    context = _load_relevance_context(Path(workspace), mandate)
    open_commitments = []
    mission_statement = None
    desired_outcomes: list[str] = []
    permanent_constraints: list[str] = []
    if context is not None:
        mission_statement = context.mission_statement
        desired_outcomes = [item.statement for item in context.desired_outcomes]
        permanent_constraints = list(context.permanent_constraints)
        open_commitments = [
            {
                "commitment_id": item.commitment_id,
                "statement": item.statement,
                "due_at": item.due_at.isoformat() if item.due_at else None,
            }
            for item in context.open_commitments
        ]
    return {
        "entry": "mandate-status",
        "claim_ceiling": "MANDATE_TERMINAL_STATUS / NO_AUTONOMY / NO_HCW_CLAIM",
        "mandate_id": mandate.mandate_id,
        "mandate_version": mandate.version,
        "mandate_digest": mandate.mandate_digest,
        "status": mandate.status.value,
        "owner_principal_id": mandate.owner_principal_id,
        "tenant_id": mandate.tenant_id,
        "workspace_id": mandate.workspace_id,
        "valid_from": mandate.valid_from.isoformat(),
        "expires_at": mandate.expires_at.isoformat(),
        "correction_epoch": mandate.correction_epoch,
        "environment_binding": {
            "environment_binding_id": binding.environment_binding_id,
            "version": binding.version,
            "binding_digest": binding.binding_digest,
        },
        "mission_statement": mission_statement,
        "desired_outcomes": desired_outcomes,
        "permanent_constraints": permanent_constraints,
        "open_commitments": open_commitments,
        "attached_at": sess.attached_at,
        "evaluated_at": when.isoformat(),
    }


def emit_help_request(
    *,
    workspace: Path,
    help_request: HelpRequest,
    evaluated_at: datetime | None = None,
    session: MandateAttachSession | None = None,
) -> dict[str, Any]:
    """Admit a structured HelpRequest bound to the attached durable Mandate."""
    sess = session or load_attach_session(workspace)
    when = evaluated_at or _utc_now()
    store = SQLiteSituatedAssessmentStore(Path(sess.database))
    try:
        mandate, binding = store.resolve_active(
            sess.mandate_id,
            sess.environment_binding_id,
            principal_id=sess.principal_id,
            tenant_id=sess.tenant_id,
            workspace_id=sess.workspace_id,
            evaluated_at=when,
        )
    except SituationalTrustDenied as exc:
        raise MandateTerminalError(f"mandate help denied: {exc}") from exc

    if help_request.mandate_id != mandate.mandate_id:
        raise MandateTerminalError("help_request.mandate_id mismatch")
    if help_request.mandate_version != mandate.version:
        raise MandateTerminalError("help_request.mandate_version mismatch")
    if help_request.mandate_digest != mandate.mandate_digest:
        raise MandateTerminalError("help_request.mandate_digest mismatch")
    if help_request.environment_binding_id != binding.environment_binding_id:
        raise MandateTerminalError("help_request.environment_binding_id mismatch")
    if help_request.environment_binding_version != binding.version:
        raise MandateTerminalError("help_request.environment_binding_version mismatch")
    if help_request.environment_binding_digest != binding.binding_digest:
        raise MandateTerminalError("help_request.environment_binding_digest mismatch")
    if help_request.tenant_id != mandate.tenant_id:
        raise MandateTerminalError("help_request.tenant_id mismatch")
    if help_request.workspace_id != mandate.workspace_id:
        raise MandateTerminalError("help_request.workspace_id mismatch")
    if help_request.correction_epoch != mandate.correction_epoch:
        raise MandateTerminalError("help_request.correction_epoch mismatch")
    if help_request.authority_granted is not False:
        raise MandateTerminalError("help_request cannot grant authority")
    if help_request.external_effects_authorized is not False:
        raise MandateTerminalError("help_request cannot authorize external effects")

    inbox = help_inbox_path(Path(workspace))
    inbox.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "recorded_at": when.isoformat(),
        "entry": "mandate-help-request",
        "claim_ceiling": "MANDATE_TERMINAL_HELP / NO_AUTONOMY / NO_AUTHORITY_GRANT",
        "help_request": json.loads(canonical_json(help_request)),
    }
    with inbox.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {
        "emitted": True,
        "help_request_id": help_request.help_request_id,
        "inbox_path": str(inbox),
        "mandate_id": mandate.mandate_id,
        "mandate_digest": mandate.mandate_digest,
        "claim_ceiling": "MANDATE_TERMINAL_HELP / NO_AUTONOMY / NO_AUTHORITY_GRANT",
    }


def _write_relevance_context(
    workspace: Path,
    context: MandateRelevanceContext,
    mandate: RatifiedMandateRef,
) -> None:
    if context.mandate_id != mandate.mandate_id:
        raise MandateTerminalError("relevance_context.mandate_id mismatch")
    if context.mandate_version != mandate.version:
        raise MandateTerminalError("relevance_context.mandate_version mismatch")
    if context.mandate_digest != mandate.mandate_digest:
        raise MandateTerminalError("relevance_context.mandate_digest mismatch")
    if context.tenant_id != mandate.tenant_id:
        raise MandateTerminalError("relevance_context.tenant_id mismatch")
    if context.workspace_id != mandate.workspace_id:
        raise MandateTerminalError("relevance_context.workspace_id mismatch")
    path = context_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(context) + "\n", encoding="utf-8")


def _load_relevance_context(
    workspace: Path, mandate: RatifiedMandateRef
) -> MandateRelevanceContext | None:
    path = context_path(Path(workspace))
    if not path.is_file():
        return None
    context = MandateRelevanceContext.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    if (
        context.mandate_id != mandate.mandate_id
        or context.mandate_version != mandate.version
        or context.mandate_digest != mandate.mandate_digest
    ):
        raise MandateTerminalError(
            "stored relevance_context does not match durable mandate"
        )
    return context


def ensure_local_mandate_session(
    *,
    workspace: Path,
    database: Path,
    mission_statement: str | None = None,
    goal_statement: str | None = None,
    evaluated_at: datetime | None = None,
) -> tuple[MandateAttachSession, bool]:
    """Zero-config: reuse attach if valid, else bootstrap a local founder Mandate.

    Returns (session, created_new).
    """
    workspace = Path(workspace)
    database = Path(database).resolve()
    when = evaluated_at or _utc_now()
    attach = attach_path(workspace)
    if attach.is_file():
        try:
            session = load_attach_session(workspace)
        except MandateTerminalError:
            session = None
        else:
            if Path(session.database).resolve() != database:
                raise MandateTerminalError(
                    "attached Mandate database does not match requested --database; "
                    "use the original database or remove .agent_os/mandate_attach.json"
                )
            try:
                store = SQLiteSituatedAssessmentStore(Path(session.database))
                store.resolve_active(
                    session.mandate_id,
                    session.environment_binding_id,
                    principal_id=session.principal_id,
                    tenant_id=session.tenant_id,
                    workspace_id=session.workspace_id,
                    evaluated_at=when,
                )
                return session, False
            except (SituationalTrustDenied, OSError, ValueError):
                pass

    digest = "a" * 64
    binding_digest = "b" * 64
    policy_digest = "c" * 64
    mission = (mission_statement or "").strip() or (
        "Advance the repository under a local Agent OS Mandate with founder correction."
    )
    goal = (goal_statement or "").strip() or "Operate via Agent OS terminal on this repo."
    mandate = RatifiedMandateRef(
        mandate_id="mandate:local-terminal",
        version=1,
        mandate_digest=digest,
        ratification_receipt_id="ratification:local-terminal-auto",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        owner_principal_id="user:founder",
        ratified_by="user:founder",
        ratified_at=when - timedelta(hours=1),
        valid_from=when - timedelta(hours=1),
        expires_at=when + timedelta(days=30),
        correction_epoch=0,
        authority_envelope_digest="e" * 64,
        allowed_environment_bindings=(
            EnvironmentBindingAuthorization(
                environment_binding_id="binding:local-repo",
                version=1,
                binding_digest=binding_digest,
            ),
        ),
        relevance_assessor=RelevanceAssessorRef(
            assessor_id="assessor:local-terminal-v0",
            version=1,
            policy_digest=policy_digest,
        ),
    )
    context = MandateRelevanceContext(
        relevance_context_id="relevance:local-terminal",
        version=1,
        mandate_id=mandate.mandate_id,
        mandate_version=mandate.version,
        mandate_digest=mandate.mandate_digest,
        tenant_id=mandate.tenant_id,
        workspace_id=mandate.workspace_id,
        mission_statement=mission,
        desired_outcomes=(
            MandateOutcomeContext(outcome_id="outcome:local-terminal", statement=goal),
        ),
        open_commitments=(
            MandateCommitmentContext(
                commitment_id="commitment:local-goal",
                statement=goal,
            ),
        ),
        permanent_constraints=("C7 non-bypassable", "No self-approval"),
    )
    database.parent.mkdir(parents=True, exist_ok=True)
    bootstrap_mandate(
        database=database,
        mandate=mandate,
        relevance_context=context,
        workspace=workspace,
        evaluated_at=when,
    )
    session = attach_mandate(
        workspace=workspace,
        database=database,
        mandate_id=mandate.mandate_id,
        environment_binding_id="binding:local-repo",
        principal_id=mandate.owner_principal_id,
        tenant_id=mandate.tenant_id,
        workspace_id=mandate.workspace_id,
        evaluated_at=when,
    )
    return session, True


def load_mandate_json(path: Path) -> RatifiedMandateRef:
    return RatifiedMandateRef.model_validate_json(Path(path).read_text(encoding="utf-8"))


def load_relevance_context_json(path: Path) -> MandateRelevanceContext:
    return MandateRelevanceContext.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def load_help_request_json(path: Path) -> HelpRequest:
    return HelpRequest.model_validate_json(Path(path).read_text(encoding="utf-8"))
