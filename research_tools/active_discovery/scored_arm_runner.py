from __future__ import annotations

from dataclasses import dataclass

from .canonical import content_digest
from .scoring_contracts import ChallengeCatalogue, DiscoveryScoreBundle
from .scoring_referee import ScoringReferee


class ScoredRunnerError(ValueError):
    """A matched scored collection failed before its global close."""


@dataclass(frozen=True, slots=True)
class ScoredArmInput:
    arm_id: str
    adapter_identity: str
    catalogue: ChallengeCatalogue
    prefix_bundles: tuple[DiscoveryScoreBundle, ...]


@dataclass(frozen=True, slots=True)
class ScoredCollectionReceipt:
    episode_id: str
    arm_ids: tuple[str, ...]
    arm_count: int
    bundle_count: int
    final_consumed_units: int
    global_close_digest: str
    receipt_digest: str


def _prevalidate(
    *, referee: ScoringReferee, arms: tuple[ScoredArmInput, ...]
) -> tuple[ScoredArmInput, ...]:
    if len(arms) != len(referee.expected_arm_ids):
        raise ScoredRunnerError("arm inputs must cover every expected arm exactly")
    by_arm = {item.arm_id: item for item in arms}
    if len(by_arm) != len(arms) or set(by_arm) != set(referee.expected_arm_ids):
        raise ScoredRunnerError("arm inputs must cover every expected arm exactly")
    ordered = tuple(by_arm[arm_id] for arm_id in referee.expected_arm_ids)

    adapter_identities = tuple(item.adapter_identity for item in ordered)
    if any(
        not isinstance(identity, str) or not identity.strip()
        for identity in adapter_identities
    ) or len(adapter_identities) != len(set(adapter_identities)):
        raise ScoredRunnerError("each matched arm requires a fresh adapter identity")

    catalogue_digests = {item.catalogue.catalogue_digest for item in ordered}
    if len(catalogue_digests) != 1:
        raise ScoredRunnerError("matched arms require exact challenge catalogue parity")

    actor_bindings = {
        bundle.actor_binding_digest
        for arm in ordered
        for bundle in arm.prefix_bundles
    }
    if len(actor_bindings) != 1:
        raise ScoredRunnerError("actor binding parity failed across matched arms")

    experiment_ids: set[str] = set()
    for arm in ordered:
        if len(arm.prefix_bundles) != 5 or tuple(
            bundle.prefix_index for bundle in arm.prefix_bundles
        ) != tuple(range(5)):
            raise ScoredRunnerError("every arm requires an exact k=0..4 prefix chain")
        prior_digest: str | None = None
        arm_bindings: set[str] = set()
        for bundle in arm.prefix_bundles:
            if bundle.arm_id != arm.arm_id:
                raise ScoredRunnerError("bundle arm identity does not match its arm input")
            if bundle.parent_bundle_digest != prior_digest:
                raise ScoredRunnerError("prefix chain parent digest mismatch")
            try:
                reparsed = DiscoveryScoreBundle.from_mapping(
                    bundle.to_mapping(), arm.catalogue
                )
            except (TypeError, ValueError) as exc:
                raise ScoredRunnerError("bundle failed challenge parity validation") from exc
            if reparsed.bundle_digest != bundle.bundle_digest:
                raise ScoredRunnerError("bundle canonical digest drifted")
            prior_digest = bundle.bundle_digest
            arm_bindings.add(bundle.actor_binding_digest)
            experiment_ids.add(bundle.experiment_id)
        if len(arm_bindings) != 1:
            raise ScoredRunnerError("actor binding parity failed within an arm")
    if len(experiment_ids) != 1:
        raise ScoredRunnerError("experiment binding parity failed across matched arms")
    return ordered


def run_scored_arm_collection(
    *, referee: ScoringReferee, arms: tuple[ScoredArmInput, ...]
) -> ScoredCollectionReceipt:
    """Seal every matched k=0..4 chain, then close without exposing a score."""

    if referee.is_closed:
        raise ScoredRunnerError("scored collection referee is already closed")
    ordered = _prevalidate(referee=referee, arms=arms)
    for arm in ordered:
        channel = referee.actor_channel(arm.arm_id)
        for bundle in arm.prefix_bundles:
            channel.submit(bundle=bundle, catalogue=arm.catalogue)
    close = referee.close_actor_channels()
    final_consumed_units = max(
        arm.prefix_bundles[-1].consumed_units for arm in ordered
    )
    payload = {
        "episode_id": referee.episode_id,
        "arm_ids": list(referee.expected_arm_ids),
        "arm_count": len(ordered),
        "bundle_count": close.bundle_count,
        "final_consumed_units": final_consumed_units,
        "global_close_digest": close.close_digest,
    }
    return ScoredCollectionReceipt(
        episode_id=referee.episode_id,
        arm_ids=referee.expected_arm_ids,
        arm_count=len(ordered),
        bundle_count=close.bundle_count,
        final_consumed_units=final_consumed_units,
        global_close_digest=close.close_digest,
        receipt_digest=content_digest("scored-arm-collection/v1", payload),
    )
