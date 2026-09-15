"""SPINE-1: Data Agent policy-approval record lifecycle (R4/R5 auto-execution).

A version-bound, tenant-scoped approval record is usable only while active AND its policy_version
matches the policy in force; revoke and consume make it unusable, and consume is single-use. This is
the domain-native re-implementation of the donor ``PolicyApprovalRecord`` lifecycle. Each test would
FAIL if the store ignored status/version or the tenant scope.
"""

from __future__ import annotations

import pytest

from domain_packs.data_agent.policy_approvals import PolicyApprovalRecord, PolicyApprovalStore

_TENANT = "tenant:acme"
_OTHER_TENANT = "tenant:other"
_VERSION = "policy:v1"


def _record(**overrides: object) -> PolicyApprovalRecord:
    payload: dict[str, object] = {
        "record_id": "par-1",
        "proposal_id": "proposal-1",
        "rule_id": "rule-1",
        "policy_version": _VERSION,
        "tenant_id": _TENANT,
        "created_at": "2026-09-15T00:00:00+00:00",
    }
    payload.update(overrides)
    return PolicyApprovalRecord(**payload)  # type: ignore[arg-type]


def _store() -> PolicyApprovalStore:
    store = PolicyApprovalStore()
    store.save(_record())
    return store


def test_save_and_get_roundtrip() -> None:
    store = _store()
    got = store.get("par-1", tenant_id=_TENANT)

    assert got is not None
    assert got.proposal_id == "proposal-1"
    assert got.status == "active"


def test_is_active_checks_status_and_version() -> None:
    store = _store()

    assert store.is_active("par-1", policy_version=_VERSION, tenant_id=_TENANT) is True
    assert store.is_active("par-1", policy_version="policy:v2", tenant_id=_TENANT) is False
    assert store.is_active("missing", policy_version=_VERSION, tenant_id=_TENANT) is False


def test_is_active_is_tenant_scoped() -> None:
    store = _store()

    assert store.is_active("par-1", policy_version=_VERSION, tenant_id=_OTHER_TENANT) is False


def test_revoke_updates_status_and_timestamp() -> None:
    store = _store()

    updated = store.revoke("par-1", revoked_at="2026-09-15T01:00:00+00:00", tenant_id=_TENANT)

    assert updated.status == "revoked"
    assert updated.revoked_at == "2026-09-15T01:00:00+00:00"
    assert store.is_active("par-1", policy_version=_VERSION, tenant_id=_TENANT) is False


def test_consume_is_single_use() -> None:
    store = _store()

    store.consume("par-1", consumed_at="2026-09-15T02:00:00+00:00", tenant_id=_TENANT)

    assert store.get("par-1", tenant_id=_TENANT).status == "consumed"  # type: ignore[union-attr]
    assert store.is_active("par-1", policy_version=_VERSION, tenant_id=_TENANT) is False


def test_revoke_and_consume_missing_raise() -> None:
    store = _store()

    with pytest.raises(KeyError):
        store.revoke("missing", revoked_at="t", tenant_id=_TENANT)
    with pytest.raises(KeyError):
        store.consume("missing", consumed_at="t", tenant_id=_TENANT)


def test_active_for_proposal_matches_version_and_status() -> None:
    store = _store()
    store.save(_record(record_id="par-2", proposal_id="proposal-2", policy_version="policy:v2"))

    active = store.active_for_proposal("proposal-1", policy_version=_VERSION, tenant_id=_TENANT)
    wrong_version = store.active_for_proposal(
        "proposal-1", policy_version="policy:v2", tenant_id=_TENANT
    )
    other_tenant = store.active_for_proposal(
        "proposal-1", policy_version=_VERSION, tenant_id=_OTHER_TENANT
    )

    assert active is not None and active.record_id == "par-1"
    assert wrong_version is None
    assert other_tenant is None


def test_consumed_record_is_no_longer_active_for_proposal() -> None:
    store = _store()
    store.consume("par-1", consumed_at="2026-09-15T02:00:00+00:00", tenant_id=_TENANT)

    assert (
        store.active_for_proposal("proposal-1", policy_version=_VERSION, tenant_id=_TENANT)
        is None
    )
