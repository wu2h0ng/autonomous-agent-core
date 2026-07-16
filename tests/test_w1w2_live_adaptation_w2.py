"""Wave A tests for W2 selector, immutable options and authority registry."""

from __future__ import annotations

import unittest
from datetime import timezone

from experiments.w1w2_live_adaptation import (
    ToolOption,
    W2DecisionReceipt,
    W2OptionRegistry,
    W2StrategySelector,
)


UTC = timezone.utc


class _InMemoryOptionRegistry(W2OptionRegistry):
    def __init__(self, options: dict[str, ToolOption]) -> None:
        self._options = dict(options)

    def resolve(self, option_id: str) -> ToolOption | None:
        return self._options.get(option_id)


def _registry() -> _InMemoryOptionRegistry:
    return _InMemoryOptionRegistry(
        {
            "opt-a": ToolOption(option_id="opt-a", tool_id="tool-a", tool_version="1"),
            "opt-b": ToolOption(option_id="opt-b", tool_id="tool-b", tool_version="1"),
        }
    )


class TestW2StrategySelector(unittest.TestCase):
    def test_selects_only_authorized_and_registered_option(self) -> None:
        selector = W2StrategySelector(
            registry=_registry(),
            authorized_option_ids=("opt-a", "opt-b"),
        )
        receipt = selector.select(context={"step": 1}, outcome_history=())
        self.assertIsInstance(receipt, W2DecisionReceipt)
        self.assertIn(receipt.selected_option_id, {"opt-a", "opt-b"})

    def test_rejects_unknown_option(self) -> None:
        def bad_fn(options, context, history):
            return "opt-evil"

        selector = W2StrategySelector(
            registry=_registry(),
            authorized_option_ids=("opt-a",),
            selection_fn=bad_fn,
        )
        with self.assertRaises(Exception):
            selector.select(context={}, outcome_history=())

    def test_rejects_unregistered_option(self) -> None:
        selector = W2StrategySelector(
            registry=_registry(),
            authorized_option_ids=("opt-a", "opt-missing"),
        )

        # opt-missing is authorized but not in registry.
        def pick_missing(options, context, history):
            return "opt-missing"

        selector = W2StrategySelector(
            registry=_registry(),
            authorized_option_ids=("opt-a", "opt-missing"),
            selection_fn=pick_missing,
        )
        with self.assertRaises(Exception):
            selector.select(context={}, outcome_history=())

    def test_selection_fn_cannot_mutate_options(self) -> None:
        def bad_fn(options, context, history):
            if isinstance(options, tuple):
                options[0] = "opt-evil"  # type: ignore[index]
            return options[0]

        selector = W2StrategySelector(
            registry=_registry(),
            authorized_option_ids=("opt-a",),
            selection_fn=bad_fn,
        )
        with self.assertRaises(Exception):
            selector.select(context={}, outcome_history=())

    def test_authorized_option_ids_immutable(self) -> None:
        selector = W2StrategySelector(
            registry=_registry(),
            authorized_option_ids=("opt-a", "opt-b"),
        )
        with self.assertRaises(Exception):
            selector.authorized_option_ids = ("opt-c",)  # type: ignore[misc]

    def test_receipt_contains_content_addressed_digests(self) -> None:
        selector = W2StrategySelector(
            registry=_registry(),
            authorized_option_ids=("opt-a", "opt-b"),
        )
        receipt = selector.select(context={"step": 1}, outcome_history=())
        self.assertTrue(receipt.authorized_set_digest)
        self.assertTrue(receipt.inputs_digest)
        self.assertTrue(receipt.outcome_feedback_ref)
        self.assertTrue(receipt.reason_code)

    def test_receipt_binds_consumed_w1_state_and_uses_typed_preference(self) -> None:
        selector = W2StrategySelector(
            registry=_registry(),
            authorized_option_ids=("opt-a", "opt-b"),
        )
        receipt = selector.select(
            context={"observation_id": "opaque"},
            outcome_history=(),
            consumed_w1_state_digest="w1-digest-1",
            preferred_option_id="opt-b",
        )
        self.assertEqual(receipt.selected_option_id, "opt-b")
        self.assertEqual(receipt.consumed_w1_state_digest, "w1-digest-1")

    def test_rejects_w1_preference_outside_authorized_set(self) -> None:
        selector = W2StrategySelector(
            registry=_registry(),
            authorized_option_ids=("opt-a", "opt-b"),
        )
        with self.assertRaises(ValueError):
            selector.select(
                context={},
                outcome_history=(),
                consumed_w1_state_digest="w1-digest-1",
                preferred_option_id="opt-evil",
            )


if __name__ == "__main__":
    unittest.main()
