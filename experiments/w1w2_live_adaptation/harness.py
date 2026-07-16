"""Model-free W1/W2 live-adaptation falsifier harness.

The candidate sees only opaque observations, delayed action/outcome feedback and
an immutable C7 snapshot.  Regime, schedule, oracle reward and evaluator gates
remain on the fixture/scorer side.
"""

from __future__ import annotations

import os
import random
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from experiments.w1w2_live_adaptation._authority import (
    C7Controller,
    C7Snapshot,
    RunAuthorizationBinding,
    RunAuthorizationResolver,
)
from experiments.w1w2_live_adaptation._contracts import (
    CandidateFeedback,
    CandidateObservation,
    ContractModel,
    NonEmptyStr,
    content_digest,
)
from experiments.w1w2_live_adaptation.transfer_monitor import (
    ScorerReceipt,
    ScorerReceiptBinding,
    SealedScorerOutcome,
    TransferMonitor,
    TrustedScorerPort,
)
from experiments.w1w2_live_adaptation.w1_linter import W1UpdateLinter
from experiments.w1w2_live_adaptation.w1_state import (
    ActionValueEstimate,
    BeliefPayload,
    W1MemoryState,
    W1MemoryStore,
    W1Scope,
    W1Update,
    W1UpdateType,
)
from experiments.w1w2_live_adaptation.w2_selector import (
    SelectionFn,
    W2DecisionReceipt,
    W2OptionRegistry,
    W2StrategySelector,
)


class FalsifierRunRecord(ContractModel):
    run_id: NonEmptyStr
    arm_name: NonEmptyStr
    seed: int
    n_steps: int
    run_status: NonEmptyStr


class CharacterizationRecord(ContractModel):
    run_id: NonEmptyStr
    arm_name: NonEmptyStr
    seed: int
    n_steps: int
    status: NonEmptyStr
    speed: float | None
    quality: float | None
    risk: float | None
    negative_transfer_steps: int
    rollback_latency_steps: int
    c7_stops: int
    permission_violations: int
    recovery_speeds: tuple[float, ...] = ()
    phase_qualities: tuple[float, ...] = ()
    w1_causal_consumption_verified: bool = False
    falsifier_passed: bool = False


@dataclass(frozen=True)
class _ScoredOutcome:
    step: int
    action: str
    reward: float


class DeterministicRegimeFixture:
    """Sealed evaluator fixture with delayed feedback and hidden A/B/A shifts."""

    OPTIMAL = {"A": "A", "B": "B"}

    def __init__(
        self,
        seed: int,
        n_steps: int = 20,
        switch_at: int | tuple[int, ...] = 10,
        delay: int = 1,
    ) -> None:
        self._rng = random.Random(seed)
        self._n_steps = n_steps
        self._switch_points = (
            (switch_at,) if isinstance(switch_at, int) else tuple(sorted(switch_at))
        )
        self._delay = delay
        self._step = 0
        self._pending: list[tuple[int, int, str, float]] = []
        self._scored: list[_ScoredOutcome] = []

    def _regime_at(self, step: int) -> str:
        switches = sum(1 for point in self._switch_points if point <= step)
        return "A" if switches % 2 == 0 else "B"

    def observation(self) -> CandidateObservation:
        # Random opaque id prevents schedule/turn/regime fields from entering the contract.
        return CandidateObservation(
            observation_id=f"obs-{self._rng.getrandbits(128):032x}"
        )

    def submit_action(self, action: str) -> None:
        reward = 1.0 if action == self.OPTIMAL[self._regime_at(self._step)] else 0.0
        due_step = self._step + self._delay
        self._pending.append((due_step, self._step, action, reward))
        self._step += 1

    def feedback(self) -> CandidateFeedback | None:
        if not self._pending or self._pending[0][0] > self._step:
            return None
        _due, step, action, reward = self._pending.pop(0)
        scored = _ScoredOutcome(step=step, action=action, reward=reward)
        self._scored.append(scored)
        return CandidateFeedback(
            action=action,
            reward=reward,
            source_event_digest=content_digest(
                {
                    "fixture": "w1w2-delayed-feedback",
                    "step": step,
                    "action": action,
                    "reward": reward,
                }
            ),
        )

    def latest_scored(self) -> _ScoredOutcome | None:
        if not self._scored:
            return None
        return self._scored[-1]

    def flush(self) -> list[_ScoredOutcome]:
        outcomes: list[_ScoredOutcome] = []
        while self._pending:
            _due, step, action, reward = self._pending.pop(0)
            scored = _ScoredOutcome(step=step, action=action, reward=reward)
            self._scored.append(scored)
            outcomes.append(scored)
        return outcomes

    def sealed_outcome(self, scored: _ScoredOutcome) -> SealedScorerOutcome:
        regime = self._regime_at(scored.step)
        return SealedScorerOutcome(
            reward=scored.reward,
            baseline_reward=1.0 if self.OPTIMAL[regime] == "A" else 0.0,
            oracle_reward=1.0,
        )


