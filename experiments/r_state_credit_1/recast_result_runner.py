"""One-shot result runner skeleton; it cannot manufacture run authority."""

from __future__ import annotations

from typing import Mapping, Protocol, Sequence

from experiments.r_state_credit_1.contracts import ArmId, ScenarioFamily
from experiments.r_state_credit_1.recast_freeze_contracts import (
    ExecutionBundle,
    SuccessorReadiness,
)
from experiments.r_state_credit_1.run_contracts import CheckpointId, HELD_OUT_SEEDS


class RunNotReady(RuntimeError):
    pass


class C7Interrupted(RuntimeError):
    pass


class C7Probe(Protocol):
    def abort_requested(self) -> bool: ...


class ResultRunner:
    """Perform pre/post C7 checks and make every attempt terminal.

    The actual provider loop remains unavailable until a future frozen bundle
    supplies its receipt and matching run authorization.
    """

    def __init__(self, bundle: ExecutionBundle, c7: C7Probe) -> None:
        self.bundle = bundle
        self._c7 = c7
        self._terminal = False

    def run(self, public_rows: Sequence[Mapping[str, object]]) -> None:
        if self._terminal:
            raise RunNotReady("run lock is terminal and cannot be retried")
        readiness = SuccessorReadiness.evaluate(self.bundle)
        if readiness.status != "READY":
            raise RunNotReady("future freeze-bound run authorization is absent")
        self._terminal = True
        forbidden = {
            "correct_action",
            "loss_by_action",
            "sealed_truth",
            "referee_label",
        }
        if any(forbidden.intersection(row) for row in public_rows):
            raise RunNotReady("hidden truth reached the public runner input")
        if self._c7.abort_requested():
            raise C7Interrupted("C7 interrupted before execution")
        expected = {
            (family.value, seed, checkpoint.value, arm.value)
            for family in ScenarioFamily
            for seed in HELD_OUT_SEEDS
            for checkpoint in CheckpointId
            for arm in ArmId
        }
        identities = [
            (
                row.get("family"),
                row.get("seed"),
                row.get("checkpoint_id"),
                row.get("arm_id"),
            )
            for row in public_rows
        ]
        if (
            len(identities) != self.bundle.expected_provider_calls
            or len(set(identities)) != len(identities)
            or set(identities) != expected
        ):
            raise RunNotReady("exact public row coverage drift")
        # Successor F intentionally stops before provider execution until the
        # real provider, sealed executor and result writer are independently bound.
        if self._c7.abort_requested():
            raise C7Interrupted("C7 interrupted after bounded execution")
        raise RunNotReady("real provider executor is not bound")
