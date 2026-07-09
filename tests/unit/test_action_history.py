"""P2-B (ADR-0016): the ActionRecordHistoryAdapter over the durable action_records ledger.

The adapter is the connector-side reader that maps the action_record connector's OWN durable
records to a generic outcome vocabulary the domain-independent OS Core derivation counts:
a clean record resolved to the intended execution outcome; a record whose write ACK was lost
(``uncertain_execution_count > 0``) executed but did NOT cleanly resolve. OS Core never sees
this record shape — it only sees the port and the generic outcome strings.

Includes spec test 3 (tenant isolation) against the tenant-scoped SQL repository: one tenant's
history must never leak into another tenant's preview.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _pkg in ("contracts", "os_core", "persistence", "sdk"):
    sys.path.insert(0, str(ROOT / "packages" / _pkg / "src"))
sys.path.insert(0, str(ROOT / "action_connectors"))

from action_record import ActionRecordStore  # noqa: E402

try:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    _HAVE_SQLALCHEMY = True
except ImportError:  # pragma: no cover - SQLAlchemy is a CI dependency
    _HAVE_SQLALCHEMY = False


def _seed(
    store, *, action_type: str, clean: int, uncertain: int, tenant_id: str = "default"
) -> None:
    kw = {} if isinstance(store, ActionRecordStore) else {"tenant_id": tenant_id}
    for i in range(clean):
        store.add(
            operation_id=f"c-{tenant_id}-{i}", action_type=action_type, parameters={"i": i}, **kw
        )
    for i in range(uncertain):
        record = store.add(
            operation_id=f"u-{tenant_id}-{i}", action_type=action_type, parameters={"i": i}, **kw
        )
        store.mark_execution_uncertain(
            record_id=record["record_id"],
            operation_id=f"u-{tenant_id}-{i}",
            action_type=action_type,
            idempotency_key=None,
            parameters={"i": i},
            reason_code="ack_lost_after_write",
            error_type="TimeoutError",
            **kw,
        )


class ActionRecordHistoryAdapterTest(unittest.TestCase):
    def test_adapter_maps_records_to_intended_and_other_outcomes(self):
        """A clean record maps to the intended outcome; an ACK-uncertain one does not; a record of
        a different action_type is excluded. FAILS if the adapter miscounts or ignores action_type."""
        from action_record.action_history import ActionRecordHistoryAdapter
        from agent_os_core.consequence_preview import INTENDED_EXECUTION_OUTCOME

        store = ActionRecordStore()
        _seed(store, action_type="execute", clean=2, uncertain=1)
        _seed(store, action_type="other_action", clean=3, uncertain=0)  # must be excluded

        adapter = ActionRecordHistoryAdapter(store)
        outcomes = adapter.outcomes_for(action_type="execute")

        self.assertEqual(len(outcomes), 3)  # only the "execute" records
        self.assertEqual(outcomes.count(INTENDED_EXECUTION_OUTCOME), 2)
        self.assertEqual(sum(1 for o in outcomes if o != INTENDED_EXECUTION_OUTCOME), 1)
        # oldest -> newest so the derivation's "most recent K" is a real recency slice.
        self.assertEqual(outcomes[:2], (INTENDED_EXECUTION_OUTCOME, INTENDED_EXECUTION_OUTCOME))

    @unittest.skipUnless(
        _HAVE_SQLALCHEMY, "SQLAlchemy required for the durable tenant-scoped ledger"
    )
    def test_preview_tenant_isolated(self):
        """Tenant B's action history NEVER counts toward tenant A's preview (test 3).

        Verified against the tenant-scoped ``SqlActionRecordStore`` — the durable ledger that
        production reads. FAILS if the tenant filter is dropped and B's records leak into A.
        """
        from action_record.action_history import ActionRecordHistoryAdapter
        from agent_os_core.consequence_preview import build_consequence_preview
        from agent_os_persistence import SqlActionRecordStore, create_all

        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        create_all(engine)
        store = SqlActionRecordStore(engine)
        # Only tenant B has "execute" history.
        _seed(store, action_type="execute", clean=2, uncertain=1, tenant_id="tenant-b")

        adapter = ActionRecordHistoryAdapter(store)
        preview_a = build_consequence_preview(
            action_type="execute", history_port=adapter, tenant_id="tenant-a"
        )
        preview_b = build_consequence_preview(
            action_type="execute", history_port=adapter, tenant_id="tenant-b"
        )

        # Tenant A sees NONE of tenant B's history.
        self.assertFalse(preview_a.available)
        self.assertEqual(preview_a.prior_executions, 0)
        self.assertEqual(preview_a.resolved_intended, 0)
        self.assertEqual(preview_a.last_outcomes, ())
        # Tenant B sees exactly its own.
        self.assertTrue(preview_b.available)
        self.assertEqual(preview_b.prior_executions, 3)
        self.assertEqual(preview_b.resolved_intended, 2)
        self.assertEqual(preview_b.resolved_other, 1)


if __name__ == "__main__":
    unittest.main()