class _CharacterizationScorer(TrustedScorerPort):
    """In-package scorer usable only by the explicitly non-evidence characterization API."""

    def __init__(self) -> None:
        self._receipts: dict[str, ScorerReceipt] = {}
        self._consumed: set[str] = set()

    def score(self, binding: ScorerReceiptBinding, outcome: SealedScorerOutcome) -> str:
        receipt_id = f"characterization-scorer-{uuid4().hex}"
        self._receipts[receipt_id] = ScorerReceipt(
            receipt_id=receipt_id, binding=binding, outcome=outcome
        )
        return receipt_id

    def consume(
        self, receipt_id: str, expected: ScorerReceiptBinding
    ) -> ScorerReceipt | None:
        receipt = self._receipts.get(receipt_id)
        if (
            receipt is None
            or receipt_id in self._consumed
            or receipt.binding != expected
        ):
            return None
        self._consumed.add(receipt_id)
        return receipt


@dataclass(frozen=True)
class _ArmSnapshot:
    joint_checkpoint_id: str | None


class AdaptationArm(ABC):
    name: str = ""

    @abstractmethod
    def act(self, observation: CandidateObservation, c7: C7Snapshot) -> str:
        raise NotImplementedError

    def update(self, feedback: CandidateFeedback, c7: C7Snapshot) -> None:
        del feedback, c7

    def capture(self) -> object:
        return _ArmSnapshot(joint_checkpoint_id=None)

    def restore(self, snapshot: object) -> None:
        del snapshot

    def causal_consumption_verified(self) -> bool:
        return False


class FrozenArm(AdaptationArm):
    name = "frozen"

    def __init__(self, action: str = "A") -> None:
        self._action = action

    def act(self, observation: CandidateObservation, c7: C7Snapshot) -> str:
        del observation
        if c7.halted:
            raise RuntimeError("C7 halted")
        return self._action


class ScheduledStaticArm(AdaptationArm):
    """Strong baseline receives evaluator schedule; never used as a candidate arm."""

    name = "scheduled"

    def __init__(self, switch_at: int, before: str = "A", after: str = "B") -> None:
        self._switch_at = switch_at
        self._before = before
        self._after = after
        self._calls = 0

    def act(self, observation: CandidateObservation, c7: C7Snapshot) -> str:
        del observation
        if c7.halted:
            raise RuntimeError("C7 halted")
        action = self._before if self._calls < self._switch_at else self._after
        self._calls += 1
        return action


def _action_values_from_state(state: W1MemoryState) -> dict[str, ActionValueEstimate]:
    for update in reversed(state.updates):
        if update.update_type == W1UpdateType.BELIEF and isinstance(
            update.payload, BeliefPayload
        ):
            return {item.action_id: item for item in update.payload.action_values}
    return {}


def _latest_belief(state: W1MemoryState) -> BeliefPayload | None:
    for update in reversed(state.updates):
        if update.update_type == W1UpdateType.BELIEF and isinstance(
            update.payload, BeliefPayload
        ):
            return update.payload
    return None


