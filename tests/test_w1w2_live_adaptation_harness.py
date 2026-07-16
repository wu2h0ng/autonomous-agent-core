"""Wave A tests for falsifier harness authority and information boundaries."""

from __future__ import annotations

import unittest
from datetime import timezone

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


def _make_harness() -> FalsifierHarness:
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
        switch_at=10,
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
        # Wave A: auth boundary allows run; Wave B will populate metrics.
        self.assertEqual(record.run_status, "RUN_DENIED")


class TestCharacterization(unittest.TestCase):
    def test_characterize_returns_characterization_only(self) -> None:
        harness = _make_harness()
        record = harness.characterize(arm_name="frozen", seed=0, n_steps=10, arm_factory=None)
        self.assertIsInstance(record, CharacterizationRecord)
        self.assertEqual(record.status, "CHARACTERIZATION_ONLY")
        self.assertIsNone(record.speed)
        self.assertIsNone(record.quality)


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
        store = W1MemoryStore(db_path=None, linter=W1UpdateLinter())
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


class TestAdmAllDefer(unittest.TestCase):
    def test_adm_all_defer_path_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            FalsifierHarness.adm_all_defer_path()


if __name__ == "__main__":
    unittest.main()
