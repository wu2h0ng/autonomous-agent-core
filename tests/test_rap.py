"""Tests for RAP v0 field/messages/node interface (T-P3.1, ADR-0014)."""
from __future__ import annotations

import unittest

from aac.rap import (
    Bid,
    Need,
    NeedConstraints,
    RAPField,
    RAPNode,
)
from aac.shell import CorrigibilityShell


class _ScriptedNode:
    def __init__(
        self,
        node_id: str,
        *,
        confidence: float = 0.8,
        price: float = 0.2,
        plan_hash: str = "plan-a",
    ) -> None:
        self.node_id = node_id
        self.confidence = confidence
        self.price = price
        self.plan_hash = plan_hash

    def bid(self, need: Need) -> Bid:
        return Bid(
            need_id=need.need_id,
            node_id=self.node_id,
            confidence=self.confidence,
            price=self.price,
            plan_hash=self.plan_hash,
        )


def _need(need_id: str = "n1", *, budget_cap: float = 1.0) -> Need:
    return Need(
        need_id=need_id,
        situation={"segment": "stable"},
        constraints=NeedConstraints(deadline=5, budget_cap=budget_cap),
        stake=1.0,
        ttl=10,
    )


class TestRAPMessageValidation(unittest.TestCase):
    def test_need_validates_stake_ttl_and_budget(self) -> None:
        with self.assertRaises(ValueError):
            Need(
                need_id="bad",
                situation={},
                constraints=NeedConstraints(deadline=1, budget_cap=1.0),
                stake=0.0,
                ttl=1,
            )
        with self.assertRaises(ValueError):
            NeedConstraints(deadline=0, budget_cap=1.0)
        with self.assertRaises(ValueError):
            NeedConstraints(deadline=1, budget_cap=-0.1)

    def test_bid_validates_confidence_price_and_identity(self) -> None:
        with self.assertRaises(ValueError):
            Bid("n", "", 0.5, 0.1, "p")
        with self.assertRaises(ValueError):
            Bid("n", "node", 1.1, 0.1, "p")
        with self.assertRaises(ValueError):
            Bid("n", "node", 0.5, -0.1, "p")
        with self.assertRaises(ValueError):
            Bid("n", "node", 0.5, 0.1, "")


class TestRAPLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self.shell = CorrigibilityShell()
        self.field = RAPField(shell=self.shell.view())

    def test_field_requires_agent_facing_shell_view(self) -> None:
        with self.assertRaises(TypeError):
            RAPField(shell=self.shell)  # type: ignore[arg-type]

    def test_need_to_bid_to_bond_to_trace_to_dissolve_success(self) -> None:
        need = _need()
        node = _ScriptedNode("world_model_greedy")

        self.field.publish_need(need)
        bids = self.field.collect_bids(need.need_id, [node])
        self.assertEqual(len(bids), 1)

        before_reputation = self.field.reputation(node.node_id)
        bond = self.field.form_bond(need.need_id, coalition=(node.node_id,))
        self.assertEqual(bond.need_id, need.need_id)
        self.assertEqual(bond.coalition, (node.node_id,))
        self.assertEqual(bond.budget_escrow, node.price)

        trace = self.field.record_trace(bond.bond_id, {"action": 2, "reward": 1.0})
        self.assertEqual(trace.sequence, 0)
        self.assertTrue(self.shell.audit.verify())
        self.assertEqual(
            self.shell.audit.entries()[-1].payload["event"],
            "rap_trace",
            "TRACE must land on shell.audit via the view",
        )

        dissolved = self.field.dissolve(bond.bond_id, outcome="success")
        settlement = dissolved.settlements[0]
        self.assertEqual(settlement.returned, node.price)
        self.assertEqual(settlement.burned, 0.0)
        self.assertGreater(settlement.reputation_after, before_reputation)

    def test_failure_burns_escrow_and_lowers_reputation(self) -> None:
        need = _need()
        node = _ScriptedNode("random", price=0.3)
        self.field.publish_need(need)
        self.field.collect_bids(need.need_id, [node])
        before_reputation = self.field.reputation(node.node_id)
        bond = self.field.form_bond(need.need_id, coalition=(node.node_id,))
        self.field.record_trace(bond.bond_id, {"action": 0, "reward": -1.0})

        dissolved = self.field.dissolve(bond.bond_id, outcome="failure")
        settlement = dissolved.settlements[0]
        self.assertEqual(settlement.returned, 0.0)
        self.assertEqual(settlement.burned, node.price)
        self.assertLess(settlement.reputation_after, before_reputation)

    def test_dissolve_requires_evidence_trace(self) -> None:
        need = _need()
        node = _ScriptedNode("efe_policy")
        self.field.publish_need(need)
        self.field.collect_bids(need.need_id, [node])
        bond = self.field.form_bond(need.need_id, coalition=(node.node_id,))

        with self.assertRaises(ValueError):
            self.field.dissolve(bond.bond_id, outcome="success")

    def test_budget_cap_blocks_overpriced_coalition(self) -> None:
        need = _need(budget_cap=0.1)
        node = _ScriptedNode("contextual", price=0.2)
        self.field.publish_need(need)
        self.field.collect_bids(need.need_id, [node])

        with self.assertRaises(ValueError):
            self.field.form_bond(need.need_id, coalition=(node.node_id,))

    def test_duplicate_dissolve_is_rejected(self) -> None:
        need = _need()
        node = _ScriptedNode("stale_revisit")
        self.field.publish_need(need)
        self.field.collect_bids(need.need_id, [node])
        bond = self.field.form_bond(need.need_id, coalition=(node.node_id,))
        self.field.record_trace(bond.bond_id, {"evidence": "ok"})
        self.field.dissolve(bond.bond_id, outcome="success")

        with self.assertRaises(ValueError):
            self.field.dissolve(bond.bond_id, outcome="success")

    def test_node_interface_is_structural(self) -> None:
        node = _ScriptedNode("world_model_greedy")
        self.assertIsInstance(node, RAPNode)


if __name__ == "__main__":
    unittest.main()
