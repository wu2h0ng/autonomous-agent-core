from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum

from .canonical import content_digest


PROBABILITY_SCALE = 1_000_000


class RegistryValidationError(ValueError):
    """A hypothesis registry invariant was violated."""


class HypothesisStatus(str, Enum):
    OPEN = "OPEN"
    SUPPORTED = "SUPPORTED"
    REFUTED = "REFUTED"
    CONFLICT = "CONFLICT"
    STALE = "STALE"


@dataclass(frozen=True, slots=True)
class Hypothesis:
    hypothesis_id: str
    alternative_group: str
    probability_micros: int
    status: HypothesisStatus
    is_other: bool
    conflicts_with: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.hypothesis_id or not self.alternative_group:
            raise RegistryValidationError("hypothesis id and group must be non-empty")
        if (
            isinstance(self.probability_micros, bool)
            or not isinstance(self.probability_micros, int)
            or not 0 <= self.probability_micros <= PROBABILITY_SCALE
        ):
            raise RegistryValidationError(
                "probability_micros is outside the closed domain"
            )
        if len(self.conflicts_with) != len(set(self.conflicts_with)):
            raise RegistryValidationError("hypothesis conflict links must be unique")


@dataclass(frozen=True, slots=True)
class HypothesisUpdate:
    hypothesis_id: str
    probability_micros: int
    status: HypothesisStatus
    conflicts_with: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.hypothesis_id:
            raise RegistryValidationError("update hypothesis_id must be non-empty")
        if (
            isinstance(self.probability_micros, bool)
            or not isinstance(self.probability_micros, int)
            or not 0 <= self.probability_micros <= PROBABILITY_SCALE
        ):
            raise RegistryValidationError(
                "update probability is outside the closed domain"
            )
        if len(self.conflicts_with) != len(set(self.conflicts_with)):
            raise RegistryValidationError("conflicts_with ids must be unique")


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    revision: int
    hypotheses: tuple[Hypothesis, ...]
    prior_snapshot_digest: str | None
    evidence_refs: tuple[str, ...]
    snapshot_digest: str


