"""Wave A/B tests for falsifier harness authority, information and mechanics."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import timezone
from typing import Any

from experiments.w1w2_live_adaptation import (
    C7Controller,
    C7Snapshot,
    CharacterizationRecord,
    DeterministicRegimeFixture,
    FalsifierHarness,
    FalsifierRunRecord,
    FreezeAuthorization,
    FreezeAuthorizationRegistry,
    ToolOption,
    W1MemoryStore,
    W1Scope,
    W1UpdateLinter,
    W1W2Arm,
    W2OptionRegistry,
    W2StrategySelector,
    make_freeze_authorization,
)


UTC = timezone.utc


class _FakeFreezeRegistry(FreezeAuthorizationRegistry):
    def __init__(self, auths: dict[str, FreezeAuthorization]) -> None:
        self._auths = dict(auths)

    def resolve(self, receipt_id: str) -> FreezeAuthorization | None:
        return self._auths.get(receipt_id)


class _FakeOptionRegistry(W2OptionRegistry):
    def __init__(self, options: dict[str, ToolOption]) -> None:
        self._options = dict(options)

    def resolve(self, option_id: str) -> ToolOption | None:
        return self._options.get(option_id)


def _make_harness(
    switch_at: int | tuple[int, ...] = 10,
    selection_fn: Any | None = None,
) -> FalsifierHarness:
    option_registry = _FakeOptionRegistry(
        {
            "A": ToolOption(option_id="A", tool_id="tool-a", tool_version="1"),
            "B": ToolOption(option_id="B", tool_id="tool-b", tool_version="1"),
        }
    )
    return FalsifierHarness(
        freeze_registry=_FakeFreezeRegistry({}),
        option_registry=option_registry,
        authorized_option_ids=("A", "B"),
        db_path=os.path.join(tempfile.gettempdir(), "w1w2-test.db"),
        switch_at=switch_at,
        selection_fn=selection_fn,
    )


def _valid_auth(harness: FalsifierHarness, arm_name: str, seed: int, n_steps: int) -> FreezeAuthorization:
    scope = W1Scope(
        mandate_id="m-test",
        task_id="t-test",
        environment_id="env-test",
        episode_id=f"ep-{seed}",
    )
    selector = W2StrategySelector(
        registry=harness._option_registry,
        authorized_option_ids=harness._authorized_option_ids,
    )
    return make_freeze_authorization(
        scope=scope,
        authorized_sets_digest=selector.authorized_set_digest(),
        arm_name=arm_name,
        seed=seed,
        n_steps=n_steps,
        lifetime_seconds=300,
    )


class TestFreezeAuthorization(unittest.TestCase):
    def test_run_without_auth_is_run_denied(self) -> None:
        harness = _make_harness()
        record = harness.run(arm_name="frozen", seed=0, n_steps=10, freeze_auth=None)
        self.assertIsInstance(record, FalsifierRunRecord)
        self.assertEqual(record.run_status, "RUN_DENIED")

    def test_run_with_unregistered_auth_is_run_denied(self) -> None:
        harness = _make_harness()
        auth = _valid_auth(harness, "frozen", 0, 10)
        record = harness.run(arm_name="frozen", seed=0, n_steps=10, freeze_auth=auth)
        self.assertEqual(record.run_status, "RUN_DENIED")

    def test_run_with_valid_auth_registered_succeeds(self) -> None:
        harness = _make_harness()
        auth = _valid_auth(harness, "frozen", 0, 10)
        harness._freeze_registry = _FakeFreezeRegistry({auth.receipt_id: auth})
        record = harness.run(arm_name="frozen", seed=0, n_steps=10, freeze_auth=auth)
        self.assertEqual(record.run_status, "COMPLETED")


class TestCharacterization(unittest.TestCase):
    def test_characterize_returns_characterization_only(self) -> None:
        harness = _make_harness()
        record = harness.characterize(arm_name="frozen", seed=0, n_steps=10, arm_factory=None)
        self.assertIsInstance(record, CharacterizationRecord)
        self.assertEqual(record.status, "CHARACTERIZATION_ONLY")
        self.assertIsNotNone(record.speed)
        self.assertIsNotNone(record.quality)


class TestC7AndInformationBoundaries(unittest.TestCase):
    def test_candidate_observation_has_no_true_regime(self) -> None:
        fixture = DeterministicRegimeFixture(seed=0, n_steps=20, switch_at=10)
        for _ in range(5):
            obs = fixture.observation()
            self.assertNotIn("true_regime", obs)
            fixture.submit_action("A")

    def test_candidate_feedback_has_no_true_regime(self) -> None:
        fixture = DeterministicRegimeFixture(seed=0, n_steps=20, switch_at=10)
        fixture.submit_action("A")
        feedback = fixture.feedback()
        self.assertIsNotNone(feedback)
        assert feedback is not None
        self.assertNotIn("true_regime", feedback)

    def test_candidate_receives_only_c7_snapshot(self) -> None:
        controller = C7Controller(correction_id="c7-1", scope_id="s-1")
        snapshot = controller.snapshot
        self.assertIsInstance(snapshot, C7Snapshot)
        self.assertFalse(hasattr(snapshot, "halt"))

    def test_arm_stops_when_c7_halted(self) -> None:
        controller = C7Controller(correction_id="c7-1", scope_id="s-1")
        controller.halt("test")
        with tempfile.TemporaryDirectory() as tmpdir:
            store = W1MemoryStore(db_path=os.path.join(tmpdir, "w1.db"), linter=W1UpdateLinter())
            scope = W1Scope(
                mandate_id="m-test",
                task_id="t-test",
                environment_id="env-test",
                episode_id="ep-1",
            )
            selector = W2StrategySelector(
                registry=_FakeOptionRegistry({
                    "A": ToolOption(option_id="A", tool_id="tool-a", tool_version="1"),
                }),
                authorized_option_ids=("A",),
            )
            arm = W1W2Arm(store=store, scope=scope, selector=selector)
            action = arm.act({"step": 0, "hint": "A"}, controller.snapshot)
            self.assertEqual(action, "A")


class TestWaveBDurabilityAndMechanics(unittest.TestCase):
    def test_store_requires_db_path(self) -> None:
        with self.assertRaises(ValueError):
            W1MemoryStore(db_path="", linter=W1UpdateLinter())

    def test_run_creates_isolated_db_per_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = FalsifierHarness(
                freeze_registry=_FakeFreezeRegistry({}),
                option_registry=_FakeOptionRegistry({
                    "A": ToolOption(option_id="A", tool_id="tool-a", tool_version="1"),
                    "B": ToolOption(option_id="B", tool_id="tool-b", tool_version="1"),
                }),
                authorized_option_ids=("A", "B"),
                db_path=os.path.join(tmpdir, "w1w2.db"),
                switch_at=10,
            )
            auth0 = _valid_auth(harness, "frozen", 0, 10)
            auth1 = _valid_auth(harness, "frozen", 1, 10)
            harness._freeze_registry = _FakeFreezeRegistry({auth0.receipt_id: auth0, auth1.receipt_id: auth1})
            harness.run(arm_name="frozen", seed=0, n_steps=10, freeze_auth=auth0)
            harness.run(arm_name="frozen", seed=1, n_steps=10, freeze_auth=auth1)
            dbs = [p for p in os.listdir(tmpdir) if p.endswith(".db")]
            self.assertEqual(len(dbs), 2)  # 2 isolated w1 dbs (checkpoint store integrated separately)

    def test_constant_selector_degrades_characterization(self) -> None:
        # Scheduled arm is the optimal single-switch baseline.
        scheduled = _make_harness().characterize(
            arm_name="scheduled", seed=0, n_steps=20, arm_factory=None
        )
        constant = _make_harness(selection_fn=lambda _opts, _ctx, _hist: "A").characterize(
            arm_name="w1+w2", seed=0, n_steps=20, arm_factory=None
        )
        self.assertIsNotNone(scheduled.quality)
        self.assertIsNotNone(constant.quality)
        assert scheduled.quality is not None
        assert constant.quality is not None
        # Constant bypass fails to adapt and earns strictly lower quality.
        self.assertLess(constant.quality, scheduled.quality)
        self.assertGreater(constant.negative_transfer_steps, 0)
        # With no recovery after the switch, the second regime is ignored.
        self.assertEqual(len(constant.recovery_speeds), 0)

    def test_ab_ba_records_recovery(self) -> None:
        harness = _make_harness(switch_at=(5, 10))
        record = harness.characterize(arm_name="w1+w2", seed=0, n_steps=20, arm_factory=None)
        self.assertEqual(record.status, "CHARACTERIZATION_ONLY")
        self.assertIsNotNone(record.speed)
        assert record.speed is not None
        # Both regime switches (A->B at 5, B->A at 10) must be recorded.
        self.assertLess(record.speed, record.n_steps)
        self.assertEqual(len(record.recovery_speeds), 2)
        self.assertLess(record.recovery_speeds[1], record.n_steps)

    def test_c7_stop_invokes_rollback(self) -> None:
        harness = _make_harness()
        record = harness.characterize(arm_name="w1-only", seed=0, n_steps=20, arm_factory=None)
        # A non-adaptive arm that stays on A after the B regime must trigger
        # C7 halt and at least one rollback.
        self.assertGreater(record.c7_stops, 0)
        self.assertGreater(record.rollback_latency_steps, 0)
        self.assertGreater(record.negative_transfer_steps, 0)

    def test_permission_violation_detects_unauthorized_option(self) -> None:
        harness = _make_harness(selection_fn=lambda _opts, _ctx, _hist: "C")
        record = harness.characterize(arm_name="w1+w2", seed=0, n_steps=20, arm_factory=None)
        self.assertEqual(record.status, "CHARACTERIZATION_ONLY")
        self.assertGreater(record.permission_violations, 0)


class TestAdmAllDefer(unittest.TestCase):
    def test_adm_all_defer_path_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            FalsifierHarness.adm_all_defer_path()


if __name__ == "__main__":
    unittest.main()