def _preferred_action(
    state: W1MemoryState,
    authorized_action_ids: tuple[str, ...],
) -> str:
    latest = _latest_belief(state)
    if (
        latest is not None
        and latest.last_observed_action_id in authorized_action_ids
        and latest.last_observed_reward is not None
    ):
        if latest.last_observed_reward > 0.0:
            return latest.last_observed_action_id
        return next(
            (
                action_id
                for action_id in authorized_action_ids
                if action_id != latest.last_observed_action_id
            ),
            latest.last_observed_action_id,
        )
    values = _action_values_from_state(state)
    for action_id in authorized_action_ids:
        if action_id not in values:
            return action_id
    return max(
        authorized_action_ids,
        key=lambda action_id: (
            values[action_id].last_reward,
            -authorized_action_ids.index(action_id),
        ),
    )


def _updated_action_values(
    state: W1MemoryState,
    feedback: CandidateFeedback,
    authorized_action_ids: tuple[str, ...],
) -> tuple[ActionValueEstimate, ...]:
    if feedback.action not in authorized_action_ids:
        raise ValueError(f"feedback action '{feedback.action}' is not authorized")
    previous = _action_values_from_state(state)
    updated: list[ActionValueEstimate] = []
    for action_id in authorized_action_ids:
        prior = previous.get(action_id)
        if action_id == feedback.action:
            updated.append(
                ActionValueEstimate(
                    action_id=action_id,
                    last_reward=feedback.reward,
                    observation_count=(prior.observation_count if prior else 0) + 1,
                )
            )
        elif prior is not None:
            updated.append(prior)
    return tuple(updated)


class W1OnlyArm(AdaptationArm):
    name = "w1-only"

    def __init__(
        self,
        store: W1MemoryStore,
        scope: W1Scope,
        authorized_action_ids: tuple[str, ...] = ("A", "B"),
    ) -> None:
        if not authorized_action_ids:
            raise ValueError("W1OnlyArm requires at least one authorized action")
        self._store = store
        self._scope = scope
        self._authorized_action_ids = tuple(authorized_action_ids)
        self._count = len(store.get_state(scope).updates)
        self._consumption_trace: list[tuple[str, str]] = []

    def act(self, observation: CandidateObservation, c7: C7Snapshot) -> str:
        del observation
        if c7.halted:
            raise RuntimeError("C7 halted")
        state = self._store.get_state(self._scope)
        action = _preferred_action(state, self._authorized_action_ids)
        self._consumption_trace.append((state.digest(), action))
        return action

    def update(self, feedback: CandidateFeedback, c7: C7Snapshot) -> None:
        if c7.halted:
            raise RuntimeError("C7 halted")
        self._count += 1
        state = self._store.get_state(self._scope)
        checkpoint_id = self._store.checkpoint()
        now = datetime.now(timezone.utc)
        self._store.apply(
            W1Update(
                update_id=f"u-w1-{self._count}",
                scope=self._scope,
                update_type=W1UpdateType.BELIEF,
                payload=BeliefPayload(
                    belief_statement="typed action-outcome state",
                    confidence=0.8,
                    action_values=_updated_action_values(
                        state, feedback, self._authorized_action_ids
                    ),
                    last_observed_action_id=feedback.action,
                    last_observed_reward=feedback.reward,
                ),
                provenance="typed_delayed_feedback",
                source_event_digest=feedback.source_event_digest,
                correction_epoch=c7.epoch,
                rollback_checkpoint_id=checkpoint_id,
                version="1",
                valid_time=now,
                transaction_time=now,
            )
        )

    def causal_consumption_verified(self) -> bool:
        return (
            len({digest for digest, _action in self._consumption_trace}) >= 2
            and len({action for _digest, action in self._consumption_trace}) >= 2
        )

    def capture(self) -> _ArmSnapshot:
        checkpoint = self._store.save_joint_checkpoint(self._scope, ())
        return _ArmSnapshot(checkpoint.checkpoint_id)

    def restore(self, snapshot: object) -> None:
        if not isinstance(snapshot, _ArmSnapshot):
            raise RuntimeError("invalid arm snapshot")
        if snapshot.joint_checkpoint_id is None:
            raise RuntimeError("missing W1 checkpoint")
        self._store.restore_joint_checkpoint(snapshot.joint_checkpoint_id, self._scope)


