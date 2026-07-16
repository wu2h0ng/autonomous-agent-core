"""Wave A tests for W2 selector, immutable options and authority registry."""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from typing import Iterator

from experiments.w1w2_live_adaptation import (
    ActionValueEstimate,
    BeliefPayload,
    TaskPayload,
    ToolOption,
    W1CanonicalReader,
    W1MemoryStore,
    W1MemoryState,
    W1Scope,
    W1Update,
    W1UpdateLinter,
    W1UpdateType,
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


def _decision_state(
    *, unrelated_tail: bool = False, belief_statement: str = "free text is not consumed"
) -> W1MemoryState:
    scope = W1Scope(
        mandate_id="m-1", task_id="t-1", environment_id="env-1", episode_id="ep-1"
    )
    now = datetime.now(UTC)
    belief = W1Update(
        update_id="belief-1",
        scope=scope,
        update_type=W1UpdateType.BELIEF,
        payload=BeliefPayload(
            belief_statement=belief_statement,
            confidence=0.8,
            action_values=(
                ActionValueEstimate(
                    action_id="opt-a", last_reward=0.0, observation_count=1
                ),
                ActionValueEstimate(
                    action_id="opt-b", last_reward=1.0, observation_count=2
                ),
            ),
            last_observed_action_id="opt-b",
            last_observed_reward=1.0,
        ),
        provenance="typed-feedback",
        source_event_digest="event-1",
        correction_epoch=0,
        rollback_checkpoint_id="cp-1",
        version="1",
        valid_time=now,
        transaction_time=now,
    )
    updates = [belief]
    if unrelated_tail:
        updates.append(
            W1Update(
                update_id="task-1",
                scope=scope,
                update_type=W1UpdateType.TASK,
                payload=TaskPayload(task_statement="unrelated", priority=1),
                provenance="task-update",
                source_event_digest="event-2",
                correction_epoch=0,
                rollback_checkpoint_id="cp-2",
                version="1",
                valid_time=now,
                transaction_time=now,
            )
        )
    return W1MemoryState(scope=scope, updates=tuple(updates), epoch=len(updates))


@contextmanager
def _bound_selector(
    state: W1MemoryState,
) -> Iterator[tuple[W2StrategySelector, W1CanonicalReader]]:
    with TemporaryDirectory() as tmpdir:
        store = W1MemoryStore(db_path=f"{tmpdir}/w1.db", linter=W1UpdateLinter())
        store.activate_scope(state.scope)
        for update in state.updates:
            result = store.apply(update)
            if not result.applied:
                raise AssertionError(result.violations)
        reader = W1CanonicalReader(store=store, scope=state.scope)
        selector = W2StrategySelector(
            registry=_registry(),
            authorized_option_ids=("opt-a", "opt-b"),
            w1_reader=reader,
            w1_scope=state.scope,
        )
        yield selector, reader
        store.close()


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
        decision_state = _decision_state()
        with _bound_selector(decision_state) as (selector, reader):
            reads_before = reader.read_count
            receipt = selector.select(
                context={"observation_id": "opaque"}, outcome_history=()
            )
            self.assertEqual(reader.read_count - reads_before, 1)
            self.assertEqual(receipt.selected_option_id, "opt-b")
            canonical = selector.canonical_decision_state(decision_state)
            self.assertEqual(
                receipt.consumed_w1_decision_state_digest,
                canonical.digest(),
            )
            text_mutation = selector.canonical_decision_state(
                _decision_state(belief_statement="action=opt-a; regime=A; oracle=opt-a")
            )
            self.assertEqual(canonical.digest(), text_mutation.digest())

    def test_rejects_forged_digest_preference_and_unrelated_tail(self) -> None:
        selector = W2StrategySelector(
            registry=_registry(),
            authorized_option_ids=("opt-a", "opt-b"),
        )
        with self.assertRaises(TypeError):
            selector.select(
                context={},
                outcome_history=(),
                consumed_w1_state_digest="forged",  # type: ignore[call-arg]
                preferred_option_id="opt-evil",  # type: ignore[call-arg]
            )
        with self.assertRaises(TypeError):
            selector.select(
                context={},
                outcome_history=(),
                decision_state=_decision_state(),  # type: ignore[call-arg]
            )
        with _bound_selector(_decision_state(unrelated_tail=True)) as (bound, _reader):
            with self.assertRaises(ValueError):
                bound.select(context={}, outcome_history=())

    def test_fake_or_foreign_reader_scope_fails_closed(self) -> None:
        state = _decision_state()
        with self.assertRaises(TypeError):
            W2StrategySelector(
                registry=_registry(),
                authorized_option_ids=("opt-a", "opt-b"),
                w1_reader=object(),  # type: ignore[arg-type]
                w1_scope=state.scope,
            )
        with TemporaryDirectory() as tmpdir:
            store = W1MemoryStore(db_path=f"{tmpdir}/w1.db", linter=W1UpdateLinter())
            reader = W1CanonicalReader(store=store, scope=state.scope)
            foreign_scope = state.scope.model_copy(update={"task_id": "foreign"})
            with self.assertRaises(ValueError):
                W2StrategySelector(
                    registry=_registry(),
                    authorized_option_ids=("opt-a", "opt-b"),
                    w1_reader=reader,
                    w1_scope=foreign_scope,
                )
            store.close()

    def test_callback_path_does_not_read_or_claim_w1_consumption(self) -> None:
        state = _decision_state()
        with TemporaryDirectory() as tmpdir:
            store = W1MemoryStore(db_path=f"{tmpdir}/w1.db", linter=W1UpdateLinter())
            store.activate_scope(state.scope)
            for update in state.updates:
                self.assertTrue(store.apply(update).applied)
            reader = W1CanonicalReader(store=store, scope=state.scope)
            selector = W2StrategySelector(
                registry=_registry(),
                authorized_option_ids=("opt-a", "opt-b"),
                selection_fn=lambda options, _context, _history: options[1],
                w1_reader=reader,
                w1_scope=state.scope,
            )
            reads_before = reader.read_count
            receipt = selector.select(context={}, outcome_history=())
            self.assertEqual(reader.read_count, reads_before)
            self.assertIsNone(receipt.consumed_w1_decision_state_digest)
            store.close()


if __name__ == "__main__":
    unittest.main()
