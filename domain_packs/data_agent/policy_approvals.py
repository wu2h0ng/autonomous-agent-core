from __future__ import annotations

from dataclasses import dataclass, replace

_ACTIVE = "active"
_REVOKED = "revoked"
_CONSUMED = "consumed"


@dataclass(frozen=True)
class PolicyApprovalRecord:
    """A version-bound, tenant-scoped approval record for an R4/R5 auto-execution rule.

    A record is only usable while it is ``active`` AND its ``policy_version`` matches the policy
    currently in force; revoking or consuming it (single use) makes it unusable. Version binding is
    what stops a decision approved under one policy from authorizing execution under a later one.
    """

    record_id: str
    proposal_id: str
    rule_id: str
    policy_version: str
    tenant_id: str
    created_at: str
    status: str = _ACTIVE
    revoked_at: str | None = None
    consumed_at: str | None = None


class PolicyApprovalStore:
    """In-memory lifecycle store for :class:`PolicyApprovalRecord` (revoke / consume / version check).

    A durable adapter can implement the same surface; the lifecycle rules are the contract. All
    lookups are tenant-scoped: one tenant's record id can never resolve another tenant's record.
    """

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], PolicyApprovalRecord] = {}

    def save(self, record: PolicyApprovalRecord) -> PolicyApprovalRecord:
        self._records[(record.tenant_id, record.record_id)] = record
        return record

    def get(self, record_id: str, *, tenant_id: str) -> PolicyApprovalRecord | None:
        return self._records.get((tenant_id, record_id))

    def is_active(self, record_id: str, *, policy_version: str, tenant_id: str) -> bool:
        record = self.get(record_id, tenant_id=tenant_id)
        if record is None:
            return False
        return record.status == _ACTIVE and record.policy_version == policy_version

    def active_for_proposal(
        self, proposal_id: str, *, policy_version: str, tenant_id: str
    ) -> PolicyApprovalRecord | None:
        for (record_tenant, _), record in self._records.items():
            if record_tenant != tenant_id:
                continue
            if (
                record.proposal_id == proposal_id
                and record.status == _ACTIVE
                and record.policy_version == policy_version
            ):
                return record
        return None

    def revoke(self, record_id: str, *, revoked_at: str, tenant_id: str) -> PolicyApprovalRecord:
        record = self._require(record_id, tenant_id=tenant_id)
        updated = replace(record, status=_REVOKED, revoked_at=revoked_at)
        self.save(updated)
        return updated

    def consume(self, record_id: str, *, consumed_at: str, tenant_id: str) -> PolicyApprovalRecord:
        record = self._require(record_id, tenant_id=tenant_id)
        updated = replace(record, status=_CONSUMED, consumed_at=consumed_at)
        self.save(updated)
        return updated

    def _require(self, record_id: str, *, tenant_id: str) -> PolicyApprovalRecord:
        record = self.get(record_id, tenant_id=tenant_id)
        if record is None:
            raise KeyError(f"unknown policy approval record: {record_id}")
        return record