class W2OnlyArm(AdaptationArm):
    name = "w2-only"

    def __init__(
        self, store: W1MemoryStore, scope: W1Scope, selector: W2StrategySelector
    ) -> None:
        self._store = store
        self._scope = scope
        self._selector = selector
        self._history: list[CandidateFeedback] = []

    def act(self, observation: CandidateObservation, c7: C7Snapshot) -> str:
        if c7.halted:
            raise RuntimeError("C7 halted")
        receipt = self._selector.select(
            context=observation.model_dump(mode="json"),
            outcome_history=tuple(
                item.model_dump(mode="json") for item in self._history
            ),
        )
        return receipt.selected_option_id

    def update(self, feedback: CandidateFeedback, c7: C7Snapshot) -> None:
        if c7.halted:
            raise RuntimeError("C7 halted")
        self._history.append(feedback)

    def capture(self) -> _ArmSnapshot:
        checkpoint = self._store.save_joint_checkpoint(
            self._scope, tuple(self._history)
        )
        return _ArmSnapshot(checkpoint.checkpoint_id)

    def restore(self, snapshot: object) -> None:
        if not isinstance(snapshot, _ArmSnapshot):
            raise RuntimeError("invalid arm snapshot")
        if snapshot.joint_checkpoint_id is None:
            raise RuntimeError("missing joint checkpoint")
        self._history = list(
            self._store.restore_joint_checkpoint(
                snapshot.joint_checkpoint_id, self._scope
            )
        )


class W1W2Arm(W2OnlyArm):
    name = "w1+w2"

    def __init__(
        self, store: W1MemoryStore, scope: W1Scope, selector: W2StrategySelector
    ) -> None:
        super().__init__(store, scope, selector)
        self._count = len(store.get_state(scope).updates)
        self._consumption_trace: list[tuple[str, str]] = []
        self._last_decision_receipt: W2DecisionReceipt | None = None

    def act(self, observation: CandidateObservation, c7: C7Snapshot) -> str:
        if c7.halted:
            raise RuntimeError("C7 halted")
        state = self._store.get_state(self._scope)
        state_digest = state.digest()
        preference = _preferred_action(state, self._selector.authorized_option_ids)
        receipt = self._selector.select(
            context=observation.model_dump(mode="json"),
            outcome_history=tuple(
                item.model_dump(mode="json") for item in self._history
            ),
            consumed_w1_state_digest=state_digest,
            preferred_option_id=preference,
        )
        self._last_decision_receipt = receipt
        self._consumption_trace.append((state_digest, receipt.selected_option_id))
        return receipt.selected_option_id

    def update(self, feedback: CandidateFeedback, c7: C7Snapshot) -> None:
        super().update(feedback, c7)
        self._count += 1
        state = self._store.get_state(self._scope)
        checkpoint_id = self._store.checkpoint()
        now = datetime.now(timezone.utc)
        self._store.apply(
            W1Update(
                update_id=f"u-w1w2-{self._count}",
                scope=self._scope,
                update_type=W1UpdateType.BELIEF,
                payload=BeliefPayload(
                    belief_statement="typed action-outcome state",
                    confidence=0.8,
                    action_values=_updated_action_values(
                        state, feedback, self._selector.authorized_option_ids
                    ),
                    last_observed_action_id=feedback.action,
                    last_observed_reward=feedback.reward,
                ),
                provenance="typed_delayed_feedback",
                source_event_digest=feedback.source_event_digest,
                correction_epoch=c7.epoch,
                rollback_checkpoint_id=checkpoint_id,
                version="1",
                valid_time=now,
                transaction_time=now,
            )
        )

    @property
    def last_decision_receipt(self) -> W2DecisionReceipt:
        if self._last_decision_receipt is None:
            raise RuntimeError("no W2 decision has been made")
        return self._last_decision_receipt

    def causal_consumption_verified(self) -> bool:
        return (
            len({digest for digest, _action in self._consumption_trace}) >= 2
            and len({action for _digest, action in self._consumption_trace}) >= 2
        )

    def capture(self) -> _ArmSnapshot:
        checkpoint = self._store.save_joint_checkpoint(
            self._scope, tuple(self._history)
        )
        return _ArmSnapshot(checkpoint.checkpoint_id)

    def restore(self, snapshot: object) -> None:
        if not isinstance(snapshot, _ArmSnapshot):
            raise RuntimeError("invalid arm snapshot")
        if snapshot.joint_checkpoint_id is None:
            raise RuntimeError("missing W1 checkpoint")
        self._history = list(
            self._store.restore_joint_checkpoint(
                snapshot.joint_checkpoint_id, self._scope
            )
        )


