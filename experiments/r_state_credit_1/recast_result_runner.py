"""One-shot result runner skeleton; it cannot manufacture run authority."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Mapping, Protocol, Sequence

from experiments.r_state_credit_1.contracts import ArmId, ScenarioFamily
from experiments.r_state_credit_1.recast_freeze_contracts import (
    ExactSuccessorArtifacts,
    ExecutionBundle,
    ReceiptVerifier,
    SuccessorReadiness,
    VerifiedReceipt,
)
from experiments.r_state_credit_1.run_contracts import CheckpointId, HELD_OUT_SEEDS


class RunNotReady(RuntimeError):
    pass


class C7Interrupted(RuntimeError):
    pass


class C7Probe(Protocol):
    def abort_requested(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class PublicResultRow:
    """Closed public identity only; no payload or nested metadata channel."""

    family: ScenarioFamily
    seed: int
    checkpoint_id: CheckpointId
    arm_id: ArmId

    def __post_init__(self) -> None:
        if not isinstance(self.family, ScenarioFamily):
            raise ValueError("family must be ScenarioFamily")
        if self.seed not in HELD_OUT_SEEDS:
            raise ValueError("seed is outside held-out roster")
        if not isinstance(self.checkpoint_id, CheckpointId):
            raise ValueError("checkpoint_id must be CheckpointId")
        if not isinstance(self.arm_id, ArmId):
            raise ValueError("arm_id must be ArmId")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> PublicResultRow:
        expected = {field.name for field in fields(cls)}
        if set(value) != expected:
            raise ValueError("closed public row schema rejects extra or missing fields")
        try:
            return cls(
                family=ScenarioFamily(value["family"]),
                seed=value["seed"],  # type: ignore[arg-type]
                checkpoint_id=CheckpointId(value["checkpoint_id"]),
                arm_id=ArmId(value["arm_id"]),
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "closed public row schema rejects invalid scalar fields"
            ) from exc


class ResultRunner:
    """Perform pre/post C7 checks and make every attempt terminal.

    The actual provider loop remains unavailable until a future frozen bundle
    supplies its receipt and matching run authorization.
    """

    def __init__(
        self,
        bundle: ExecutionBundle,
        c7: C7Probe,
        *,
        artifacts: ExactSuccessorArtifacts | None = None,
        receipts: tuple[VerifiedReceipt, ...] = (),
        receipt_verifier: ReceiptVerifier | None = None,
    ) -> None:
        self.bundle = bundle
        self._c7 = c7
        self._artifacts = artifacts
        self._receipts = receipts
        self._receipt_verifier = receipt_verifier
        self._terminal = False

    def run(self, public_rows: Sequence[PublicResultRow]) -> None:
        if self._terminal:
            raise RunNotReady("run lock is terminal and cannot be retried")
        readiness = SuccessorReadiness.evaluate(
            self.bundle,
            artifacts=self._artifacts,
            receipts=self._receipts,
            receipt_verifier=self._receipt_verifier,
        )
        if readiness.status != "READY":
            raise RunNotReady("future freeze-bound verified custody is absent")
        self._terminal = True
        if any(type(row) is not PublicResultRow for row in public_rows):
            raise RunNotReady("runner accepts exact typed public rows only")
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
            (row.family.value, row.seed, row.checkpoint_id.value, row.arm_id.value)
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
