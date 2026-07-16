"""Wave A/B tests for falsifier harness authority, information and mechanics."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from typing import Any

from experiments.w1w2_live_adaptation import (
    AdaptationArm,
    C7Controller,
    C7Snapshot,
    CharacterizationRecord,
    DeterministicRegimeFixture,
    FalsifierHarness,
    FalsifierRunRecord,
    CanonicalRunAuthorization,
    CandidateFeedback,
    CandidateObservation,
    RunAuthorizationBinding,
    RunAuthorizationResolver,
    ScorerReceipt,
    ScorerReceiptBinding,
    SealedScorerOutcome,
    ToolOption,
    W1CanonicalReader,
    W1MemoryStore,
    W1MemoryState,
    W1OnlyArm,
    W1Scope,
    W1UpdateLinter,
    W1W2Arm,
    W2OptionRegistry,
    W2StrategySelector,
)


UTC = timezone.utc


class _FakeRunAuthorizationResolver(RunAuthorizationResolver):
    """Test-side stand-in for external custody; the package cannot mint receipts."""

    def __init__(self, auths: dict[str, CanonicalRunAuthorization]) -> None:
        self._auths = dict(auths)
        self._consumed: set[str] = set()

    def consume(
        self, receipt_id: str, expected: RunAuthorizationBinding
    ) -> CanonicalRunAuthorization | None:
        auth = self._auths.get(receipt_id)
        if auth is None or receipt_id in self._consumed or auth.binding != expected:
            return None
        self._consumed.add(receipt_id)
        return auth


class _FakeOptionRegistry(W2OptionRegistry):
    def __init__(self, options: dict[str, ToolOption]) -> None:
        self._options = dict(options)

    def resolve(self, option_id: str) -> ToolOption | None:
        return self._options.get(option_id)


class _FakeTrustedScorer:
    def __init__(self) -> None:
        self._receipts: dict[str, ScorerReceipt] = {}
        self._consumed: set[str] = set()

    def score(self, binding: ScorerReceiptBinding, outcome: SealedScorerOutcome) -> str:
        receipt_id = f"external-score-{binding.run_id}-{binding.step}"
        self._receipts[receipt_id] = ScorerReceipt(
            receipt_id=receipt_id, binding=binding, outcome=outcome
        )
        return receipt_id

    def consume(self, receipt_id, expected):
        receipt = self._receipts.get(receipt_id)
        if (
            receipt is None
            or receipt_id in self._consumed
            or receipt.binding != expected
        ):
            return None
        self._consumed.add(receipt_id)
        return receipt


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
        run_authorization_resolver=_FakeRunAuthorizationResolver({}),
        option_registry=option_registry,
        authorized_option_ids=("A", "B"),
        db_path=os.path.join(tempfile.gettempdir(), "w1w2-test.db"),
        switch_at=switch_at,
        selection_fn=selection_fn,
        trusted_scorer=_FakeTrustedScorer(),
    )


def _externally_issued_auth(
    harness: FalsifierHarness, receipt_id: str, arm_name: str, seed: int, n_steps: int
) -> CanonicalRunAuthorization:
    return CanonicalRunAuthorization(
        receipt_id=receipt_id,
        binding=harness.expected_run_binding(
            arm_name=arm_name, seed=seed, n_steps=n_steps
        ),
        issuer_id="independent-freezer",
        issued_at=datetime(2020, 1, 1, tzinfo=UTC),
        expires_at=datetime(2099, 7, 17, tzinfo=UTC),
    )


class TestFreezeAuthorization(unittest.TestCase):
    def test_package_exports_no_freeze_authorization_minter(self) -> None:
        import experiments.w1w2_live_adaptation as package

        self.assertFalse(hasattr(package, "make_freeze_authorization"))
        self.assertFalse(hasattr(package, "FreezeAuthorization"))

    def test_run_without_auth_is_run_denied(self) -> None:
        harness = _make_harness()
        record = harness.run(
            arm_name="frozen", seed=0, n_steps=10, authorization_receipt_id=None
        )
        self.assertIsInstance(record, FalsifierRunRecord)
        self.assertEqual(record.run_status, "RUN_DENIED")

    def test_run_with_unregistered_auth_is_run_denied(self) -> None:
        harness = _make_harness()
        record = harness.run(
            arm_name="frozen", seed=0, n_steps=10, authorization_receipt_id="forged"
        )
        self.assertEqual(record.run_status, "RUN_DENIED")

    def test_run_with_valid_auth_registered_succeeds(self) -> None:
        harness = _make_harness()
        auth = _externally_issued_auth(harness, "external-1", "frozen", 0, 10)
        harness._run_authorization_resolver = _FakeRunAuthorizationResolver(
            {auth.receipt_id: auth}
        )
        record = harness.run(
            arm_name="frozen",
            seed=0,
            n_steps=10,
            authorization_receipt_id=auth.receipt_id,
        )
        self.assertEqual(record.run_status, "COMPLETED")

    def test_run_receipt_is_one_time_and_bound_to_full_option_content(self) -> None:
        harness = _make_harness()
        auth = _externally_issued_auth(harness, "external-1", "frozen", 0, 10)
        resolver = _FakeRunAuthorizationResolver({auth.receipt_id: auth})
        harness._run_authorization_resolver = resolver
        first = harness.run("frozen", 0, 10, auth.receipt_id)
        second = harness.run("frozen", 0, 10, auth.receipt_id)
        self.assertEqual(first.run_status, "COMPLETED")
        self.assertEqual(second.run_status, "RUN_DENIED")
        mutated_registry = _FakeOptionRegistry(
            {
                "A": ToolOption(option_id="A", tool_id="mutated", tool_version="1"),
                "B": ToolOption(option_id="B", tool_id="tool-b", tool_version="1"),
            }
        )
        mutated = FalsifierHarness(
            run_authorization_resolver=_FakeRunAuthorizationResolver(
                {auth.receipt_id: auth}
            ),
            option_registry=mutated_registry,
            authorized_option_ids=("A", "B"),
            switch_at=(5, 10),
            trusted_scorer=_FakeTrustedScorer(),
        )
        denied = mutated.run("frozen", 0, 10, auth.receipt_id)
        self.assertEqual(denied.run_status, "RUN_DENIED")

    def test_result_run_denies_missing_scorer_and_stateful_selector_surface(
        self,
    ) -> None:
        base = _make_harness()
        auth = _externally_issued_auth(base, "external-2", "frozen", 0, 10)
        base._run_authorization_resolver = _FakeRunAuthorizationResolver(
            {auth.receipt_id: auth}
        )
        base._trusted_scorer = None
        self.assertEqual(
            base.run("frozen", 0, 10, auth.receipt_id).run_status, "RUN_DENIED"
        )

        callback = _make_harness(
            selection_fn=lambda options, _ctx, _history: options[0]
        )
        callback_auth = _externally_issued_auth(callback, "external-3", "w1+w2", 0, 10)
        callback._run_authorization_resolver = _FakeRunAuthorizationResolver(
            {callback_auth.receipt_id: callback_auth}
        )
        self.assertEqual(
            callback.run("w1+w2", 0, 10, callback_auth.receipt_id).run_status,
            "RUN_DENIED",
        )


class TestCharacterization(unittest.TestCase):
    def test_characterize_returns_characterization_only(self) -> None:
        harness = _make_harness()
        record = harness.characterize(
            arm_name="frozen", seed=0, n_steps=10, arm_factory=None
        )
        self.assertIsInstance(record, CharacterizationRecord)
        self.assertEqual(record.status, "CHARACTERIZATION_ONLY")
        self.assertIsNotNone(record.speed)
        self.assertIsNotNone(record.quality)


class TestC7AndInformationBoundaries(unittest.TestCase):
    def test_candidate_observation_has_no_regime_or_schedule_proxy(self) -> None:
        fixture = DeterministicRegimeFixture(seed=0, n_steps=20, switch_at=10)
        for _ in range(5):
            obs = fixture.observation()
            self.assertIsInstance(obs, CandidateObservation)
            raw = obs.model_dump(mode="json")
            for forbidden in (
                "true_regime",
                "regime",
                "hint",
                "step",
                "n_steps",
                "schedule",
            ):
                self.assertNotIn(forbidden, raw)
            fixture.submit_action("A")

    def test_candidate_feedback_has_no_true_regime(self) -> None:
        fixture = DeterministicRegimeFixture(seed=0, n_steps=20, switch_at=10)
        fixture.submit_action("A")
        feedback = fixture.feedback()
        self.assertIsNotNone(feedback)
        assert feedback is not None
        self.assertIsInstance(feedback, CandidateFeedback)
        raw = feedback.model_dump(mode="json")
        for forbidden in ("true_regime", "regime", "hint", "step", "schedule"):
            self.assertNotIn(forbidden, raw)

    def test_candidate_receives_only_c7_snapshot(self) -> None:
        controller = C7Controller(correction_id="c7-1", scope_id="s-1")
        snapshot = controller.snapshot
        self.assertIsInstance(snapshot, C7Snapshot)
        self.assertFalse(hasattr(snapshot, "halt"))

    def test_arm_stops_when_c7_halted(self) -> None:
        controller = C7Controller(correction_id="c7-1", scope_id="s-1")
        controller.halt("test")
        with tempfile.TemporaryDirectory() as tmpdir:
            store = W1MemoryStore(
                db_path=os.path.join(tmpdir, "w1.db"), linter=W1UpdateLinter()
            )
            scope = W1Scope(
                mandate_id="m-test",
                task_id="t-test",
                environment_id="env-test",
                episode_id="ep-1",
            )
            selector = W2StrategySelector(
                registry=_FakeOptionRegistry(
                    {
                        "A": ToolOption(
                            option_id="A", tool_id="tool-a", tool_version="1"
                        ),
                    }
                ),
                authorized_option_ids=("A",),
                w1_reader=W1CanonicalReader(store=store, scope=scope),
                w1_scope=scope,
            )
            arm = W1W2Arm(store=store, scope=scope, selector=selector)
            with self.assertRaises(RuntimeError):
                arm.act(CandidateObservation(observation_id="o-1"), controller.snapshot)

    def test_w1w2_arm_rejects_unbound_selector(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = W1MemoryStore(
                db_path=os.path.join(tmpdir, "w1.db"), linter=W1UpdateLinter()
            )
            scope = W1Scope(
                mandate_id="m-test",
                task_id="t-test",
                environment_id="env-test",
                episode_id="ep-1",
            )
            selector = W2StrategySelector(
                registry=_FakeOptionRegistry(
                    {"A": ToolOption(option_id="A", tool_id="tool-a", tool_version="1")}
                ),
                authorized_option_ids=("A",),
            )
            with self.assertRaises(ValueError):
                W1W2Arm(store=store, scope=scope, selector=selector)

    def test_c7_halt_restores_lks_and_performs_zero_subsequent_candidate_calls(
        self,
    ) -> None:
        class CountingArm(AdaptationArm):
            name = "attack-arm"

            def __init__(self) -> None:
                self.act_calls = 0
                self.update_calls = 0
                self.restore_calls = 0
                self.state: list[float] = []
                self.calls_after_restore = 0

            def act(self, observation, c7):
                if self.restore_calls:
                    self.calls_after_restore += 1
                self.act_calls += 1
                return "A"

            def update(self, feedback, c7):
                if self.restore_calls:
                    self.calls_after_restore += 1
                self.update_calls += 1
                self.state.append(feedback.reward)

            def capture(self):
                return tuple(self.state)

            def restore(self, snapshot):
                self.restore_calls += 1
                if not isinstance(snapshot, tuple):
                    raise AssertionError("expected tuple snapshot")
                self.state = list(snapshot)

        arm = CountingArm()
        record = _make_harness().characterize(
            "w1+w2", 0, 20, arm_factory=lambda _store, _scope, _selector: arm
        )
        self.assertEqual(record.c7_stops, 1)
        self.assertEqual(arm.restore_calls, 1)
        self.assertEqual(arm.calls_after_restore, 0)
        self.assertLess(arm.act_calls, 20)
        self.assertEqual(arm.state, [1.0] * len(arm.state))


class TestWaveBDurabilityAndMechanics(unittest.TestCase):
    def test_store_requires_db_path(self) -> None:
        with self.assertRaises(ValueError):
            W1MemoryStore(db_path="", linter=W1UpdateLinter())

    def test_w1_only_typed_state_changes_next_action_and_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "w1.db")
            scope = W1Scope(
                mandate_id="m-test",
                task_id="t-test",
                environment_id="env-test",
                episode_id="ep-1",
            )
            store = W1MemoryStore(db_path=path, linter=W1UpdateLinter())
            store.activate_scope(scope)
            arm = W1OnlyArm(store, scope, authorized_action_ids=("A", "B"))
            c7 = C7Controller("c7-1", scope.task_id).snapshot
            observation = CandidateObservation(observation_id="opaque")
            self.assertEqual(arm.act(observation, c7), "A")
            arm.update(
                CandidateFeedback(action="A", reward=0.0, source_event_digest="e-1"), c7
            )
            self.assertEqual(arm.act(observation, c7), "B")
            expected_digest = store.get_state(scope).digest()
            store.close()

            reopened = W1MemoryStore(db_path=path, linter=W1UpdateLinter())
            reopened.activate_scope(scope)
            restarted = W1OnlyArm(reopened, scope, authorized_action_ids=("A", "B"))
            self.assertEqual(reopened.get_state(scope).digest(), expected_digest)
            self.assertEqual(restarted.act(observation, c7), "B")
            reopened.close()

    def test_w1_rollback_restores_state_digest_and_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scope = W1Scope(
                mandate_id="m-test",
                task_id="t-test",
                environment_id="env-test",
                episode_id="ep-1",
            )
            store = W1MemoryStore(
                db_path=os.path.join(tmpdir, "w1.db"), linter=W1UpdateLinter()
            )
            store.activate_scope(scope)
            arm = W1OnlyArm(store, scope, authorized_action_ids=("A", "B"))
            c7 = C7Controller("c7-1", scope.task_id).snapshot
            observation = CandidateObservation(observation_id="opaque")
            arm.update(
                CandidateFeedback(action="A", reward=0.0, source_event_digest="e-1"), c7
            )
            checkpoint = arm.capture()
            before_digest = store.get_state(scope).digest()
            self.assertEqual(arm.act(observation, c7), "B")
            arm.update(
                CandidateFeedback(action="B", reward=0.0, source_event_digest="e-2"), c7
            )
            self.assertEqual(arm.act(observation, c7), "A")
            arm.restore(checkpoint)
            self.assertEqual(store.get_state(scope).digest(), before_digest)
            self.assertEqual(arm.act(observation, c7), "B")
            store.close()

    def test_w1w2_receipt_consumes_live_state_and_constant_reader_fails_gate(
        self,
    ) -> None:
        class ConstantReader:
            def __init__(self, delegate, scope):
                self._delegate = delegate
                self._constant = W1MemoryState(scope=scope, updates=(), epoch=0)

            def get_state(self, scope):
                del scope
                return self._constant

            def __getattr__(self, name):
                return getattr(self._delegate, name)

        with tempfile.TemporaryDirectory() as tmpdir:
            scope = W1Scope(
                mandate_id="m-test",
                task_id="t-test",
                environment_id="env-test",
                episode_id="ep-1",
            )
            registry = _FakeOptionRegistry(
                {
                    "A": ToolOption(option_id="A", tool_id="tool-a", tool_version="1"),
                    "B": ToolOption(option_id="B", tool_id="tool-b", tool_version="1"),
                }
            )
            store = W1MemoryStore(
                db_path=os.path.join(tmpdir, "live.db"), linter=W1UpdateLinter()
            )
            store.activate_scope(scope)
            selector = W2StrategySelector(
                registry=registry,
                authorized_option_ids=("A", "B"),
                w1_reader=W1CanonicalReader(store=store, scope=scope),
                w1_scope=scope,
            )
            arm = W1W2Arm(store=store, scope=scope, selector=selector)
            c7 = C7Controller("c7-1", scope.task_id).snapshot
            observation = CandidateObservation(observation_id="opaque")
            arm.act(observation, c7)
            arm.update(
                CandidateFeedback(action="A", reward=0.0, source_event_digest="e-1"), c7
            )
            self.assertEqual(arm.act(observation, c7), "B")
            self.assertEqual(
                arm.last_decision_receipt.consumed_w1_decision_state_digest,
                selector.canonical_decision_state(store.get_state(scope)).digest(),
            )
            self.assertTrue(arm.causal_consumption_verified())

            disconnected_store = W1MemoryStore(
                db_path=os.path.join(tmpdir, "constant.db"), linter=W1UpdateLinter()
            )
            disconnected_store.activate_scope(scope)
            with self.assertRaises(TypeError):
                W1CanonicalReader(
                    store=ConstantReader(disconnected_store, scope),  # type: ignore[arg-type]
                    scope=scope,
                )
            store.close()
            disconnected_store.close()

    def test_run_creates_isolated_db_per_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            harness = FalsifierHarness(
                run_authorization_resolver=_FakeRunAuthorizationResolver({}),
                option_registry=_FakeOptionRegistry(
                    {
                        "A": ToolOption(
                            option_id="A", tool_id="tool-a", tool_version="1"
                        ),
                        "B": ToolOption(
                            option_id="B", tool_id="tool-b", tool_version="1"
                        ),
                    }
                ),
                authorized_option_ids=("A", "B"),
                db_path=os.path.join(tmpdir, "w1w2.db"),
                switch_at=10,
                trusted_scorer=_FakeTrustedScorer(),
            )
            auth0 = _externally_issued_auth(harness, "ext-0", "frozen", 0, 10)
            auth1 = _externally_issued_auth(harness, "ext-1", "frozen", 1, 10)
            harness._run_authorization_resolver = _FakeRunAuthorizationResolver(
                {auth0.receipt_id: auth0, auth1.receipt_id: auth1}
            )
            harness.run("frozen", 0, 10, auth0.receipt_id)
            harness.run("frozen", 1, 10, auth1.receipt_id)
            dbs = [p for p in os.listdir(tmpdir) if p.endswith(".db")]
            self.assertEqual(
                len(dbs), 2
            )  # 2 isolated w1 dbs (checkpoint store integrated separately)

    def test_constant_selector_degrades_characterization(self) -> None:
        # Scheduled arm is the optimal single-switch baseline.
        scheduled = _make_harness().characterize(
            arm_name="scheduled", seed=0, n_steps=20, arm_factory=None
        )
        constant = _make_harness(
            selection_fn=lambda _opts, _ctx, _hist: "A"
        ).characterize(arm_name="w1+w2", seed=0, n_steps=20, arm_factory=None)
        self.assertIsNotNone(scheduled.quality)
        self.assertIsNotNone(constant.quality)
        assert scheduled.quality is not None
        assert constant.quality is not None
        # Constant bypass fails to adapt and earns strictly lower quality.
        self.assertLess(constant.quality, scheduled.quality)
        self.assertGreater(constant.negative_transfer_steps, 0)
        # With no recovery after the switch, the second regime is ignored.
        self.assertEqual(len(constant.recovery_speeds), 0)
        self.assertFalse(constant.falsifier_passed)

    def test_constant_b_also_cannot_pass_ab_a_falsifier(self) -> None:
        constant = _make_harness(
            switch_at=(5, 10), selection_fn=lambda _opts, _ctx, _hist: "B"
        ).characterize("w1+w2", 0, 20)
        self.assertFalse(constant.falsifier_passed)

    def test_hidden_callback_can_characterize_but_cannot_pass_candidate_gate(
        self,
    ) -> None:
        def hidden_callback(options, _context, history):
            if not history:
                return options[0]
            last = history[-1]
            if float(last["reward"]) > 0.0:
                return str(last["action"])
            return options[1] if last["action"] == options[0] else options[0]

        attacked = _make_harness(
            switch_at=(5, 10), selection_fn=hidden_callback
        ).characterize("w1+w2", 0, 20)
        self.assertEqual(attacked.status, "CHARACTERIZATION_ONLY")
        self.assertEqual(len(attacked.recovery_speeds), 2)
        self.assertFalse(attacked.w1_causal_consumption_verified)
        self.assertFalse(attacked.falsifier_passed)

    def test_ab_ba_records_recovery(self) -> None:
        harness = _make_harness(switch_at=(5, 10))
        record = harness.characterize(
            arm_name="w1+w2", seed=0, n_steps=20, arm_factory=None
        )
        self.assertEqual(record.status, "CHARACTERIZATION_ONLY")
        self.assertIsNotNone(record.speed)
        assert record.speed is not None
        # Both regime switches (A->B at 5, B->A at 10) must be recorded.
        self.assertLess(record.speed, record.n_steps)
        self.assertEqual(len(record.recovery_speeds), 2)
        self.assertLess(record.recovery_speeds[1], record.n_steps)
        self.assertTrue(record.w1_causal_consumption_verified)
        self.assertTrue(record.falsifier_passed)

    def test_c7_stop_invokes_rollback(self) -> None:
        harness = _make_harness()
        record = harness.characterize(
            arm_name="frozen", seed=0, n_steps=20, arm_factory=None
        )
        # The deliberately non-adaptive frozen arm must still trigger the
        # independent negative-transfer stop and rollback path.
        self.assertGreater(record.c7_stops, 0)
        self.assertGreater(record.rollback_latency_steps, 0)
        self.assertGreater(record.negative_transfer_steps, 0)

    def test_permission_violation_detects_unauthorized_option(self) -> None:
        harness = _make_harness(selection_fn=lambda _opts, _ctx, _hist: "C")
        record = harness.characterize(
            arm_name="w1+w2", seed=0, n_steps=20, arm_factory=None
        )
        self.assertEqual(record.status, "CHARACTERIZATION_ONLY")
        self.assertGreater(record.permission_violations, 0)


class TestAdmAllDefer(unittest.TestCase):
    def test_adm_all_defer_path_raises(self) -> None:
        with self.assertRaises(RuntimeError):
            FalsifierHarness.adm_all_defer_path()


if __name__ == "__main__":
    unittest.main()