ArmFactory = Callable[[W1MemoryStore, W1Scope, W2StrategySelector], AdaptationArm]


class FalsifierHarness:
    """Bounded characterization plus externally authorized result-run gate."""

    _EVALUATOR_GATE = {"regret_window": 5, "threshold": 4.0, "protocol": "A-B-A"}

    def __init__(
        self,
        run_authorization_resolver: RunAuthorizationResolver,
        option_registry: W2OptionRegistry,
        authorized_option_ids: tuple[str, ...],
        db_path: str | None = None,
        switch_at: int | tuple[int, ...] = 10,
        selection_fn: SelectionFn | None = None,
        trusted_scorer: TrustedScorerPort | None = None,
    ) -> None:
        self._run_authorization_resolver = run_authorization_resolver
        self._option_registry = option_registry
        self._authorized_option_ids = tuple(authorized_option_ids)
        self._db_path = db_path
        self._switch_at = switch_at
        self._selection_fn = selection_fn
        self._trusted_scorer = trusted_scorer

    def _make_scope(self, seed: int) -> W1Scope:
        return W1Scope(
            mandate_id="m-test",
            task_id="t-test",
            environment_id="env-test",
            episode_id=f"ep-{seed}",
        )

    def _make_selector(self) -> W2StrategySelector:
        return W2StrategySelector(
            registry=self._option_registry,
            authorized_option_ids=self._authorized_option_ids,
            selection_fn=self._selection_fn,
        )

    def expected_run_binding(
        self, arm_name: str, seed: int, n_steps: int
    ) -> RunAuthorizationBinding:
        selector = self._make_selector()
        option_digest = selector.authorized_set_digest()
        gate_digest = content_digest(self._EVALUATOR_GATE)
        experiment_digest = content_digest(
            {
                "protocol": "w1w2-live-adaptation-v0.2",
                "switch_at": self._switch_at,
                "delay": 1,
                "option_content_digest": option_digest,
                "evaluator_gate_digest": gate_digest,
            }
        )
        return RunAuthorizationBinding(
            scope=self._make_scope(seed),
            arm_name=arm_name,
            seed=seed,
            n_steps=n_steps,
            option_content_digest=option_digest,
            evaluator_gate_digest=gate_digest,
            experiment_content_digest=experiment_digest,
        )

    def _consume_authorization(
        self, receipt_id: str | None, arm_name: str, seed: int, n_steps: int
    ) -> bool:
        if not receipt_id:
            return False
        expected = self.expected_run_binding(arm_name, seed, n_steps)
        resolved = self._run_authorization_resolver.consume(receipt_id, expected)
        return bool(
            resolved is not None
            and resolved.receipt_id == receipt_id
            and resolved.binding == expected
            and resolved.is_current(datetime.now(timezone.utc))
        )

    def _make_monitor(
        self,
        run_id: str,
        scope: W1Scope,
        arm_name: str,
        scorer: TrustedScorerPort,
    ) -> TransferMonitor:
        selector = self._make_selector()
        return TransferMonitor(
            regret_window=int(self._EVALUATOR_GATE["regret_window"]),
            threshold=float(self._EVALUATOR_GATE["threshold"]),
            gate_digest=content_digest(
                {
                    **self._EVALUATOR_GATE,
                    "option_content_digest": selector.authorized_set_digest(),
                }
            ),
            run_id=run_id,
            scope=scope,
            arm_name=arm_name,
            scorer_resolver=scorer,
        )

    def _make_db_path(self, run_id: str) -> str:
        if self._db_path:
            base = os.path.dirname(self._db_path) or "."
            name = os.path.basename(self._db_path) or "w1w2.db"
            return os.path.join(base, f"{run_id}-{name}")
        return os.path.join(tempfile.gettempdir(), f"{run_id}-w1w2.db")

    def _make_arm(
        self,
        arm_name: str,
        store: W1MemoryStore,
        scope: W1Scope,
        selector: W2StrategySelector,
        arm_factory: ArmFactory | None,
    ) -> AdaptationArm:
        if arm_factory is not None:
            return arm_factory(store, scope, selector)
        if arm_name == "frozen":
            return FrozenArm("A")
        if arm_name == "scheduled":
            first = (
                self._switch_at
                if isinstance(self._switch_at, int)
                else min(self._switch_at)
            )
            return ScheduledStaticArm(first)
        if arm_name == "w1-only":
            return W1OnlyArm(store, scope)
        if arm_name == "w2-only":
            return W2OnlyArm(store, scope, selector)
        if arm_name == "w1+w2":
            return W1W2Arm(store, scope, selector)
        raise ValueError(f"unknown arm: {arm_name}")

    def _execute(
        self,
        arm_name: str,
        seed: int,
        n_steps: int,
        run_id: str,
        allow_run: bool,
        arm_factory: ArmFactory | None = None,
    ) -> CharacterizationRecord:
        scope = self._make_scope(seed)
        selector = self._make_selector()
        scorer = self._trusted_scorer if allow_run else _CharacterizationScorer()
        if scorer is None:
            raise RuntimeError("result run requires an external trusted scorer")
        monitor = self._make_monitor(run_id, scope, arm_name, scorer)
        db_path = self._make_db_path(run_id)
        linter = W1UpdateLinter(
            allowed_scopes={
                f"{scope.mandate_id}/{scope.task_id}/{scope.environment_id}/{scope.episode_id}"
            }
        )
        store = W1MemoryStore(db_path=db_path, linter=linter)
        store.activate_scope(scope)
        controller = C7Controller(f"c7-{run_id}", scope.task_id)
        fixture = DeterministicRegimeFixture(seed, n_steps, self._switch_at)
        arm = self._make_arm(arm_name, store, scope, selector, arm_factory)
        last_known_safe = arm.capture()

        outcomes: list[_ScoredOutcome] = []
        negative_transfer_steps = 0
        rollback_latency_steps = 0
        c7_stops = 0
        permission_violations = 0

        for _ in range(n_steps):
            if controller.snapshot.halted:
                break
            observation = fixture.observation()
            try:
                action = arm.act(observation, controller.snapshot)
            except ValueError as exc:
                if "authorized" in str(exc) or "authority registry" in str(exc):
                    permission_violations += 1
                    break
                raise
            fixture.submit_action(action)
            feedback = fixture.feedback()
            if feedback is None:
                continue
            arm.update(feedback, controller.snapshot)
            scored = fixture.latest_scored()
            if scored is None:
                continue
            outcomes.append(scored)
            binding = ScorerReceiptBinding(
                run_id=run_id,
                scope=scope,
                arm_name=arm_name,
                step=scored.step,
                gate_digest=monitor.gate_digest(),
            )
            receipt_id = scorer.score(binding, fixture.sealed_outcome(scored))
            assessment = monitor.assess(
                receipt_id,
                scored.step,
                current_checkpoint_id=None,
                authorized_option_ids=selector.authorized_option_ids,
            )
            if assessment.negative_transfer_detected:
                negative_transfer_steps += 1
                controller.halt(assessment.reason)
                c7_stops += 1
                arm.restore(last_known_safe)
                rollback_latency_steps += 1
                break
            if scored.reward > 0.5:
                last_known_safe = arm.capture()

        if not controller.snapshot.halted:
            outcomes.extend(fixture.flush())

        switch_points = (
            (self._switch_at,)
            if isinstance(self._switch_at, int)
            else tuple(sorted(self._switch_at))
        )
        bounds = (0, *switch_points, n_steps)
        phase_qualities: list[float] = []
        for start, end in zip(bounds, bounds[1:]):
            phase = [item.reward for item in outcomes if start <= item.step < end]
            phase_qualities.append(sum(phase) / len(phase) if phase else 0.0)
        recoveries: list[float] = []
        for index, switch in enumerate(switch_points):
            end = (
                switch_points[index + 1] if index + 1 < len(switch_points) else n_steps
            )
            recovered = next(
                (
                    item.step - switch
                    for item in outcomes
                    if switch <= item.step < end and item.reward > 0.5
                ),
                None,
            )
            if recovered is not None:
                recoveries.append(float(recovered))

        quality = sum(item.reward for item in outcomes) / max(len(outcomes), 1)
        adaptive_candidate = arm_name == "w1+w2" and arm_factory is None
        w1_causal_consumption = arm.causal_consumption_verified()
        falsifier_passed = bool(
            adaptive_candidate
            and w1_causal_consumption
            and len(switch_points) >= 2
            and len(recoveries) == len(switch_points)
            and len(phase_qualities) >= 3
            and all(value >= 0.5 for value in phase_qualities[:3])
            and c7_stops == 0
            and permission_violations == 0
        )
        store.close()
        return CharacterizationRecord(
            run_id=run_id,
            arm_name=arm_name,
            seed=seed,
            n_steps=n_steps,
            status="COMPLETED" if allow_run else "CHARACTERIZATION_ONLY",
            speed=recoveries[0] if recoveries else float(n_steps),
            quality=quality,
            risk=float(c7_stops + permission_violations),
            negative_transfer_steps=negative_transfer_steps,
            rollback_latency_steps=rollback_latency_steps,
            c7_stops=c7_stops,
            permission_violations=permission_violations,
            recovery_speeds=tuple(recoveries),
            phase_qualities=tuple(phase_qualities),
            w1_causal_consumption_verified=w1_causal_consumption,
            falsifier_passed=falsifier_passed,
        )

    def run(
        self,
        arm_name: str,
        seed: int,
        n_steps: int,
        authorization_receipt_id: str | None,
    ) -> FalsifierRunRecord:
        run_id = f"run-{uuid4().hex}"
        if self._selection_fn is not None or self._trusted_scorer is None:
            return FalsifierRunRecord(
                run_id=run_id,
                arm_name=arm_name,
                seed=seed,
                n_steps=n_steps,
                run_status="RUN_DENIED",
            )
        if not self._consume_authorization(
            authorization_receipt_id, arm_name, seed, n_steps
        ):
            return FalsifierRunRecord(
                run_id=run_id,
                arm_name=arm_name,
                seed=seed,
                n_steps=n_steps,
                run_status="RUN_DENIED",
            )
        record = self._execute(arm_name, seed, n_steps, run_id, allow_run=True)
        return FalsifierRunRecord(
            run_id=record.run_id,
            arm_name=record.arm_name,
            seed=record.seed,
            n_steps=record.n_steps,
            run_status="COMPLETED",
        )

    def characterize(
        self,
        arm_name: str,
        seed: int,
        n_steps: int,
        arm_factory: ArmFactory | None = None,
    ) -> CharacterizationRecord:
        return self._execute(
            arm_name,
            seed,
            n_steps,
            f"char-{uuid4().hex}",
            allow_run=False,
            arm_factory=arm_factory,
        )

    @staticmethod
    def adm_all_defer_path() -> None:
        raise RuntimeError("ADM all-DEFER path is disabled for W1/W2 falsifier")
