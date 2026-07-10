"""Durable PolicyApprovalRecord SQL store (workstream E enablement / AR-20260707).

Same code runs on SQLite (tests) and PostgreSQL (production). Verifies the
durable store round-trips records, supports revoke/consume lifecycle, and
survives a "restart" (new store instance over the same engine).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for seg in ("packages/contracts/src", "packages/os_core/src", "packages/persistence/src"):
    sys.path.insert(0, str(ROOT / seg))

from agent_os_contracts import PolicyApprovalRecord  # noqa: E402
from agent_os_core.policy_engine import PolicyApprovalRecordStorePort  # noqa: E402


def _record(
    record_id="par-1",
    proposal_id="proposal-1",
    status="active",
    revoked_at=None,
    policy_version="v1",
    tenant_id="tenant-1",
) -> PolicyApprovalRecord:
    return PolicyApprovalRecord(
        record_id=record_id,
        trace_id="trace-1",
        proposal_id=proposal_id,
        rule_id="rule-1",
        policy_version=policy_version,
        tenant_id=tenant_id,
        created_at="2026-07-07T00:00:00+00:00",
        revoked_at=revoked_at,
        status=status,
    )


class SqlPolicyApprovalRecordStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool
        from agent_os_persistence import create_all, SqlPolicyApprovalRecordStore

        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        create_all(self.engine)
        self.store = SqlPolicyApprovalRecordStore(self.engine)

    def test_is_a_port_implementation(self) -> None:
        self.assertIsInstance(self.store, PolicyApprovalRecordStorePort)

    def test_save_and_get_roundtrip(self) -> None:
        rec = _record()
        self.store.save(rec)
        got = self.store.get("par-1", tenant_id="tenant-1")
        self.assertIsNotNone(got)
        self.assertEqual(got.proposal_id, "proposal-1")
        self.assertEqual(got.status, "active")

    def test_is_active_checks_status_and_version(self) -> None:
        self.store.save(_record())
        self.assertTrue(self.store.is_active("par-1", tenant_id="tenant-1", policy_version="v1"))
        self.assertFalse(self.store.is_active("par-1", tenant_id="tenant-1", policy_version="v2"))
        self.assertFalse(self.store.is_active("missing", tenant_id="tenant-1", policy_version="v1"))

    def test_revoke_updates_status(self) -> None:
        self.store.save(_record())
        self.store.revoke("par-1", revoked_at="2026-07-07T01:00:00+00:00", tenant_id="tenant-1")
        self.assertFalse(self.store.is_active("par-1", tenant_id="tenant-1", policy_version="v1"))
        got = self.store.get("par-1", tenant_id="tenant-1")
        self.assertEqual(got.status, "revoked")
        self.assertEqual(got.revoked_at, "2026-07-07T01:00:00+00:00")

    def test_consume_updates_status(self) -> None:
        self.store.save(_record())
        self.store.consume("par-1", tenant_id="tenant-1")
        self.assertFalse(self.store.is_active("par-1", tenant_id="tenant-1", policy_version="v1"))
        self.assertEqual(self.store.get("par-1", tenant_id="tenant-1").status, "consumed")

    def test_revoke_missing_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.store.revoke("nope", revoked_at="t", tenant_id="tenant-1")

    def test_consume_missing_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.store.consume("nope", tenant_id="tenant-1")

    def test_active_for_proposal(self) -> None:
        self.store.save(_record(proposal_id="p-a"))
        found = self.store.active_for_proposal("p-a", tenant_id="tenant-1", policy_version="v1")
        self.assertIsNotNone(found)
        self.assertEqual(found.record_id, "par-1")
        # consumed record is not active
        self.store.consume("par-1", tenant_id="tenant-1")
        self.assertIsNone(
            self.store.active_for_proposal("p-a", tenant_id="tenant-1", policy_version="v1")
        )

    def test_record_id_scoped_by_tenant(self) -> None:
        # Composite PK (tenant_id, record_id) allows the same record_id in two tenants;
        # get/consume/revoke/is_active must never leak across tenants.
        self.store.save(_record(record_id="par-1", tenant_id="tenant-a", proposal_id="p-a"))
        self.store.save(_record(record_id="par-1", tenant_id="tenant-b", proposal_id="p-b"))

        self.assertEqual(self.store.get("par-1", tenant_id="tenant-a").proposal_id, "p-a")
        self.assertEqual(self.store.get("par-1", tenant_id="tenant-b").proposal_id, "p-b")

        self.store.consume("par-1", tenant_id="tenant-b")
        self.assertEqual(self.store.get("par-1", tenant_id="tenant-a").status, "active")
        self.assertEqual(self.store.get("par-1", tenant_id="tenant-b").status, "consumed")
        self.assertTrue(
            self.store.is_active("par-1", tenant_id="tenant-a", policy_version="v1")
        )
        self.assertFalse(
            self.store.is_active("par-1", tenant_id="tenant-b", policy_version="v1")
        )

    def test_survives_restart(self) -> None:
        from agent_os_persistence import SqlPolicyApprovalRecordStore

        self.store.save(_record())
        # simulate restart: new store instance over same engine
        new_store = SqlPolicyApprovalRecordStore(self.engine)
        self.assertTrue(new_store.is_active("par-1", tenant_id="tenant-1", policy_version="v1"))

    def test_policy_engine_accepts_durable_store(self) -> None:
        from agent_os_core.policy_engine import PolicyEngine
        from agent_os_contracts import RuntimeFeatureFlags

        engine = PolicyEngine(
            RuntimeFeatureFlags(r4_r5_auto_execution=True),
            record_store=self.store,
        )
        # the durable store is wired into the engine
        self.assertIs(engine.record_store, self.store)


if __name__ == "__main__":
    unittest.main()
