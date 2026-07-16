"""Interactive turn-based episode environment for R-STATE-CREDIT-1 Phase 1.

The environment is deterministic, reversible, and materializable in a temporary
directory.  No provider calls, model inference, or external side effects occur.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import random
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from experiments.r_state_credit_1.contracts import ProbeAction
from experiments.r_state_credit_1.observation import Observation, _canonical_json


BASE_TIME = datetime(2026, 7, 15, 10, 0, tzinfo=timezone.utc)
T_MIN = 20
T_MAX = 60
O_MAX = 8_192
B_A0 = 262_144
B_ARM = 65_536


class PerturbationClass(str, Enum):
    """Perturbation classes supported by the architecture."""

    ALIAS_REBIND = "ALIAS_REBIND"
    OBJECT_VERSION_CHANGE = "OBJECT_VERSION_CHANGE"
    PROCESS_RESTART = "PROCESS_RESTART"
    OUT_OF_ORDER_TRANSACTION = "OUT_OF_ORDER_TRANSACTION"
    HALF_OPEN_VALID_TIME_BOUNDARY = "HALF_OPEN_VALID_TIME_BOUNDARY"
    SIMULTANEOUS_CONFLICTING_EVIDENCE = "SIMULTANEOUS_CONFLICTING_EVIDENCE"
    DELAYED_DEPENDENT_ACTION = "DELAYED_DEPENDENT_ACTION"
    ASSERTION_SUPERSESSION = "ASSERTION_SUPERSESSION"
    LATE_REFUTATION = "LATE_REFUTATION"
    TRANSITIVE_INVALIDATION = "TRANSITIVE_INVALIDATION"
    PENDING_COMMITMENT = "PENDING_COMMITMENT"
    PRECONDITION_REFUTATION = "PRECONDITION_REFUTATION"
    ACTION_DISPATCH = "ACTION_DISPATCH"
    RECEIPT_LOSS = "RECEIPT_LOSS"
    INTERRUPTION_BEFORE_EFFECT_VERIFICATION = "INTERRUPTION_BEFORE_EFFECT_VERIFICATION"
    REPRESENTATION_PRESSURE = "REPRESENTATION_PRESSURE"
    PROTECTED_STATE_AT_BOUND = "PROTECTED_STATE_AT_BOUND"
    DETERMINISTIC_RECOVERY = "DETERMINISTIC_RECOVERY"


class EpisodeStatus(str, Enum):
    RUNNING = "RUNNING"
    TERMINAL = "TERMINAL"
    ABSTAINED = "ABSTAINED"
    OVERFLOW = "OVERFLOW"


@dataclass
class EpisodeState:
    """Mutable in-memory state for one episode."""

    files: dict[str, str]
    aliases: dict[str, str]
    entities: dict[str, str]
    assertions: list[dict[str, Any]]
    commitments: list[dict[str, Any]]
    dispatched_actions: dict[str, dict[str, Any]]
    process_epoch: int = 1
    pending_effect: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class EpisodeEvent:
    """An observable event recorded inside the episode loop."""

    turn_index: int
    event_id: str
    event_class: str
    subject_ref: str
    payload: dict[str, Any]
    valid_time: datetime
    observed_at_turn: int


class InvalidEpisode(RuntimeError):
    """Raised when an episode cannot be constructed deterministically."""


class ObservationSizeExceeded(InvalidEpisode):
    """Raised when a single observation exceeds O_max."""


class EpisodeOverflow(InvalidEpisode):
    """Raised when a cumulative budget is exceeded."""


EpisodePolicy = Callable[[Observation, "InteractiveEpisode"], ProbeAction]


def _episode_seed(family_id: str, seed_id: int) -> bytes:
    """Derive a 32-byte deterministic episode seed."""
    return hashlib.sha256(
        _canonical_json({"family_id": family_id, "seed_id": seed_id}).encode("utf-8")
    ).digest()


def _chain(seed: bytes, index: int) -> bytes:
    """Deterministic SHA-256 chain starting from seed."""
    value = seed
    for _ in range(index):
        value = hashlib.sha256(value).digest()
    return value


class InteractiveEpisode:
    """A deterministic, reversible, turn-based interactive episode."""

    def __init__(
        self,
        family_id: str,
        seed_id: int,
        temp_root: Path | None = None,
        *,
        o_max: int = O_MAX,
        b_a0: int = B_A0,
        b_arm: int = B_ARM,
    ) -> None:
        if not isinstance(family_id, str) or not family_id:
            raise ValueError("family_id must be non-empty text")
        if not isinstance(seed_id, int) or isinstance(seed_id, bool) or seed_id < 0:
            raise ValueError("seed_id must be a non-negative integer")
        self.family_id = family_id
        self.seed_id = seed_id
        self.o_max = o_max
        self.b_a0 = b_a0
        self.b_arm = b_arm
        self._episode_seed = _episode_seed(family_id, seed_id)
        self._rng = random.Random(self._episode_seed)
        self.T = self._sample_T()
        self._state = self._build_initial_state()
        self._turn_index = 0
        self._observations: list[Observation] = []
        self._events: list[EpisodeEvent] = []
        self._perturbation_schedule = self._schedule_perturbations()
        self._checkpoints = self._select_checkpoint_turns()
        self._status = EpisodeStatus.RUNNING
        self._a0_overflow = False
        self._arm_overflow = False
        self._current_perturbation: PerturbationClass | None = None
        self._owned_temp = temp_root is None
        self._temp_root = temp_root or Path(tempfile.mkdtemp(prefix="rsc1-episode-"))
        self._materialize_initial_tree()

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    def _sample_T(self) -> int:
        """Sample episode length from the frozen [20, 60] distribution."""
        value = int.from_bytes(self._episode_seed[:4], "big")
        return T_MIN + (value % (T_MAX - T_MIN + 1))

    def _build_initial_state(self) -> EpisodeState:
        """Build a seed-specific initial state."""
        entity_count = 2 + (self._episode_seed[0] % 7)  # 2 .. 8
        entities = {f"entity-{index:02d}": "v1" for index in range(entity_count)}
        topologies = ("chain", "star", "disconnected")
        topology = topologies[self._episode_seed[1] % len(topologies)]
        aliases = self._build_aliases(entity_count, topology)
        # No identifying metadata is written to the materialized temp tree;
        # family/seed remain runner-internal in-memory state only.
        return EpisodeState(
            files={},
            aliases=aliases,
            entities=entities,
            assertions=[],
            commitments=[],
            dispatched_actions={},
        )

    def _build_aliases(self, entity_count: int, topology: str) -> dict[str, str]:
        """Build a seed-specific alias graph topology."""
        aliases: dict[str, str] = {}
        if topology == "chain" and entity_count > 1:
            for index in range(entity_count - 1):
                aliases[f"alias-{index:02d}"] = f"entity-{index:02d}"
            aliases["alias-bounded"] = f"entity-{(entity_count - 1):02d}"
        elif topology == "star" and entity_count > 1:
            center = "entity-00"
            for index in range(1, entity_count):
                aliases[f"alias-{index:02d}"] = center
        # disconnected: empty alias map
        return aliases

    def _schedule_perturbations(self) -> list[tuple[int, PerturbationClass, int]]:
        """Produce a deterministic perturbation schedule from the seed."""
        implemented: tuple[PerturbationClass, ...] = (
            PerturbationClass.ALIAS_REBIND,
            PerturbationClass.OBJECT_VERSION_CHANGE,
            PerturbationClass.PROCESS_RESTART,
            PerturbationClass.OUT_OF_ORDER_TRANSACTION,
            PerturbationClass.HALF_OPEN_VALID_TIME_BOUNDARY,
            PerturbationClass.SIMULTANEOUS_CONFLICTING_EVIDENCE,
            PerturbationClass.ACTION_DISPATCH,
            PerturbationClass.DETERMINISTIC_RECOVERY,
            PerturbationClass.PENDING_COMMITMENT,
            PerturbationClass.PRECONDITION_REFUTATION,
            PerturbationClass.DELAYED_DEPENDENT_ACTION,
            PerturbationClass.ASSERTION_SUPERSESSION,
            PerturbationClass.LATE_REFUTATION,
            PerturbationClass.TRANSITIVE_INVALIDATION,
            PerturbationClass.RECEIPT_LOSS,
            PerturbationClass.INTERRUPTION_BEFORE_EFFECT_VERIFICATION,
            PerturbationClass.REPRESENTATION_PRESSURE,
            PerturbationClass.PROTECTED_STATE_AT_BOUND,
        )
        low, high = 5, self.T - 2
        span = high - low
        max_count = min(len(implemented), (span // 3) + 1)
        count = max(4, min(6, max_count))
        if count < 4:
            raise InvalidEpisode("episode too short for four checkpoints")
        step = span // (count - 1) if count > 1 else 0
        terminal_turns = [low + step * i for i in range(count)]
        rng = random.Random(self._episode_seed)
        classes = rng.sample(list(implemented), count)
        schedule: list[tuple[int, PerturbationClass, int]] = []
        used_triggers: set[int] = set()
        for cls, terminal in zip(classes, terminal_turns):
            offset = self._terminal_offset(cls)
            trigger = max(2, terminal - offset)
            # Co-occurring classes each release their own observation; shift a
            # colliding trigger to the nearest earlier free turn so it stays
            # at or before its terminal phase turn.
            while trigger in used_triggers and trigger > 2:
                trigger -= 1
            used_triggers.add(trigger)
            schedule.append((trigger, cls, terminal))
        return sorted(schedule)

    def _terminal_offset(self, cls: PerturbationClass) -> int:
        """Turns from trigger to terminal phase for a perturbation class."""
        if cls in {
            PerturbationClass.OUT_OF_ORDER_TRANSACTION,
            PerturbationClass.SIMULTANEOUS_CONFLICTING_EVIDENCE,
            PerturbationClass.DETERMINISTIC_RECOVERY,
            PerturbationClass.PRECONDITION_REFUTATION,
            PerturbationClass.DELAYED_DEPENDENT_ACTION,
            PerturbationClass.LATE_REFUTATION,
            PerturbationClass.TRANSITIVE_INVALIDATION,
            PerturbationClass.RECEIPT_LOSS,
            PerturbationClass.INTERRUPTION_BEFORE_EFFECT_VERIFICATION,
            PerturbationClass.REPRESENTATION_PRESSURE,
            PerturbationClass.PROTECTED_STATE_AT_BOUND,
        }:
            return 0
        if cls is PerturbationClass.ACTION_DISPATCH:
            return 2
        if cls is PerturbationClass.PENDING_COMMITMENT:
            return 3
        return 1

    def _terminal_turn(self, cls: PerturbationClass, trigger_turn: int) -> int:
        """Compute the terminal-phase turn for a perturbation class."""
        return trigger_turn + self._terminal_offset(cls)

    def _select_checkpoint_turns(self) -> list[int]:
        """Select exactly four checkpoint turns with minimum 3-turn spacing.

        The perturbation schedule provides a set of eligible terminal-phase
        turns.  From that set we enumerate every 4-element combination whose
        consecutive turns are at least three turns apart, then choose one
        combination deterministically from the episode seed.  This guarantees
        the spacing invariant whenever any valid combination exists and makes
        the algorithm a direct mechanical match for the frozen amendment.
        """
        eligible_terminal_turns = sorted(
            {terminal for _, _, terminal in self._perturbation_schedule}
        )
        eligible_terminal_turns = [
            turn
            for turn in eligible_terminal_turns
            if 5 <= turn <= self.T - 2
        ]
        if len(eligible_terminal_turns) < 4:
            raise InvalidEpisode("insufficient terminal phases for four checkpoints")

        valid_combinations = [
            combo
            for combo in itertools.combinations(eligible_terminal_turns, 4)
            if all(right - left >= 3 for left, right in zip(combo, combo[1:]))
        ]
        if not valid_combinations:
            raise InvalidEpisode("cannot space four checkpoints")

        digest = hashlib.sha256(b"checkpoint-v1\x00" + self._episode_seed).digest()
        rng = random.Random(digest)
        selected = valid_combinations[rng.randrange(len(valid_combinations))]
        return list(selected)

    # ------------------------------------------------------------------
    # Materialization
    # ------------------------------------------------------------------

    def _materialize_initial_tree(self) -> None:
        """Write the seed-specific initial tree into the temp directory."""
        self._temp_root.mkdir(parents=True, exist_ok=True)
        for relative_path, content in self._state.files.items():
            self._write_file(relative_path, content)
        for entity, version in self._state.entities.items():
            self._write_file(
                f"entities/{entity}.json",
                json.dumps({"entity": entity, "version": version}),
            )
        self._write_file("aliases.json", json.dumps(self._state.aliases, sort_keys=True))

    def _write_file(self, relative_path: str, content: str) -> None:
        path = self._temp_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _materialize_state(self) -> None:
        """Rewrite the temp directory to reflect current observable state."""
        # Family, seed, and turn remain runner-internal; only observable entity
        # and alias state is materialized.
        for entity, version in self._state.entities.items():
            self._write_file(
                f"entities/{entity}.json",
                json.dumps({"entity": entity, "version": version}, sort_keys=True),
            )
        self._write_file("aliases.json", json.dumps(self._state.aliases, sort_keys=True))

    # ------------------------------------------------------------------
    # Turn loop
    # ------------------------------------------------------------------

    def observe(self) -> tuple[Observation, ProbeAction | None]:
        """Release the next observation and an optional forced action.

        A0 overflow is tracked via ``a0_overflow`` but does not force the
        shared step action, so non-A0 arms can continue.  Non-A0 arm overflow
        forces the shared step action to ``ABSTAIN``.
        """
        if self._status is not EpisodeStatus.RUNNING:
            raise RuntimeError(f"episode is not running: {self._status.value}")
        self._turn_index += 1
        observation = self._generate_observation(self._turn_index)
        if observation.serialized_bytes() > self.o_max:
            self._status = EpisodeStatus.OVERFLOW
            raise ObservationSizeExceeded(
                f"observation size {observation.serialized_bytes()} "
                f"exceeds O_max={self.o_max} at turn {self._turn_index}"
            )
        cumulative = self._cumulative_a0_bytes(observation)
        forced: ProbeAction | None = None
        if cumulative > self.b_a0:
            self._a0_overflow = True
        if cumulative > self.b_arm:
            self._arm_overflow = True
            forced = ProbeAction.ABSTAIN
        self._observations.append(observation)
        return observation, forced

    def step(self, action: ProbeAction) -> EpisodeEvent:
        """Resolve the actor action, update state, and record the event."""
        if not self._observations or self._observations[-1].turn_index != self._turn_index:
            raise RuntimeError("observe() must be called before step()")
        observation = self._observations[-1]
        event = self._resolve_action(action, observation)
        self._events.append(event)
        self._update_terminal_status(action)
        return event

    def run(
        self,
        actor_policy: EpisodePolicy | None = None,
    ) -> tuple[list[Observation], list[EpisodeEvent]]:
        """Run the full episode using ``actor_policy`` or the default policy."""
        policy = actor_policy or self._default_policy
        while self._status is EpisodeStatus.RUNNING:
            observation, forced = self.observe()
            action = forced if forced is not None else policy(observation, self)
            self.step(action)
        return self._observations, self._events

    def _default_policy(self, observation: Observation, episode: InteractiveEpisode) -> ProbeAction:
        """Deterministic default policy used for reversibility tests."""
        _ = episode
        review_classes = {
            PerturbationClass.ALIAS_REBIND.value,
            PerturbationClass.OBJECT_VERSION_CHANGE.value,
            PerturbationClass.SIMULTANEOUS_CONFLICTING_EVIDENCE.value,
            PerturbationClass.PRECONDITION_REFUTATION.value,
            PerturbationClass.OUT_OF_ORDER_TRANSACTION.value,
            PerturbationClass.DELAYED_DEPENDENT_ACTION.value,
            PerturbationClass.ASSERTION_SUPERSESSION.value,
            PerturbationClass.LATE_REFUTATION.value,
            PerturbationClass.TRANSITIVE_INVALIDATION.value,
        }
        verify_classes = {
            PerturbationClass.PROCESS_RESTART.value,
            PerturbationClass.ACTION_DISPATCH.value,
            PerturbationClass.DETERMINISTIC_RECOVERY.value,
            PerturbationClass.RECEIPT_LOSS.value,
            PerturbationClass.INTERRUPTION_BEFORE_EFFECT_VERIFICATION.value,
        }
        if observation.event_class in review_classes:
            return ProbeAction.REVIEW
        if observation.event_class in verify_classes:
            return ProbeAction.VERIFY_EFFECT
        if observation.event_class == PerturbationClass.REPRESENTATION_PRESSURE.value:
            return ProbeAction.ABSTAIN
        return ProbeAction.CONTINUE

    def _generate_observation(self, turn: int) -> Observation:
        """Generate the observation for ``turn``."""
        self._current_perturbation = None
        for pturn, pcls, _ in self._perturbation_schedule:
            if pturn == turn:
                self._current_perturbation = pcls
                return self._perturbation_observation(pcls, turn)
        return self._normal_observation(turn)

    def _normal_observation(self, turn: int) -> Observation:
        """Generate a routine progression observation."""
        entity_keys = sorted(self._state.entities.keys())
        entity = entity_keys[(turn - 1) % max(1, len(entity_keys))]
        return Observation(
            turn_index=turn,
            event_class="ENTITY_OBSERVED",
            payload={
                "entity": entity,
                "object_version": self._state.entities[entity],
                "process_epoch": self._state.process_epoch,
            },
            valid_time=BASE_TIME + timedelta(minutes=turn),
            observed_at_turn=turn,
        )

    def _perturbation_observation(
        self, pcls: PerturbationClass, turn: int
    ) -> Observation:
        """Generate an observation for a scheduled perturbation."""
        if pcls is PerturbationClass.ALIAS_REBIND:
            return self._alias_rebind_observation(turn)
        if pcls is PerturbationClass.OBJECT_VERSION_CHANGE:
            return self._object_version_change_observation(turn)
        if pcls is PerturbationClass.PROCESS_RESTART:
            return self._process_restart_observation(turn)
        if pcls is PerturbationClass.OUT_OF_ORDER_TRANSACTION:
            return self._out_of_order_transaction_observation(turn)
        if pcls is PerturbationClass.HALF_OPEN_VALID_TIME_BOUNDARY:
            return self._half_open_boundary_observation(turn)
        if pcls is PerturbationClass.SIMULTANEOUS_CONFLICTING_EVIDENCE:
            return self._simultaneous_conflict_observation(turn)
        if pcls is PerturbationClass.ACTION_DISPATCH:
            return self._action_dispatch_observation(turn)
        if pcls is PerturbationClass.DETERMINISTIC_RECOVERY:
            return self._deterministic_recovery_observation(turn)
        if pcls is PerturbationClass.PENDING_COMMITMENT:
            return self._pending_commitment_observation(turn)
        if pcls is PerturbationClass.PRECONDITION_REFUTATION:
            return self._precondition_refutation_observation(turn)
        if pcls is PerturbationClass.DELAYED_DEPENDENT_ACTION:
            return self._delayed_dependent_action_observation(turn)
        if pcls is PerturbationClass.ASSERTION_SUPERSESSION:
            return self._assertion_supersession_observation(turn)
        if pcls is PerturbationClass.LATE_REFUTATION:
            return self._late_refutation_observation(turn)
        if pcls is PerturbationClass.TRANSITIVE_INVALIDATION:
            return self._transitive_invalidation_observation(turn)
        if pcls is PerturbationClass.RECEIPT_LOSS:
            return self._receipt_loss_observation(turn)
        if pcls is PerturbationClass.INTERRUPTION_BEFORE_EFFECT_VERIFICATION:
            return self._interruption_before_effect_verification_observation(turn)
        if pcls is PerturbationClass.REPRESENTATION_PRESSURE:
            return self._representation_pressure_observation(turn)
        if pcls is PerturbationClass.PROTECTED_STATE_AT_BOUND:
            return self._protected_state_at_bound_observation(turn)
        # Dispatch is exhaustive over the frozen PerturbationClass enum.

    # ------------------------------------------------------------------
    # Perturbation observations
    # ------------------------------------------------------------------

    def _alias_rebind_observation(self, turn: int) -> Observation:
        entity_keys = sorted(self._state.entities.keys())
        if len(entity_keys) < 2:
            target = entity_keys[0] if entity_keys else "entity-00"
            new_ref = target
        else:
            target = entity_keys[turn % len(entity_keys)]
            new_ref = entity_keys[(turn + 1) % len(entity_keys)]
        alias = f"alias-{turn % 8:02d}"
        return Observation(
            turn_index=turn,
            event_class=PerturbationClass.ALIAS_REBIND.value,
            payload={
                "alias": alias,
                "new_ref": new_ref,
                "old_ref": self._state.aliases.get(alias, target),
            },
            valid_time=BASE_TIME + timedelta(minutes=turn),
            observed_at_turn=turn,
        )

    def _object_version_change_observation(self, turn: int) -> Observation:
        entity_keys = sorted(self._state.entities.keys())
        entity = entity_keys[turn % max(1, len(entity_keys))]
        return Observation(
            turn_index=turn,
            event_class=PerturbationClass.OBJECT_VERSION_CHANGE.value,
            payload={
                "entity": entity,
                "new_version": "v2",
                "old_version": self._state.entities.get(entity, "v1"),
            },
            valid_time=BASE_TIME + timedelta(minutes=turn),
            observed_at_turn=turn,
        )

    def _process_restart_observation(self, turn: int) -> Observation:
        return Observation(
            turn_index=turn,
            event_class=PerturbationClass.PROCESS_RESTART.value,
            payload={
                "new_epoch": self._state.process_epoch + 1,
                "old_epoch": self._state.process_epoch,
                "pending_effects_cleared": self._state.pending_effect is not None,
            },
            valid_time=BASE_TIME + timedelta(minutes=turn),
            observed_at_turn=turn,
        )

    def _out_of_order_transaction_observation(self, turn: int) -> Observation:
        return Observation(
            turn_index=turn,
            event_class=PerturbationClass.OUT_OF_ORDER_TRANSACTION.value,
            payload={
                "assertion_id": f"assertion-{turn:03d}",
                "predicate": "release_window",
                "value": "closed",
                "valid_time_iso": (
                    BASE_TIME - timedelta(days=1) + timedelta(minutes=turn)
                ).isoformat(),
            },
            valid_time=BASE_TIME - timedelta(days=1) + timedelta(minutes=turn),
            observed_at_turn=turn,
        )

    def _half_open_boundary_observation(self, turn: int) -> Observation:
        return Observation(
            turn_index=turn,
            event_class=PerturbationClass.HALF_OPEN_VALID_TIME_BOUNDARY.value,
            payload={
                "assertion_id": f"assertion-{turn:03d}",
                "boundary": "start",
                "predicate": "release_window",
                "value": "open",
            },
            valid_time=BASE_TIME + timedelta(minutes=turn),
            observed_at_turn=turn,
        )

    def _simultaneous_conflict_observation(self, turn: int) -> Observation:
        return Observation(
            turn_index=turn,
            event_class=PerturbationClass.SIMULTANEOUS_CONFLICTING_EVIDENCE.value,
            payload={
                "assertions": [
                    {
                        "assertion_id": f"assertion-{turn:03d}-a",
                        "predicate": "active_schema",
                        "value": "schema-v1",
                    },
                    {
                        "assertion_id": f"assertion-{turn:03d}-b",
                        "predicate": "active_schema",
                        "value": "schema-v2",
                    },
                ],
                "overlap": True,
            },
            valid_time=BASE_TIME + timedelta(minutes=turn),
            observed_at_turn=turn,
        )

    def _action_dispatch_observation(self, turn: int) -> Observation:
        action_ref = f"action-{turn:03d}"
        return Observation(
            turn_index=turn,
            event_class=PerturbationClass.ACTION_DISPATCH.value,
            payload={
                "action_ref": action_ref,
                "expected_receipt_turn": turn + 2,
                "value": "effect initiated",
            },
            valid_time=BASE_TIME + timedelta(minutes=turn),
            observed_at_turn=turn,
        )

    def _deterministic_recovery_observation(self, turn: int) -> Observation:
        return Observation(
            turn_index=turn,
            event_class=PerturbationClass.DETERMINISTIC_RECOVERY.value,
            payload={
                "recovery_ref": f"recovery-{turn:03d}",
                "recovery_action": "ROLLBACK",
                "snapshot_digest": self._state_digest(),
            },
            valid_time=BASE_TIME + timedelta(minutes=turn),
            observed_at_turn=turn,
        )

    def _pending_commitment_observation(self, turn: int) -> Observation:
        return Observation(
            turn_index=turn,
            event_class=PerturbationClass.PENDING_COMMITMENT.value,
            payload={
                "commitment_ref": f"commitment-{turn:03d}",
                "preconditions": [f"precondition-{turn:03d}"],
                "value": "ship only after preconditions hold",
            },
            valid_time=BASE_TIME + timedelta(minutes=turn),
            observed_at_turn=turn,
        )

    def _precondition_refutation_observation(self, turn: int) -> Observation:
        return Observation(
            turn_index=turn,
            event_class=PerturbationClass.PRECONDITION_REFUTATION.value,
            payload={
                "commitment_ref": f"commitment-{turn - 1:03d}",
                "precondition": f"precondition-{turn - 1:03d}",
            },
            valid_time=BASE_TIME + timedelta(minutes=turn),
            observed_at_turn=turn,
        )

    def _delayed_dependent_action_observation(self, turn: int) -> Observation:
        return Observation(
            turn_index=turn,
            event_class=PerturbationClass.DELAYED_DEPENDENT_ACTION.value,
            payload={
                "action_ref": f"action-{turn:03d}",
                "precondition": f"precondition-{turn:03d}",
                "dispatch_turn": turn - 3,
                "precondition_refuted": True,
            },
            valid_time=BASE_TIME + timedelta(minutes=turn),
            observed_at_turn=turn,
        )

    def _assertion_supersession_observation(self, turn: int) -> Observation:
        return Observation(
            turn_index=turn,
            event_class=PerturbationClass.ASSERTION_SUPERSESSION.value,
            payload={
                "assertion_id": f"assertion-{turn:03d}",
                "supersedes": f"assertion-{turn - 3:03d}",
                "predicate": "active_schema",
                "value": f"schema-v{2 + turn % 2}",
                "dependent_assertion_id": f"assertion-{turn:03d}-dep",
            },
            valid_time=BASE_TIME + timedelta(minutes=turn),
            observed_at_turn=turn,
        )

    def _late_refutation_observation(self, turn: int) -> Observation:
        return Observation(
            turn_index=turn,
            event_class=PerturbationClass.LATE_REFUTATION.value,
            payload={
                "refutation_id": f"refutation-{turn:03d}",
                "refuted_assertion_id": f"assertion-{turn - 3:03d}",
                "dependent_assertion_ids": [
                    f"assertion-{turn:03d}-dep-a",
                    f"assertion-{turn:03d}-dep-b",
                ],
            },
            valid_time=BASE_TIME + timedelta(minutes=turn),
            observed_at_turn=turn,
        )

    def _transitive_invalidation_observation(self, turn: int) -> Observation:
        return Observation(
            turn_index=turn,
            event_class=PerturbationClass.TRANSITIVE_INVALIDATION.value,
            payload={
                "chain": [
                    f"assertion-{turn:03d}-c0",
                    f"assertion-{turn:03d}-c1",
                    f"assertion-{turn:03d}-c2",
                ],
                "root_cause": f"refutation-{turn:03d}",
                "invalidated": True,
            },
            valid_time=BASE_TIME + timedelta(minutes=turn),
            observed_at_turn=turn,
        )

    def _receipt_loss_observation(self, turn: int) -> Observation:
        return Observation(
            turn_index=turn,
            event_class=PerturbationClass.RECEIPT_LOSS.value,
            payload={
                "action_ref": f"action-{turn:03d}",
                "expected_receipt_turn": turn - 1,
                "receipt_received": False,
            },
            valid_time=BASE_TIME + timedelta(minutes=turn),
            observed_at_turn=turn,
        )

    def _interruption_before_effect_verification_observation(
        self, turn: int
    ) -> Observation:
        return Observation(
            turn_index=turn,
            event_class=PerturbationClass.INTERRUPTION_BEFORE_EFFECT_VERIFICATION.value,
            payload={
                "action_ref": f"action-{turn:03d}",
                "interrupted_epoch": self._state.process_epoch,
                "new_epoch": self._state.process_epoch + 1,
                "retry_record": f"retry-{turn:03d}",
            },
            valid_time=BASE_TIME + timedelta(minutes=turn),
            observed_at_turn=turn,
        )

    def _representation_pressure_observation(self, turn: int) -> Observation:
        return Observation(
            turn_index=turn,
            event_class=PerturbationClass.REPRESENTATION_PRESSURE.value,
            payload={
                "cumulative_bytes": self._cumulative_a0_bytes(),
                "b_a0": self.b_a0,
                "headroom_bytes": max(0, self.b_a0 - self._cumulative_a0_bytes()),
                "pressure": True,
            },
            valid_time=BASE_TIME + timedelta(minutes=turn),
            observed_at_turn=turn,
        )

    def _protected_state_at_bound_observation(self, turn: int) -> Observation:
        return Observation(
            turn_index=turn,
            event_class=PerturbationClass.PROTECTED_STATE_AT_BOUND.value,
            payload={
                "protected_records": ["manifest", "authority-artifacts"],
                "budget_at_bound": True,
                "silent_loss": False,
            },
            valid_time=BASE_TIME + timedelta(minutes=turn),
            observed_at_turn=turn,
        )

    # ------------------------------------------------------------------
    # Action resolution
    # ------------------------------------------------------------------

    def _resolve_action(
        self, action: ProbeAction, observation: Observation
    ) -> EpisodeEvent:
        """Apply action effects and perturbation effects to state."""
        if self._current_perturbation is not None:
            self._apply_perturbation_effect(self._current_perturbation, observation)
            self._current_perturbation = None
        if action is ProbeAction.VERIFY_EFFECT and self._state.pending_effect:
            self._state.pending_effect["verified"] = True
            self._state.pending_effect = None
        self._materialize_state()
        payload = dict(observation.payload)
        payload["action"] = action.value
        if self._a0_overflow or self._arm_overflow:
            payload["action_reason"] = "REPRESENTATION_BUDGET_OVERFLOW"
        return EpisodeEvent(
            turn_index=self._turn_index,
            event_id=f"{self.family_id}:{self.seed_id}:event:{self._turn_index:03d}",
            event_class=observation.event_class,
            subject_ref="visible:episode",
            payload=payload,
            valid_time=observation.valid_time,
            observed_at_turn=observation.observed_at_turn,
        )

    def _apply_perturbation_effect(
        self, pcls: PerturbationClass, observation: Observation
    ) -> None:
        """Apply the state change for a perturbation class."""
        payload = observation.payload
        if pcls is PerturbationClass.ALIAS_REBIND:
            alias = str(payload.get("alias", "alias-00"))
            new_ref = str(payload.get("new_ref", "entity-00"))
            self._state.aliases[alias] = new_ref
        elif pcls is PerturbationClass.OBJECT_VERSION_CHANGE:
            entity = str(payload.get("entity", "entity-00"))
            self._state.entities[entity] = "v2"
        elif pcls is PerturbationClass.PROCESS_RESTART:
            self._state.process_epoch += 1
            self._state.pending_effect = None
        elif pcls is PerturbationClass.OUT_OF_ORDER_TRANSACTION:
            self._state.assertions.append(
                {
                    "assertion_id": payload.get("assertion_id"),
                    "predicate": payload.get("predicate"),
                    "value": payload.get("value"),
                    "valid_time": payload.get("valid_time_iso"),
                }
            )
        elif pcls is PerturbationClass.HALF_OPEN_VALID_TIME_BOUNDARY:
            self._state.assertions.append(
                {
                    "assertion_id": payload.get("assertion_id"),
                    "boundary": payload.get("boundary"),
                    "predicate": payload.get("predicate"),
                    "value": payload.get("value"),
                }
            )
        elif pcls is PerturbationClass.SIMULTANEOUS_CONFLICTING_EVIDENCE:
            assertions = payload.get("assertions", [])
            if isinstance(assertions, (list, tuple)):
                for assertion in assertions:
                    if isinstance(assertion, dict):
                        self._state.assertions.append(dict(assertion))
        elif pcls is PerturbationClass.ACTION_DISPATCH:
            action_ref = str(payload.get("action_ref", "action-000"))
            self._state.dispatched_actions[action_ref] = {
                "status": "pending",
                "turn": observation.turn_index,
            }
            self._state.pending_effect = {
                "action_ref": action_ref,
                "verified": False,
            }
        elif pcls is PerturbationClass.DETERMINISTIC_RECOVERY:
            # Recovery action is recorded; state is not mutated here.
            pass
        elif pcls is PerturbationClass.PENDING_COMMITMENT:
            commitment_ref = str(payload.get("commitment_ref", "commitment-000"))
            preconditions = payload.get("preconditions", [])
            if not isinstance(preconditions, (list, tuple)):
                preconditions = []
            self._state.commitments.append(
                {
                    "commitment_ref": commitment_ref,
                    "preconditions": list(preconditions),
                    "status": "pending",
                }
            )
        elif pcls is PerturbationClass.PRECONDITION_REFUTATION:
            commitment_ref = str(payload.get("commitment_ref", "commitment-000"))
            for commitment in self._state.commitments:
                if commitment.get("commitment_ref") == commitment_ref:
                    commitment["status"] = "blocked"
        elif pcls is PerturbationClass.DELAYED_DEPENDENT_ACTION:
            action_ref = str(payload.get("action_ref", "action-000"))
            self._state.dispatched_actions[action_ref] = {
                "status": "blocked_precondition_refuted",
                "turn": observation.turn_index,
            }
        elif pcls is PerturbationClass.ASSERTION_SUPERSESSION:
            supersedes = payload.get("supersedes")
            for assertion in self._state.assertions:
                if assertion.get("assertion_id") == supersedes:
                    assertion["status"] = "superseded"
            self._state.assertions.append(
                {
                    "assertion_id": payload.get("assertion_id"),
                    "supersedes": supersedes,
                    "predicate": payload.get("predicate"),
                    "value": payload.get("value"),
                }
            )
            self._state.assertions.append(
                {
                    "assertion_id": payload.get("dependent_assertion_id"),
                    "depends_on": supersedes,
                    "status": "active",
                }
            )
        elif pcls is PerturbationClass.LATE_REFUTATION:
            refuted_assertion_id = payload.get("refuted_assertion_id")
            for assertion in self._state.assertions:
                if assertion.get("assertion_id") == refuted_assertion_id:
                    assertion["status"] = "refuted"
            dependents = payload.get("dependent_assertion_ids", [])
            if not isinstance(dependents, (list, tuple)):
                dependents = []
            self._state.assertions.append(
                {
                    "assertion_id": payload.get("refutation_id"),
                    "refutes": refuted_assertion_id,
                    "dependents": list(dependents),
                    "status": "refutation",
                }
            )
        elif pcls is PerturbationClass.TRANSITIVE_INVALIDATION:
            chain = payload.get("chain", [])
            if not isinstance(chain, (list, tuple)):
                chain = []
            previous: str | None = None
            for cid in chain:
                self._state.assertions.append(
                    {
                        "assertion_id": cid,
                        "depends_on": previous,
                        "status": "invalidated",
                        "root_cause": payload.get("root_cause"),
                    }
                )
                previous = str(cid)
        elif pcls is PerturbationClass.RECEIPT_LOSS:
            action_ref = str(payload.get("action_ref", "action-000"))
            self._state.dispatched_actions[action_ref] = {
                "status": "receipt_lost",
                "turn": observation.turn_index,
            }
            self._state.pending_effect = {
                "action_ref": action_ref,
                "verified": False,
            }
        elif pcls is PerturbationClass.INTERRUPTION_BEFORE_EFFECT_VERIFICATION:
            action_ref = str(payload.get("action_ref", "action-000"))
            self._state.process_epoch += 1
            self._state.dispatched_actions[action_ref] = {
                "status": "interrupted_unverified",
                "turn": observation.turn_index,
            }
            self._state.pending_effect = {
                "action_ref": action_ref,
                "verified": False,
            }
        elif pcls is PerturbationClass.REPRESENTATION_PRESSURE:
            # Marker only: representation pressure must not inflate state.
            pass
        elif pcls is PerturbationClass.PROTECTED_STATE_AT_BOUND:
            # Marker only: protected-state notification carries no mutation.
            pass

    def _update_terminal_status(self, action: ProbeAction) -> None:
        """Update episode status after an action is resolved."""
        if self._turn_index >= self.T:
            self._status = EpisodeStatus.TERMINAL
            return
        if self._turn_index in self._checkpoints and action is ProbeAction.ABSTAIN:
            if self._turn_index == max(self._checkpoints):
                self._status = EpisodeStatus.ABSTAINED

    # ------------------------------------------------------------------
    # Budget and introspection
    # ------------------------------------------------------------------

    def _cumulative_a0_bytes(self, next_observation: Observation | None = None) -> int:
        """Serialized bytes of the ordered observation tuple."""
        observations = list(self._observations)
        if next_observation is not None:
            observations.append(next_observation)
        return len(
            _canonical_json([obs.canonical_json() for obs in observations]).encode(
                "utf-8"
            )
        )

    def _state_digest(self) -> str:
        """Return a deterministic digest of current in-memory state."""
        return hashlib.sha256(
            _canonical_json(
                {
                    "aliases": self._state.aliases,
                    "entities": self._state.entities,
                    "process_epoch": self._state.process_epoch,
                }
            ).encode("utf-8")
        ).hexdigest()

    @property
    def observations(self) -> list[Observation]:
        return list(self._observations)

    @property
    def events(self) -> list[EpisodeEvent]:
        return list(self._events)

    @property
    def checkpoints(self) -> list[int]:
        return list(self._checkpoints)

    @property
    def status(self) -> EpisodeStatus:
        return self._status

    @property
    def a0_overflow(self) -> bool:
        return self._a0_overflow

    @property
    def arm_overflow(self) -> bool:
        return self._arm_overflow

    @property
    def temp_root(self) -> Path:
        return self._temp_root

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        """Remove the materialization root and all files written by the episode."""
        if self._temp_root.exists():
            shutil.rmtree(self._temp_root, ignore_errors=True)

    def __enter__(self) -> InteractiveEpisode:
        return self

    def __exit__(self, *exc: object) -> None:
        self.cleanup()