class HypothesisRegistry:
    """Append-only snapshots of competing, uncertainty-preserving hypotheses."""

    def __init__(self, hypotheses: tuple[Hypothesis, ...]) -> None:
        self._validate_hypotheses(hypotheses)
        payload = {
            "revision": 0,
            "hypotheses": [asdict(item) for item in hypotheses],
            "prior_snapshot_digest": None,
            "evidence_refs": [],
        }
        initial = RegistrySnapshot(
            revision=0,
            hypotheses=tuple(hypotheses),
            prior_snapshot_digest=None,
            evidence_refs=(),
            snapshot_digest=content_digest("registry-snapshot", payload),
        )
        self._history: tuple[RegistrySnapshot, ...] = (initial,)

    @property
    def history(self) -> tuple[RegistrySnapshot, ...]:
        return self._history

    @property
    def current(self) -> RegistrySnapshot:
        return self._history[-1]

    def append_revision(
        self,
        *,
        updates: tuple[HypothesisUpdate, ...],
        evidence_refs: tuple[str, ...],
        expected_parent_digest: str,
    ) -> RegistrySnapshot:
        if expected_parent_digest != self.current.snapshot_digest:
            raise RegistryValidationError("registry parent digest is stale")
        if not updates:
            raise RegistryValidationError("registry revision requires updates")
        if not evidence_refs or any(not ref for ref in evidence_refs):
            raise RegistryValidationError("registry revision requires evidence refs")
        if len(evidence_refs) != len(set(evidence_refs)):
            raise RegistryValidationError("evidence refs must be unique")
        update_ids = tuple(update.hypothesis_id for update in updates)
        if len(update_ids) != len(set(update_ids)):
            raise RegistryValidationError("a revision may update each hypothesis once")

        by_id = {item.hypothesis_id: item for item in self.current.hypotheses}
        unknown = set(update_ids) - set(by_id)
        if unknown:
            raise RegistryValidationError(f"unknown hypothesis ids: {sorted(unknown)}")

        update_by_id = {item.hypothesis_id: item for item in updates}
        for update in updates:
            if update.status is not HypothesisStatus.CONFLICT:
                if update.conflicts_with:
                    raise RegistryValidationError(
                        "conflicts_with is allowed only for CONFLICT updates"
                    )
                continue
            if not update.conflicts_with:
                raise RegistryValidationError("CONFLICT requires reciprocal peer links")
            source = by_id[update.hypothesis_id]
            for peer_id in update.conflicts_with:
                peer = by_id.get(peer_id)
                peer_update = update_by_id.get(peer_id)
                if (
                    peer is None
                    or peer.alternative_group != source.alternative_group
                    or peer_update is None
                    or peer_update.status is not HypothesisStatus.CONFLICT
                    or update.hypothesis_id not in peer_update.conflicts_with
                ):
                    raise RegistryValidationError(
                        "CONFLICT links must be reciprocal and within one alternative group"
                    )
        revised: list[Hypothesis] = []
        for current in self.current.hypotheses:
            update = update_by_id.get(current.hypothesis_id)
            if update is None:
                revised.append(current)
                continue
            if current.is_other and (
                update.probability_micros <= 0
                or update.status in {HypothesisStatus.REFUTED, HypothesisStatus.STALE}
            ):
                raise RegistryValidationError(
                    "OTHER must remain active with non-zero probability"
                )
            revised.append(
                Hypothesis(
                    hypothesis_id=current.hypothesis_id,
                    alternative_group=current.alternative_group,
                    probability_micros=update.probability_micros,
                    status=update.status,
                    is_other=current.is_other,
                    conflicts_with=(
                        tuple(sorted(update.conflicts_with))
                        if update.status is HypothesisStatus.CONFLICT
                        else ()
                    ),
                )
            )

        revised_tuple = tuple(revised)
        self._validate_hypotheses(revised_tuple)
        revision_number = self.current.revision + 1
        refs = tuple(sorted(evidence_refs))
        payload = {
            "revision": revision_number,
            "hypotheses": [asdict(item) for item in revised_tuple],
            "prior_snapshot_digest": self.current.snapshot_digest,
            "evidence_refs": list(refs),
        }
        snapshot = RegistrySnapshot(
            revision=revision_number,
            hypotheses=revised_tuple,
            prior_snapshot_digest=self.current.snapshot_digest,
            evidence_refs=refs,
            snapshot_digest=content_digest("registry-snapshot", payload),
        )
        self._history = (*self._history, snapshot)
        return snapshot

    @staticmethod
    def _validate_hypotheses(hypotheses: tuple[Hypothesis, ...]) -> None:
        if not hypotheses:
            raise RegistryValidationError("registry requires at least one hypothesis")
        ids = tuple(item.hypothesis_id for item in hypotheses)
        if len(ids) != len(set(ids)):
            raise RegistryValidationError("hypothesis ids must be unique")
        by_id = {item.hypothesis_id: item for item in hypotheses}
        for item in hypotheses:
            if item.status is HypothesisStatus.CONFLICT:
                if not item.conflicts_with:
                    raise RegistryValidationError(
                        "CONFLICT hypothesis requires peer links"
                    )
                for peer_id in item.conflicts_with:
                    peer = by_id.get(peer_id)
                    if (
                        peer is None
                        or peer.alternative_group != item.alternative_group
                        or peer.status is not HypothesisStatus.CONFLICT
                        or item.hypothesis_id not in peer.conflicts_with
                    ):
                        raise RegistryValidationError(
                            "CONFLICT hypothesis links must be reciprocal within a group"
                        )
            elif item.conflicts_with:
                raise RegistryValidationError(
                    "non-CONFLICT hypothesis cannot retain conflict links"
                )
        groups = {item.alternative_group for item in hypotheses}
        for group in groups:
            members = tuple(
                item for item in hypotheses if item.alternative_group == group
            )
            others = tuple(item for item in members if item.is_other)
            if len(others) != 1 or others[0].probability_micros <= 0:
                raise RegistryValidationError(
                    f"group {group!r} requires exactly one OTHER with non-zero probability"
                )
            if sum(item.probability_micros for item in members) != PROBABILITY_SCALE:
                raise RegistryValidationError(
                    f"group {group!r} probabilities must sum to {PROBABILITY_SCALE}"
                )
