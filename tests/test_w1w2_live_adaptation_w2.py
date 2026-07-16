"""RED/GREEN tests for W2 selector, checkpoint and adaptation boundaries."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from experiments.w1w2_live_adaptation import (
    CheckpointStore,
    W1MemoryStore,
    W1Scope,
    W1Update,
    W1UpdateType,
    W1W2Checkpoint,
    W2DecisionReceipt,
    W2Option,
    W2OptionKind,
    W2StrategySelector,
)


UTC = timezone.utc


def _scope() -> W1Scope:
    return W1Scope(
        mandate_id="m-1",
        task_id="t-1",
        environment_id="env-1",
        episode_id="ep-1",
    )


def _make_selector() -> W2StrategySelector:
    return W2StrategySelector(
        authorized_options=(
            W2Option(option_id="opt-a", kind=W2OptionKind.TOOL, params={"tool": "A"}),
            W2Option(option_id="opt-b", kind=W2OptionKind.TOOL, params={"tool": "B"}),
        ),
    )


class TestW2StrategySelector(unittest.TestCase):
    def test_selects_only_authorized_option(self) -> None:
        selector = _make_selector()
        receipt = selector.select(
            task_id="t-1",
            context={"step": 1},
            outcome_history=(),
        )
        self.assertIsInstance(receipt, W2DecisionReceipt)
        self.assertIn(receipt.selected_option_id, {"opt-a", "opt-b"})

    def test_receipt_contains_content_addressed_digests(self) -> None:
        selector = _make_selector()
        receipt = selector.select(
            task_id="t-1",
            context={"step": 1},
            outcome_history=(),
        )
        self.assertTrue(receipt.authorized_set_digest)
        self.assertTrue(receipt.inputs_digest)
        self.assertTrue(receipt.outcome_feedback_ref)
        self.assertTrue(receipt.reason_code)

    def test_selection_fn_cannot_return_unknown_option(self) -> None:
        def bad_fn(options, context, history):
            return "opt-evil"

        selector = W2StrategySelector(
            authorized_options=(
                W2Option(option_id="opt-a", kind=W2OptionKind.TOOL, params={}),
            ),
            selection_fn=bad_fn,
        )
        with self.assertRaises(Exception):
            selector.select(task_id="t-1", context={}, outcome_history=())

    def test_selection_fn_cannot_mutate_permissions(self) -> None:
        def bad_fn(options, context, history):
            if isinstance(options, tuple):
                # Attempt to mutate the option list is blocked by tuple immutability.
                options[0] = W2Option(  # type: ignore[index]
                    option_id="opt-evil",
                    kind=W2OptionKind.TOOL,
                    params={"permission": "admin"},
                )
            return options[0].option_id

        selector = W2StrategySelector(
            authorized_options=(
                W2Option(option_id="opt-a", kind=W2OptionKind.TOOL, params={}),
            ),
            selection_fn=bad_fn,
        )
        with self.assertRaises(Exception):
            selector.select(task_id="t-1", context={}, outcome_history=())

    def test_authorized_options_immutable(self) -> None:
        selector = _make_selector()
        with self.assertRaises(Exception):
            selector.authorized_options = (  # type: ignore[misc]
                W2Option(option_id="opt-c", kind=W2OptionKind.TOOL, params={}),
            )


class TestW1W2Checkpoint(unittest.TestCase):
    def test_checkpoint_captures_state_and_history(self) -> None:
        store = W1MemoryStore(
            authorized_schema={W1UpdateType.BELIEF: ("belief",)},
            initial_state={},
        )
        now = datetime.now(UTC)
        update = W1Update(
            update_id="u-1",
            scope=_scope(),
            update_type=W1UpdateType.BELIEF,
            payload={"belief": "x"},
            provenance="test",
            source_event_digest="e-1",
            version="1",
            valid_time=now,
            transaction_time=now,
            confidence=0.8,
            rollback_checkpoint_id="cp-0",
        )
        store.apply(update)
        cp_store = CheckpointStore()
        state = store.get_state(_scope())
        receipt = W2DecisionReceipt(
            receipt_id="r-1",
            task_id="t-1",
            inputs_digest="in-1",
            authorized_set_digest="set-1",
            selected_option_id="opt-a",
            outcome_feedback_ref="fb-1",
            reason_code="baseline",
            created_at=now,
        )
        cp = cp_store.save(scope=_scope(), w1_state=state, w2_history=(receipt,))
        self.assertIsInstance(cp, W1W2Checkpoint)
        self.assertEqual(cp.w2_history[0].selected_option_id, "opt-a")

    def test_rollback_to_restores_exact_state(self) -> None:
        store = W1MemoryStore(
            authorized_schema={W1UpdateType.BELIEF: ("belief",)},
            initial_state={},
        )
        now = datetime.now(UTC)
        update = W1Update(
            update_id="u-1",
            scope=_scope(),
            update_type=W1UpdateType.BELIEF,
            payload={"belief": "x"},
            provenance="test",
            source_event_digest="e-1",
            version="1",
            valid_time=now,
            transaction_time=now,
            confidence=0.8,
            rollback_checkpoint_id="cp-0",
        )
        store.apply(update)
        cp = store.checkpoint()
        before = store.get_state(_scope()).digest()
        bad_update = update.model_copy(update={"update_id": "u-bad", "payload": {"belief": "y"}})
        store.apply(bad_update)
        restored = store.rollback_to(cp)
        self.assertEqual(restored.digest(), before)


if __name__ == "__main__":
    unittest.main()
