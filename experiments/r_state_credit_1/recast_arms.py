"""Real A0-A3 representation arms for the R-STATE-CREDIT-1 recast path.

Each arm renders its own representation of the released observation prefix and
holds its own budget ledger with fail-closed overflow/ABSTAIN semantics.  The
module is runner-only: neutral labels, call order, and the reverse map remain
in :mod:`experiments.r_state_credit_1.arm_blinding`.  No provider call, model
inference, training, or external side effect occurs here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from experiments.r_state_credit_1.action_grammar import ActorAction
from experiments.r_state_credit_1.contracts import ArmId
from experiments.r_state_credit_1.observation import Observation, _canonical_json


FORCED_OVERFLOW_REASON = "REPRESENTATION_BUDGET_OVERFLOW"

_ROUTINE_EVENT_CLASS = "ENTITY_OBSERVED"
_RECENT_WINDOW = 6
_MAX_SELECTED = 12
_RELEVANCE_RULE_ID = "nonroutine-recency-v1"

_DISPATCH_CLASSES = {
    "ACTION_DISPATCH": "unverified",
    "RECEIPT_LOSS": "receipt_lost",
    "INTERRUPTION_BEFORE_EFFECT_VERIFICATION": "interrupted_unverified",
}
_CONFLICT_CLASSES = {
    "OUT_OF_ORDER_TRANSACTION": "out_of_order",
    "HALF_OPEN_VALID_TIME_BOUNDARY": "boundary",
    "SIMULTANEOUS_CONFLICTING_EVIDENCE": "contradiction",
    "DELAYED_DEPENDENT_ACTION": "dependent_refuted",
    "ASSERTION_SUPERSESSION": "supersession",
    "LATE_REFUTATION": "late_refutation",
    "TRANSITIVE_INVALIDATION": "transitive_invalidation",
}


class RecastArmViolation(RuntimeError):
    """Raised when arm inputs or budget configuration are invalid."""


def _observation_mapping(observation: Observation) -> dict[str, Any]:
    return json.loads(observation.canonical_json())


def _require_prefix(observations: Sequence[Observation]) -> tuple[Observation, ...]:
    prefix = tuple(observations)
    if not prefix:
        raise RecastArmViolation("observation prefix must be non-empty")
    if any(not isinstance(item, Observation) for item in prefix):
        raise RecastArmViolation("prefix must contain Observation values")
    return prefix


class RepresentationArm(Protocol):
    """One representation arm over the shared released observation prefix."""

    arm_id: ArmId

    def context(self, observations: tuple[Observation, ...]) -> dict[str, Any]: ...


@dataclass
class ArmBudgetLedger:
    """Per-arm byte accounting.

    ``mode`` is ``"peak"`` for the A0 raw log (the rendered tuple already is
    the cumulative byte count of the episode so far) and ``"cumulative"`` for
    the bounded representation arms (delivered bytes accumulate).
    """

    budget: int
    mode: str
    charged_bytes: int = 0
    peak_bytes: int = 0
    requests: int = 0
    overflowed: bool = False

    def would_overflow(self, candidate_bytes: int) -> bool:
        if candidate_bytes > self.budget:
            return True
        if self.mode == "cumulative":
            return self.charged_bytes + candidate_bytes > self.budget
        return False

    def charge(self, candidate_bytes: int) -> None:
        self.charged_bytes += candidate_bytes
        self.peak_bytes = max(self.peak_bytes, candidate_bytes)
        self.requests += 1

    def copy(self) -> ArmBudgetLedger:
        return ArmBudgetLedger(
            budget=self.budget,
            mode=self.mode,
            charged_bytes=self.charged_bytes,
            peak_bytes=self.peak_bytes,
            requests=self.requests,
            overflowed=self.overflowed,
        )


@dataclass(frozen=True, slots=True)
class RepresentationOutcome:
    """The runner-side result of asking one arm for its representation."""

    arm_id: ArmId
    representation: str
    representation_bytes: int
    forced_action: ActorAction | None
    forced_reason: str | None


class FullLogArm:
    """A0: the exact ordered bounded raw log; no truncation or selection."""

    arm_id = ArmId.A0_FULL_LOG

    def context(self, observations: tuple[Observation, ...]) -> dict[str, Any]:
        return {
            "entries": [_observation_mapping(obs) for obs in observations],
            "released": len(observations),
        }


class RollingSummaryArm:
    """A1: deterministic lossy rolling summary of the prefix."""

    arm_id = ArmId.A1_ROLLING_SUMMARY

    def context(self, observations: tuple[Observation, ...]) -> dict[str, Any]:
        class_counts: dict[str, int] = {}
        for obs in observations:
            class_counts[obs.event_class] = class_counts.get(obs.event_class, 0) + 1
        recent = observations[-_RECENT_WINDOW:]
        compacted = observations[: max(0, len(observations) - _RECENT_WINDOW)]
        digest = hashlib.sha256()
        for obs in compacted:
            digest.update(obs.canonical_json().encode("utf-8"))
            digest.update(b"\x00")
        return {
            "class_counts": class_counts,
            "recent": [_observation_mapping(obs) for obs in recent],
            "compacted": {
                "count": len(compacted),
                "digest": digest.hexdigest(),
            },
        }


class BoundedRetrievalArm:
    """A2: bounded retrieval over prior observations with a frozen rule."""

    arm_id = ArmId.A2_FROZEN_RETRIEVAL

    def context(self, observations: tuple[Observation, ...]) -> dict[str, Any]:
        relevant = [
            obs
            for obs in observations
            if obs.event_class != _ROUTINE_EVENT_CLASS
        ]
        selected = relevant[-_MAX_SELECTED:]
        return {
            "rule": _RELEVANCE_RULE_ID,
            "selected": [_observation_mapping(obs) for obs in selected],
            "omitted": len(observations) - len(selected),
        }


class TypedStateArm:
    """A3: typed state/commitment/conflict compilation of the visible feed.

    The compilation is policy-neutral: it exposes typed facts only and never
    emits a directive, hint, or recommended action.
    """

    arm_id = ArmId.A3_TYPED_STATE

    def context(self, observations: tuple[Observation, ...]) -> dict[str, Any]:
        entities: dict[str, str] = {}
        bindings: dict[str, str] = {}
        epoch = 1
        active: list[str] = []
        superseded: list[str] = []
        refuted: list[str] = []
        out_of_order: list[str] = []
        invalidated: list[str] = []
        commitments: dict[str, str] = {}
        effects: dict[str, str] = {}
        conflicts_open: list[dict[str, str]] = []
        recovery: dict[str, str] | None = None
        pressure_open = 0
        protected_at_bound = False

        for obs in observations:
            name = obs.event_class
            payload = obs.payload
            if name == _ROUTINE_EVENT_CLASS:
                entity = str(payload.get("entity", ""))
                if entity:
                    entities[entity] = str(payload.get("object_version", ""))
                epoch = int(payload.get("process_epoch", epoch))
            elif name == "ALIAS_REBIND":
                alias = str(payload.get("alias", ""))
                bindings[alias] = str(payload.get("new_ref", ""))
                conflicts_open.append({"kind": "binding_change", "ref": alias})
            elif name == "OBJECT_VERSION_CHANGE":
                entity = str(payload.get("entity", ""))
                entities[entity] = str(payload.get("new_version", ""))
                conflicts_open.append({"kind": "version_change", "ref": entity})
            elif name == "PROCESS_RESTART":
                epoch = int(payload.get("new_epoch", epoch + 1))
                for ref, status in list(effects.items()):
                    if status != "verified":
                        effects[ref] = "cleared_by_restart"
            elif name == "OUT_OF_ORDER_TRANSACTION":
                ref = str(payload.get("assertion_id", ""))
                out_of_order.append(ref)
                conflicts_open.append({"kind": "out_of_order", "ref": ref})
            elif name == "HALF_OPEN_VALID_TIME_BOUNDARY":
                ref = str(payload.get("assertion_id", ""))
                active.append(ref)
                conflicts_open.append({"kind": "boundary", "ref": ref})
            elif name == "SIMULTANEOUS_CONFLICTING_EVIDENCE":
                raw = payload.get("assertions", [])
                refs = [
                    str(item.get("assertion_id", ""))
                    for item in raw
                    if isinstance(item, dict)
                ]
                active.extend(refs)
                conflicts_open.append(
                    {"kind": "contradiction", "ref": refs[0] if refs else ""}
                )
            elif name in _DISPATCH_CLASSES:
                ref = str(payload.get("action_ref", ""))
                effects[ref] = _DISPATCH_CLASSES[name]
                if name == "INTERRUPTION_BEFORE_EFFECT_VERIFICATION":
                    epoch = int(payload.get("new_epoch", epoch + 1))
            elif name == "PENDING_COMMITMENT":
                ref = str(payload.get("commitment_ref", ""))
                commitments[ref] = "pending"
            elif name == "PRECONDITION_REFUTATION":
                ref = str(payload.get("commitment_ref", ""))
                commitments[ref] = "blocked"
            elif name == "ASSERTION_SUPERSESSION":
                superseded.append(str(payload.get("supersedes", "")))
                active.append(str(payload.get("assertion_id", "")))
                conflicts_open.append(
                    {
                        "kind": "supersession",
                        "ref": str(payload.get("assertion_id", "")),
                    }
                )
            elif name == "LATE_REFUTATION":
                refuted.append(str(payload.get("refuted_assertion_id", "")))
                conflicts_open.append(
                    {
                        "kind": "late_refutation",
                        "ref": str(payload.get("refutation_id", "")),
                    }
                )
            elif name == "TRANSITIVE_INVALIDATION":
                chain = payload.get("chain", [])
                if isinstance(chain, (list, tuple)):
                    invalidated.extend(str(item) for item in chain)
                conflicts_open.append(
                    {
                        "kind": "transitive_invalidation",
                        "ref": str(payload.get("root_cause", "")),
                    }
                )
            elif name == "DETERMINISTIC_RECOVERY":
                recovery = {
                    "ref": str(payload.get("recovery_ref", "")),
                    "snapshot_digest": str(payload.get("snapshot_digest", "")),
                }
            elif name == "REPRESENTATION_PRESSURE":
                pressure_open += 1
            elif name == "PROTECTED_STATE_AT_BOUND":
                protected_at_bound = True
            elif name == "EFFECT_VERIFIED":
                ref = str(payload.get("action_ref", ""))
                effects[ref] = "verified"
            elif name == "STATE_REVIEWED":
                conflicts_open = []
            elif name == "ABSTENTION_RECORDED":
                for ref, status in list(commitments.items()):
                    if status == "blocked":
                        commitments[ref] = "acknowledged_blocked"
                pressure_open = 0
            elif name == "RECOVERY_APPLIED":
                recovery = None

        return {
            "entities": entities,
            "bindings": bindings,
            "epoch": epoch,
            "assertions": {
                "active": active,
                "superseded": superseded,
                "refuted": refuted,
                "out_of_order": out_of_order,
                "invalidated": invalidated,
            },
            "commitments": [
                {"ref": ref, "status": status}
                for ref, status in sorted(commitments.items())
            ],
            "effects": [
                {"ref": ref, "status": status}
                for ref, status in sorted(effects.items())
            ],
            "conflicts_open": conflicts_open,
            "recovery": recovery,
            "pressure_open": pressure_open,
            "protected_at_bound": protected_at_bound,
        }


@dataclass
class ArmRoster:
    """Runner-only roster holding the four arms and their budget ledgers."""

    b_a0: int = 262_144
    b_arm: int = 65_536
    _arms: dict[ArmId, RepresentationArm] = field(init=False)
    _ledgers: dict[ArmId, ArmBudgetLedger] = field(init=False)

    def __post_init__(self) -> None:
        for name in ("b_a0", "b_arm"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise RecastArmViolation(f"{name} must be a positive integer")
        self._arms = {
            arm.arm_id: arm
            for arm in (
                FullLogArm(),
                RollingSummaryArm(),
                BoundedRetrievalArm(),
                TypedStateArm(),
            )
        }
        self._ledgers = {
            ArmId.A0_FULL_LOG: ArmBudgetLedger(budget=self.b_a0, mode="peak"),
            ArmId.A1_ROLLING_SUMMARY: ArmBudgetLedger(
                budget=self.b_arm, mode="cumulative"
            ),
            ArmId.A2_FROZEN_RETRIEVAL: ArmBudgetLedger(
                budget=self.b_arm, mode="cumulative"
            ),
            ArmId.A3_TYPED_STATE: ArmBudgetLedger(
                budget=self.b_arm, mode="cumulative"
            ),
        }

    def _render(
        self, arm_id: ArmId, observations: Sequence[Observation]
    ) -> str:
        prefix = _require_prefix(observations)
        arm = self._arms[arm_id]
        envelope = {
            "latest": _observation_mapping(prefix[-1]),
            "context": arm.context(prefix),
        }
        return _canonical_json(envelope)

    def peek_representation(
        self, arm_id: ArmId, observations: Sequence[Observation]
    ) -> str:
        """Render without charging any ledger (runner-side inspection only)."""
        return self._render(arm_id, observations)

    def representation(
        self, arm_id: ArmId, observations: Sequence[Observation]
    ) -> RepresentationOutcome:
        """Render one arm's representation and account it on the arm's ledger.

        Overflow is fail-closed and sticky: the arm is forced to ``ABSTAIN``
        at the current and every remaining checkpoint, and no other arm is
        affected.
        """
        if not isinstance(arm_id, ArmId):
            raise RecastArmViolation("arm_id must be ArmId")
        ledger = self._ledgers[arm_id]
        if ledger.overflowed:
            return RepresentationOutcome(
                arm_id=arm_id,
                representation="",
                representation_bytes=0,
                forced_action=ActorAction.ABSTAIN,
                forced_reason=FORCED_OVERFLOW_REASON,
            )
        rendered = self._render(arm_id, observations)
        size = len(rendered.encode("utf-8"))
        if ledger.would_overflow(size):
            ledger.overflowed = True
            return RepresentationOutcome(
                arm_id=arm_id,
                representation="",
                representation_bytes=size,
                forced_action=ActorAction.ABSTAIN,
                forced_reason=FORCED_OVERFLOW_REASON,
            )
        ledger.charge(size)
        return RepresentationOutcome(
            arm_id=arm_id,
            representation=rendered,
            representation_bytes=size,
            forced_action=None,
            forced_reason=None,
        )

    def ledger(self, arm_id: ArmId) -> ArmBudgetLedger:
        """Return a copy of the arm's ledger for runner-side receipts."""
        return self._ledgers[arm_id].copy()

    def overflowed(self, arm_id: ArmId) -> bool:
        return self._ledgers[arm_id].overflowed
