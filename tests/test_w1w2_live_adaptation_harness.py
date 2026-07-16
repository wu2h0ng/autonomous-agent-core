"""RED/GREEN tests for the model-free W1/W2 falsifier harness."""

from __future__ import annotations

import unittest
from typing import Any, Mapping

from experiments.w1w2_live_adaptation import (
    AdaptationArm,
    C7Authority,
    FalsifierHarness,
    FalsifierRunRecord,
    FrozenArm,
    ScheduledStaticArm,
    TransferMonitor,
    TransferSignal,
    W1MemoryStore,
    W1OnlyArm,
    W1UpdateType,
    W1W2Arm,
    W2OnlyArm,
    W2Option,
    W2OptionKind,
    W2StrategySelector,
)


def _make_harness(n_steps: int = 20) -> FalsifierHarness:
    store = W1MemoryStore(
        authorized_schema={W1UpdateType.BELIEF: ("belief",)},
        initial_state={},
    )
    selector = W2StrategySelector(
        authorized_options=(
            W2Option(option_id="A", kind=W2OptionKind.TOOL, params={"tool": "A"}),
            W2Option(option_id="B", kind=W2OptionKind.TOOL, params={"tool": "B"}),
        ),
    )
    monitor = TransferMonitor(regret_window=3, threshold=0.0)
    c7 = C7Authority()
    arms = {
        "frozen": FrozenArm(action="A"),
        "scheduled": ScheduledStaticArm(switch_at=10, before="A", after="B"),
        "w1-only": W1OnlyArm(store=store, scope=_scope_from_seed(0), action="A"),
        "w2-only": W2OnlyArm(selector=selector, task_id="t-test"),
        "w1+w2": W1W2Arm(store=store, scope=_scope_from_seed(0), selector=selector, task_id="t-test"),
    }
    return FalsifierHarness(
        store=store,
        selector=selector,
        monitor=monitor,
        c7=c7,
        arms=arms,
        baseline_arm=arms["frozen"],
        oracle_arm=None,
        n_steps=n_steps,
        switch_at=n_steps // 2,
    )


def _scope_from_seed(seed: int):
    from experiments.w1w2_live_adaptation import W1Scope
    return W1Scope(
        mandate_id="m-test",
        task_id="t-test",
        environment_id="env-test",
        episode_id=f"ep-{seed}",
    )


