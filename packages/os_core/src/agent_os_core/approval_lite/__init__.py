from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from agent_os_contracts import (
    ActionAlternative,
    ApprovalAnalytics,
    ApprovalDecision,
    ApprovalDecisionCounts,
    BlockCode,
    EvidenceChain,
    OperationContract,
)

# P2-A (ADR-0015): coarse operator intents accepted by the decision path. The
# fine-grained ``ApprovalDecision`` (recommended vs revised) is DERIVED from the
# selected action, never taken from the operator's word — that is what makes the
# rubber-stamp signal a measurement rather than a self-report.
DECISION_OUTCOME_APPROVE = "approve"
DECISION_OUTCOME_REJECT = "reject"
DECISION_OUTCOME_ESCALATE = "escalate"
_DECISION_OUTCOMES = frozenset(
    {DECISION_OUTCOME_APPROVE, DECISION_OUTCOME_REJECT, DECISION_OUTCOME_ESCALATE}
)


class ChoiceSetViolationError(Exception):
    """A ``revise`` named an action outside the proposal's surfaced choice set (P2-A).

    Carries :attr:`block_code` = ``BlockCode.CHOICE_SET_VIOLATION`` so the runtime
    can translate it into a typed ``TrustedLoopBlock`` without approval_lite importing
    the runtime (which would be a circular import). A revise must pick a real, surfaced
    alternative — otherwise the choice-set audit trail would be a fiction.
    """

    block_code = BlockCode.CHOICE_SET_VIOLATION

    def __init__(self, message: str, *, details: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.details = details


@dataclass(frozen=True)
class ApprovalRecord:
    """Immutable record of an approval decision."""

    approval_id: str
    proposal_id: str
    status: str  # "pending" | "approved" | "rejected"
    approver_role: str | None
    reason: str | None = None
    operation_fingerprint: str | None = None
    approved_by: str | None = None
    # ADR-0014: durable snapshot of the human-facing choice set, captured at proposal time.
    # Unlike the approval-resume context (deleted after execution), this record persists, so a
    # post-execution audit can still show WHAT the approver was choosing between and why only one
    # option was surfaced. Preserved across approve/reject status transitions.
    alternatives: tuple[ActionAlternative, ...] = field(default_factory=tuple)
    single_option_rationale: str | None = None
    # P2-A (ADR-0015): the rubber-stamp-analytics fields. ``recommended_action`` and
    # ``risk_level`` are snapshotted at proposal time so the decision path and the
    # analytics projection are self-contained (the ActionProposal is gone by then).
    # ``decision``/``selected_action`` are populated by ``ApprovalLiteRuntime.decide``:
    # ``decision`` is the DERIVED ApprovalDecision value, ``selected_action`` is the
    # action the approver actually approved. ``created_at`` is an ISO-8601 UTC stamp
    # used for windowed analytics. All default to None so pre-P2-A records deserialize.
    recommended_action: str | None = None
    risk_level: str | None = None
    decision: str | None = None
    selected_action: str | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class ApprovalOperationContext:
    """Frozen operation context needed to resume an approved action by approval id."""

    approval_id: str
    proposal_id: str
    operation: OperationContract
    action_parameters: dict[str, Any]
    evidence_chain: EvidenceChain
    # ADR-0014: the proposal's human-facing choice set, snapshotted at proposal time so
    # the approval detail surface renders what the approver is choosing between.
    alternatives: tuple[ActionAlternative, ...] = field(default_factory=tuple)
    single_option_rationale: str | None = None


class ApprovalStorePort(ABC):
    """Persistence port for approval records (storage only; lifecycle lives in the runtime).

    OS Core depends on this abstraction; concrete backends (in-memory below, or a
    PostgreSQL adapter outside OS Core) implement it. Persisting approvals is what
    lets an approval created in one process be acted on later in another.
    """

    @abstractmethod
    def save(self, record: ApprovalRecord, *, tenant_id: str = "default") -> ApprovalRecord:
        """Persist (insert or replace by ``approval_id``) and return the record."""
        ...

    @abstractmethod
    def get(self, approval_id: str, *, tenant_id: str = "default") -> ApprovalRecord | None:
        """Return the record for ``approval_id``, or ``None`` if absent."""
        ...

    @abstractmethod
    def list(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        tenant_id: str = "default",
    ) -> tuple[ApprovalRecord, ...]:
        """Return a paginated list of approval records, optionally filtered by status."""
        ...


class ApprovalContextStorePort(ABC):
    """Persistence port for approval-bound operation contexts.

    The approval record stores the decision lifecycle; this context stores the
    exact operation/evidence/action payload captured at proposal time, so a
    later process can execute by approval_id without client replay.
    """

    @abstractmethod
    def save(
        self, context: ApprovalOperationContext, *, tenant_id: str = "default"
    ) -> ApprovalOperationContext:
        """Persist or replace a context by ``approval_id`` and return it."""
        ...

    @abstractmethod
    def get(
        self, approval_id: str, *, tenant_id: str = "default"
    ) -> ApprovalOperationContext | None:
        """Return the context for ``approval_id``, or ``None`` if absent."""
        ...

    @abstractmethod
    def claim(
        self,
        approval_id: str,
        *,
        reclaim_stale_after_seconds: float | None = None,
        tenant_id: str = "default",
    ) -> ApprovalOperationContext | None:
        """Atomically mark a pending context as executing and return it.

        When ``reclaim_stale_after_seconds`` is provided, durable stores may
        reclaim an already-executing context only if its claim lease is older
        than that age. This is crash recovery for abandoned claims, not a
        distributed exactly-once guarantee.
        """
        ...

    @abstractmethod
    def release_claim(self, approval_id: str, *, tenant_id: str = "default") -> None:
        """Return an executing context to pending so the approval can be retried."""
        ...

    @abstractmethod
    def delete(self, approval_id: str, *, tenant_id: str = "default") -> None:
        """Remove the context for ``approval_id`` if present."""
        ...


class InMemoryApprovalStore(ApprovalStorePort):
    """In-memory :class:`ApprovalStorePort` backed by a dict keyed on approval_id."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, ApprovalRecord]] = {}

    def _tenant_records(self, tenant_id: str) -> dict[str, ApprovalRecord]:
        return self._records.setdefault(tenant_id, {})

    def save(self, record: ApprovalRecord, *, tenant_id: str = "default") -> ApprovalRecord:
        self._tenant_records(tenant_id)[record.approval_id] = record
        return record

    def get(self, approval_id: str, *, tenant_id: str = "default") -> ApprovalRecord | None:
        return self._tenant_records(tenant_id).get(approval_id)

    def list(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        tenant_id: str = "default",
    ) -> tuple[ApprovalRecord, ...]:
        records = list(self._tenant_records(tenant_id).values())
        if status is not None:
            records = [r for r in records if r.status == status]
        records = sorted(records, key=lambda r: r.approval_id)
        return tuple(records[offset : offset + limit])


class InMemoryApprovalContextStore(ApprovalContextStorePort):
    """In-memory approval-context store keyed by approval_id."""

    def __init__(self) -> None:
        self._contexts: dict[str, dict[str, ApprovalOperationContext]] = {}
        self._statuses: dict[str, dict[str, str]] = {}
        self._claimed_at: dict[str, dict[str, datetime]] = {}

    def _tenant_maps(
        self, tenant_id: str
    ) -> tuple[
        dict[str, ApprovalOperationContext],
        dict[str, str],
        dict[str, datetime],
    ]:
        return (
            self._contexts.setdefault(tenant_id, {}),
            self._statuses.setdefault(tenant_id, {}),
            self._claimed_at.setdefault(tenant_id, {}),
        )

    def save(
        self, context: ApprovalOperationContext, *, tenant_id: str = "default"
    ) -> ApprovalOperationContext:
        contexts, statuses, _ = self._tenant_maps(tenant_id)
        contexts[context.approval_id] = context
        statuses[context.approval_id] = "pending"
        return context

    def get(
        self, approval_id: str, *, tenant_id: str = "default"
    ) -> ApprovalOperationContext | None:
        contexts, _, _ = self._tenant_maps(tenant_id)
        return contexts.get(approval_id)

    def claim(
        self,
        approval_id: str,
        *,
        reclaim_stale_after_seconds: float | None = None,
        tenant_id: str = "default",
    ) -> ApprovalOperationContext | None:
        contexts, statuses, claimed_at = self._tenant_maps(tenant_id)
        status = statuses.get(approval_id)
        if status == "executing" and reclaim_stale_after_seconds is not None:
            claimed_at_dt = claimed_at.get(approval_id)
            if claimed_at_dt is None:
                return None
            elapsed = (datetime.now(timezone.utc) - claimed_at_dt).total_seconds()
            if elapsed < reclaim_stale_after_seconds:
                return None
        elif status != "pending":
            return None
        context = contexts.get(approval_id)
        if context is None:
            return None
        statuses[approval_id] = "executing"
        claimed_at[approval_id] = datetime.now(timezone.utc)
        return context

    def release_claim(self, approval_id: str, *, tenant_id: str = "default") -> None:
        _, statuses, claimed_at = self._tenant_maps(tenant_id)
        if statuses.get(approval_id) == "executing":
            statuses[approval_id] = "pending"
            claimed_at.pop(approval_id, None)

    def delete(self, approval_id: str, *, tenant_id: str = "default") -> None:
        contexts, statuses, claimed_at = self._tenant_maps(tenant_id)
        contexts.pop(approval_id, None)
        statuses.pop(approval_id, None)
        claimed_at.pop(approval_id, None)


class ApprovalLiteRuntime:
    """Lightweight approval lifecycle manager over an injected store.

    Owns the lifecycle (pending -> approved/rejected); storage is delegated to an
    :class:`ApprovalStorePort` (in-memory by default, or a durable adapter). Because
    ``ApprovalRecord`` is frozen, approve/reject create a new record to replace the old.
    """

    def __init__(self, store: ApprovalStorePort | None = None) -> None:
        self._store: ApprovalStorePort = store or InMemoryApprovalStore()

    def create_pending(
        self,
        *,
        approval_id: str,
        proposal_id: str,
        approver_role: str | None,
        operation_fingerprint: str | None = None,
        alternatives: tuple[ActionAlternative, ...] = (),
        single_option_rationale: str | None = None,
        recommended_action: str | None = None,
        risk_level: str | None = None,
        created_at: str | None = None,
        tenant_id: str = "default",
    ) -> ApprovalRecord:
        """Create a new pending approval record.

        Args:
            approval_id: Unique identifier for this approval.
            proposal_id: The proposal this approval relates to.
            approver_role: The role required to approve (may be None).
            operation_fingerprint: Optional frozen digest of the approved operation
                contract and action parameters.
            alternatives: ADR-0014 human-facing choice set, snapshotted durably.
            single_option_rationale: ADR-0014 truthful reason only one option was
                surfaced, snapshotted durably.
            recommended_action: P2-A snapshot of the proposal's recommended action,
                so the decision path can classify recommended-vs-revise offline.
            risk_level: P2-A snapshot of the proposal's risk tier, so analytics can
                be sliced by risk without re-reading the (gone) proposal.
            created_at: Optional ISO-8601 UTC timestamp; defaults to now. Injectable
                so windowed-analytics behavior is deterministically testable.
            tenant_id: Tenant scope for the record.

        Returns:
            The newly created ApprovalRecord with status "pending".
        """
        record = ApprovalRecord(
            approval_id=approval_id,
            proposal_id=proposal_id,
            status="pending",
            approver_role=approver_role,
            operation_fingerprint=operation_fingerprint,
            alternatives=tuple(alternatives),
            single_option_rationale=single_option_rationale,
            recommended_action=recommended_action,
            risk_level=risk_level,
            created_at=created_at or datetime.now(timezone.utc).isoformat(),
        )
        return self._store.save(record, tenant_id=tenant_id)

    def approve(
        self,
        approval_id: str,
        reason: str | None = None,
        approved_by: str | None = None,
        *,
        tenant_id: str = "default",
    ) -> ApprovalRecord:
        """Approve a pending approval record.

        Args:
            approval_id: The ID of the approval to approve.
            reason: Optional reason for the approval.
            approved_by: Optional operator/user identifier for audit.
            tenant_id: Tenant scope for the record.

        Returns:
            A new ApprovalRecord with status "approved".

        Raises:
            KeyError: If no record with the given ID exists.
            ValueError: If the record is not in "pending" status.
        """
        existing = self._store.get(approval_id, tenant_id=tenant_id)
        if existing is None:
            raise KeyError(f"No approval record found with id '{approval_id}'")
        if existing.status != "pending":
            raise ValueError(
                f"Cannot approve record '{approval_id}': "
                f"current status is '{existing.status}', expected 'pending'"
            )
        # ``replace`` preserves every snapshot field (alternatives, rationale, the
        # P2-A recommended_action/risk_level/created_at) without re-listing them.
        # decision/selected_action are left untouched: the legacy approve path does
        # not classify recommended-vs-revise — that is ``decide``'s responsibility.
        updated = replace(
            existing,
            status="approved",
            reason=reason,
            approved_by=approved_by,
        )
        return self._store.save(updated, tenant_id=tenant_id)

    def reject(
        self,
        approval_id: str,
        reason: str | None = None,
        *,
        tenant_id: str = "default",
    ) -> ApprovalRecord:
        """Reject a pending approval record.

        Args:
            approval_id: The ID of the approval to reject.
            reason: Optional reason for the rejection.
            tenant_id: Tenant scope for the record.

        Returns:
            A new ApprovalRecord with status "rejected".

        Raises:
            KeyError: If no record with the given ID exists.
            ValueError: If the record is not in "pending" status.
        """
        existing = self._store.get(approval_id, tenant_id=tenant_id)
        if existing is None:
            raise KeyError(f"No approval record found with id '{approval_id}'")
        if existing.status != "pending":
            raise ValueError(
                f"Cannot reject record '{approval_id}': "
                f"current status is '{existing.status}', expected 'pending'"
            )
        updated = replace(existing, status="rejected", reason=reason)
        return self._store.save(updated, tenant_id=tenant_id)

    def get(self, approval_id: str, *, tenant_id: str = "default") -> ApprovalRecord:
        """Retrieve an approval record by ID.

        Args:
            approval_id: The unique ID of the approval.
            tenant_id: Tenant scope for the record.

        Returns:
            The ApprovalRecord.

        Raises:
            KeyError: If no record with the given ID exists.
        """
        record = self._store.get(approval_id, tenant_id=tenant_id)
        if record is None:
            raise KeyError(f"No approval record found with id '{approval_id}'")
        return record

    def list(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
        tenant_id: str = "default",
    ) -> tuple[ApprovalRecord, ...]:
        """List approval records from the store.

        Args:
            status: Optional status filter ("pending", "approved", "rejected").
            limit: Maximum number of records to return.
            offset: Number of records to skip.
            tenant_id: Tenant scope for the records.

        Returns:
            A tuple of matching ApprovalRecord instances.
        """
        return self._store.list(status=status, limit=limit, offset=offset, tenant_id=tenant_id)

    def decide(
        self,
        approval_id: str,
        *,
        outcome: str,
        selected_action: str | None = None,
        reason: str | None = None,
        approved_by: str | None = None,
        tenant_id: str = "default",
    ) -> ApprovalRecord:
        """Record a human approval decision and DERIVE its rubber-stamp classification.

        ``outcome`` is the coarse operator intent (``approve`` | ``reject`` |
        ``escalate``). For an ``approve``, the fine-grained
        :class:`~agent_os_contracts.ApprovalDecision` is derived from ``selected_action``
        versus the snapshotted ``recommended_action`` — never from the operator's own
        label. Selecting the recommended action (or omitting ``selected_action``) yields
        ``approved_recommended``; selecting a different, in-choice-set alternative yields
        ``approved_revised`` (a ``revise``).

        Args:
            approval_id: The approval to decide.
            outcome: ``approve`` | ``reject`` | ``escalate``.
            selected_action: The action the approver actually chose (approve path).
            reason: Optional human rationale for the decision.
            approved_by: Optional operator identifier (approve path only).
            tenant_id: Tenant scope for the record.

        Returns:
            The updated :class:`ApprovalRecord` carrying ``decision``/``selected_action``.

        Raises:
            ValueError: Unknown ``outcome``, or the approval is not pending (a consumed
                or already-decided approval cannot be re-decided).
            KeyError: No record with ``approval_id`` exists.
            ChoiceSetViolationError: A revise named an action outside the choice set.
        """
        if outcome not in _DECISION_OUTCOMES:
            raise ValueError(
                f"Unknown approval outcome '{outcome}'; expected one of "
                f"{sorted(_DECISION_OUTCOMES)}."
            )
        existing = self._store.get(approval_id, tenant_id=tenant_id)
        if existing is None:
            raise KeyError(f"No approval record found with id '{approval_id}'")
        if existing.status != "pending":
            raise ValueError(
                f"Cannot record a decision on approval '{approval_id}': current status "
                f"is '{existing.status}', expected 'pending'. A consumed or "
                "already-decided approval cannot be re-decided."
            )

        if outcome == DECISION_OUTCOME_REJECT:
            updated = replace(
                existing,
                status="rejected",
                reason=reason,
                decision=ApprovalDecision.REJECTED.value,
                selected_action=None,
            )
        elif outcome == DECISION_OUTCOME_ESCALATE:
            # Escalation punts to a higher approver: the approval stays pending and may
            # be decided again later. Analytics counts the record's CURRENT decision, so
            # a subsequent real decision overwrites this one (never double-counted).
            updated = replace(
                existing,
                reason=reason,
                decision=ApprovalDecision.ESCALATED.value,
                selected_action=None,
            )
        else:  # DECISION_OUTCOME_APPROVE
            recommended = existing.recommended_action
            chosen = selected_action if selected_action is not None else recommended
            if chosen == recommended:
                decision = ApprovalDecision.APPROVED_RECOMMENDED
            else:
                choice_set = {alternative.action for alternative in existing.alternatives}
                if chosen not in choice_set:
                    raise ChoiceSetViolationError(
                        f"revise selected action '{chosen}' is not in the proposal's "
                        "surfaced choice set (ADR-0014); a revise must pick a real "
                        "alternative.",
                        details=(
                            f"selected_action={chosen!r}",
                            f"recommended_action={recommended!r}",
                            "choice_set=" + ",".join(sorted(choice_set)),
                        ),
                    )
                decision = ApprovalDecision.APPROVED_REVISED
            updated = replace(
                existing,
                status="approved",
                reason=reason,
                approved_by=approved_by,
                decision=decision.value,
                selected_action=chosen,
            )
        return self._store.save(updated, tenant_id=tenant_id)

    def analytics(
        self,
        *,
        tenant_id: str = "default",
        risk: str | None = None,
        window: str = "all",
    ) -> ApprovalAnalytics:
        """Derive rubber-stamp analytics by scanning this tenant's decided approvals.

        This is a pure projection over ``ApprovalRecord``s — there is no parallel
        counter store to drift. Only records that carry a ``decision`` are counted;
        ``risk`` and ``window`` narrow the scope (``window='all'`` = no time bound).
        """
        window_start = _parse_window_start(window)
        counts = {decision: 0 for decision in ApprovalDecision}
        for record in self._iter_records(tenant_id=tenant_id):
            if record.decision is None:
                continue
            if risk is not None and record.risk_level != risk:
                continue
            if window_start is not None and not _created_within(record.created_at, window_start):
                continue
            try:
                decision = ApprovalDecision(record.decision)
            except ValueError:
                # An unknown/legacy decision value must never crash analytics.
                continue
            counts[decision] += 1

        approved_recommended = counts[ApprovalDecision.APPROVED_RECOMMENDED]
        approved_revised = counts[ApprovalDecision.APPROVED_REVISED]
        approvals = approved_recommended + approved_revised
        modify_rate = approved_revised / approvals if approvals else 0.0
        selection_concentration = approved_recommended / approvals if approvals else 0.0
        return ApprovalAnalytics(
            tenant_id=tenant_id,
            window=window,
            risk=risk,
            counts=ApprovalDecisionCounts(
                approved_recommended=approved_recommended,
                approved_revised=approved_revised,
                rejected=counts[ApprovalDecision.REJECTED],
                escalated=counts[ApprovalDecision.ESCALATED],
            ),
            total=sum(counts.values()),
            modify_rate=modify_rate,
            selection_concentration=selection_concentration,
        )

    def _iter_records(self, *, tenant_id: str):
        """Yield every approval record for a tenant, store-agnostically (paginated)."""
        page = 500
        offset = 0
        while True:
            batch = self._store.list(limit=page, offset=offset, tenant_id=tenant_id)
            if not batch:
                return
            yield from batch
            if len(batch) < page:
                return
            offset += page


_WINDOW_UNIT_SECONDS = {"h": 3600, "d": 86400, "w": 604800}


def _parse_window_start(window: str) -> datetime | None:
    """Return the earliest ``created_at`` included by ``window``, or None for 'all'.

    Supported: ``all`` (no bound) and ``<N>h`` / ``<N>d`` / ``<N>w``. An unsupported
    window is a caller error (raised), not a silent no-op.
    """
    if not window:
        return None
    text = window.strip().lower()
    if text == "all":
        return None
    unit = text[-1:]
    amount = text[:-1]
    if unit in _WINDOW_UNIT_SECONDS and amount.isdigit():
        seconds = int(amount) * _WINDOW_UNIT_SECONDS[unit]
        return datetime.now(timezone.utc) - timedelta(seconds=seconds)
    raise ValueError(f"Unsupported analytics window '{window}'; use 'all' or '<N>h'/'<N>d'/'<N>w'.")


def _created_within(created_at: str | None, window_start: datetime) -> bool:
    """True when ``created_at`` (ISO-8601) is at or after ``window_start``."""
    if not created_at:
        return False
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created >= window_start