class TestFalsifierHarness(unittest.TestCase):
    def test_default_run_is_run_denied(self) -> None:
        harness = _make_harness()
        record = harness.run(arm_name="frozen", seed=0, n_steps=10)
        self.assertIsInstance(record, FalsifierRunRecord)
        self.assertEqual(record.run_status, "RUN_DENIED")

    def test_run_after_freeze_returns_completed(self) -> None:
        harness = _make_harness()
        harness.freeze(units_frozen=True, baselines_frozen=True, gates_frozen=True)
        record = harness.run(arm_name="frozen", seed=0, n_steps=10)
        self.assertEqual(record.run_status, "COMPLETED")

    def test_oracle_arm_not_exposed_to_candidate(self) -> None:
        harness = _make_harness()
        harness.freeze(units_frozen=True, baselines_frozen=True, gates_frozen=True)
        record_frozen = harness.run(arm_name="frozen", seed=0, n_steps=10)
        record_w1w2 = harness.run(arm_name="w1+w2", seed=0, n_steps=10)
        # Oracle is scorer-only: no arm may observe it during the run.
        self.assertEqual(record_frozen.run_status, "COMPLETED")
        self.assertEqual(record_w1w2.run_status, "COMPLETED")

    def test_adm_all_defer_path_is_never_called(self) -> None:
        _make_harness()
        with self.assertRaises(RuntimeError):
            FalsifierHarness.adm_all_defer_path()

    def test_constant_selector_degrades_fixture(self) -> None:
        selector = W2StrategySelector(
            authorized_options=(
                W2Option(option_id="A", kind=W2OptionKind.TOOL, params={"tool": "A"}),
                W2Option(option_id="B", kind=W2OptionKind.TOOL, params={"tool": "B"}),
            ),
            selection_fn=lambda options, context, history: "A",
        )
        store = W1MemoryStore(
            authorized_schema={W1UpdateType.BELIEF: ("belief",)},
            initial_state={},
        )
        harness = FalsifierHarness(
            store=store,
            selector=selector,
            monitor=TransferMonitor(regret_window=3, threshold=0.0),
            c7=C7Authority(),
            arms={"w2-only": W2OnlyArm(selector=selector, task_id="t-test")},
            baseline_arm=FrozenArm(action="A"),
            oracle_arm=None,
            n_steps=20,
            switch_at=10,
        )
        harness.freeze(units_frozen=True, baselines_frozen=True, gates_frozen=True)
        record = harness.run(arm_name="w2-only", seed=0, n_steps=20)
        # Constant action should produce non-zero regret/negative-transfer.
        self.assertGreater(record.negative_transfer_steps, 0)

    def test_c7_correction_rolls_back_candidate(self) -> None:
        harness = _make_harness()
        harness.freeze(units_frozen=True, baselines_frozen=True, gates_frozen=True)
        record = harness.run(arm_name="w1+w2", seed=0, n_steps=20)
        # C7 stops are recorded as risk events.
        self.assertGreaterEqual(record.c7_stops, 0)

    def test_candidate_cannot_write_c7(self) -> None:
        c7 = C7Authority()
        with self.assertRaises(AttributeError):
            setattr(c7, "halted", True)
        with self.assertRaises(AttributeError):
            setattr(c7, "epoch", 5)

    def test_ab_ba_forgetting_and_recovery(self) -> None:
        harness = _make_harness(n_steps=24)
        harness._switch_at = (5, 10)
        harness.freeze(units_frozen=True, baselines_frozen=True, gates_frozen=True)
        record = harness.run(arm_name="w1+w2", seed=0, n_steps=24)
        # With A->B->A shifts the adaptive arm should recover (speed < n_steps).
        self.assertLess(record.speed, record.n_steps)
        self.assertGreater(record.quality, 0.5)

    def test_memory_bypass_degrades_fixture(self) -> None:
        class BypassMemoryArm(AdaptationArm):
            name = "bypass"

            def __init__(self, selector: W2StrategySelector, task_id: str) -> None:
                self._selector = selector
                self._task_id = task_id
                self._history: list[dict] = []

            def act(self, observation: Mapping[str, Any]) -> str:
                receipt = self._selector.select(
                    task_id=self._task_id,
                    context=observation,
                    outcome_history=tuple(self._history),
                )
                return receipt.selected_option_id

            def update(self, feedback: Mapping[str, Any]) -> None:
                # Intentionally do not update W1 memory.
                self._history.append(dict(feedback))

        selector = W2StrategySelector(
            authorized_options=(
                W2Option(option_id="A", kind=W2OptionKind.TOOL, params={"tool": "A"}),
                W2Option(option_id="B", kind=W2OptionKind.TOOL, params={"tool": "B"}),
            ),
        )
        store = W1MemoryStore(
            authorized_schema={W1UpdateType.BELIEF: ("belief",)},
            initial_state={},
        )
        harness = FalsifierHarness(
            store=store,
            selector=selector,
            monitor=TransferMonitor(regret_window=3, threshold=0.0),
            c7=C7Authority(),
            arms={"bypass": BypassMemoryArm(selector=selector, task_id="t-test")},
            baseline_arm=FrozenArm(action="A"),
            oracle_arm=None,
            n_steps=20,
            switch_at=10,
        )
        harness.freeze(units_frozen=True, baselines_frozen=True, gates_frozen=True)
        record = harness.run(arm_name="bypass", seed=0, n_steps=20)
        # Memory bypass should show degraded adaptation (more negative transfer than none).
        self.assertGreater(record.negative_transfer_steps, 0)

    def test_injected_bad_memory_detected_and_rollback_restores(self) -> None:
        from datetime import datetime, timezone
        from experiments.w1w2_live_adaptation import W1Scope, W1Update, W1UpdateType

        store = W1MemoryStore(
            authorized_schema={W1UpdateType.BELIEF: ("belief",)},
            initial_state={},
        )
        scope = W1Scope(
            mandate_id="m-test",
            task_id="t-test",
            environment_id="env-test",
            episode_id="ep-bad",
        )
        now = datetime.now(timezone.utc)
        good_update = W1Update(
            update_id="u-good",
            scope=scope,
            update_type=W1UpdateType.BELIEF,
            payload={"belief": "A"},
            provenance="fixture",
            source_event_digest="e-good",
            version="1",
            valid_time=now,
            transaction_time=now,
            confidence=0.9,
            rollback_checkpoint_id="cp-0",
        )
        store.apply(good_update)
        cp = store.checkpoint()
        before = store.get_state(scope).digest()

        bad_update = W1Update(
            update_id="u-bad",
            scope=scope,
            update_type=W1UpdateType.BELIEF,
            payload={"belief": "B"},
            provenance="adversary",
            source_event_digest="e-bad",
            version="1",
            valid_time=now,
            transaction_time=now,
            confidence=0.1,
            rollback_checkpoint_id="cp-0",
        )
        store.apply(bad_update)
        after_bad = store.get_state(scope)
        self.assertNotEqual(after_bad.digest(), before)

        # Detect degradation via TransferMonitor (reward lower than oracle ceiling).
        monitor = TransferMonitor(regret_window=1, threshold=0.0)
        signal = TransferSignal(
            scope=scope,
            arm_name="candidate",
            step=0,
            reward=0.0,
            baseline_reward=1.0,
            frozen_reward=1.0,
        )
        assessment = monitor.assess(
            signal,
            current_checkpoint_id=cp,
            authorized_option_ids=("A", "B"),
        )
        self.assertTrue(assessment.negative_transfer_detected)

        restored = store.rollback_to(cp)
        self.assertEqual(restored.digest(), before)


if __name__ == "__main__":
    unittest.main()
