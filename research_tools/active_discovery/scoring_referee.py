from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol

from .canonical import content_digest
from .scoring_contracts import ChallengeCatalogue, DiscoveryScoreBundle


class RefereeProtocolError(RuntimeError):
    """A caller crossed the sealed scoring protocol boundary."""


class ScoringHalted(RefereeProtocolError):
    """The external halt authority stopped collection or scoring."""


class HaltAuthority(Protocol):
    def halted(self, episode_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class StoredBundleReceipt:
    bundle_digest: str
    canonical_byte_digest: str
    byte_length: int


@dataclass(frozen=True, slots=True)
class PrefixSealReceipt:
    episode_id: str
    arm_id: str
    prefix_index: int
    bundle_digest: str
    canonical_byte_digest: str
    parent_bundle_digest: str | None
    seal_digest: str


@dataclass(frozen=True, slots=True)
class CollectionCloseReceipt:
    episode_id: str
    expected_arm_ids: tuple[str, ...]
    bundle_digests: tuple[str, ...]
    bundle_count: int
    close_digest: str


@dataclass(frozen=True, slots=True)
class ScoredBundle:
    arm_id: str
    prefix_index: int
    bundle_digest: str
    score_value: object


@dataclass(frozen=True, slots=True)
class RefereeScoreBatch:
    episode_id: str
    authority_id: str
    close_digest: str
    scored_bundles: tuple[ScoredBundle, ...]


class BundleByteReader:
    """Digest-only retrieval grant over an immutable bundle-store snapshot."""

    def __init__(
        self,
        *,
        stored_bytes: Mapping[str, bytes],
        allowed_bundle_digests: frozenset[str],
    ) -> None:
        self._stored_bytes = dict(stored_bytes)
        self._allowed_bundle_digests = allowed_bundle_digests

    def materialize(
        self, *, bundle_digest: str, catalogue: ChallengeCatalogue
    ) -> DiscoveryScoreBundle:
        if bundle_digest not in self._allowed_bundle_digests:
            raise RefereeProtocolError("bundle digest is outside the retrieval grant")
        try:
            raw_bytes = self._stored_bytes[bundle_digest]
        except KeyError as exc:
            raise RefereeProtocolError("sealed bundle bytes are unavailable") from exc
        try:
            raw = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RefereeProtocolError("sealed bundle bytes are not canonical JSON") from exc
        if not isinstance(raw, dict):
            raise RefereeProtocolError("sealed bundle bytes must encode an object")
        bundle = DiscoveryScoreBundle.from_mapping(raw, catalogue)
        if bundle.canonical_bytes != raw_bytes:
            raise RefereeProtocolError("sealed bundle bytes are not canonical")
        if bundle.bundle_digest != bundle_digest:
            raise RefereeProtocolError("sealed bundle digest does not match its bytes")
        return bundle


class BundleByteStore:
    """Content-addressed storage for exact canonical bundle bytes."""

    def __init__(self) -> None:
        self._stored_bytes: dict[str, bytes] = {}

    @property
    def stored_bundle_count(self) -> int:
        return len(self._stored_bytes)

    def _seal_validated(
        self, *, bundle: DiscoveryScoreBundle, catalogue: ChallengeCatalogue
    ) -> StoredBundleReceipt:
        raw_bytes = bundle.canonical_bytes
        try:
            raw = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:  # pragma: no cover
            raise RefereeProtocolError("bundle failed canonical serialization") from exc
        if not isinstance(raw, dict):  # pragma: no cover - dataclass mapping is an object
            raise RefereeProtocolError("bundle serialization must encode an object")
        reparsed = DiscoveryScoreBundle.from_mapping(raw, catalogue)
        if reparsed.canonical_bytes != raw_bytes:
            raise RefereeProtocolError("bundle serialization is not canonical")
        bundle_digest = reparsed.bundle_digest
        if bundle_digest != bundle.bundle_digest:
            raise RefereeProtocolError("bundle digest is not content-addressed")
        existing = self._stored_bytes.get(bundle_digest)
        if existing is not None and existing != raw_bytes:
            raise RefereeProtocolError("bundle digest collision")
        self._stored_bytes[bundle_digest] = raw_bytes
        return StoredBundleReceipt(
            bundle_digest=bundle_digest,
            canonical_byte_digest=hashlib.sha256(raw_bytes).hexdigest(),
            byte_length=len(raw_bytes),
        )

    def _reader_for(
        self, allowed_bundle_digests: tuple[str, ...]
    ) -> BundleByteReader:
        allowed = frozenset(allowed_bundle_digests)
        if len(allowed) != len(allowed_bundle_digests):
            raise RefereeProtocolError("retrieval grant contains duplicate digests")
        if not allowed.issubset(self._stored_bytes):
            raise RefereeProtocolError("retrieval grant names unavailable bundle bytes")
        return BundleByteReader(
            stored_bytes=self._stored_bytes,
            allowed_bundle_digests=allowed,
        )


class ActorSealChannel:
    """Actor-visible capability: append the next immutable prefix only."""

    def __init__(self, referee: ScoringReferee, arm_id: str) -> None:
        self._referee = referee
        self._arm_id = arm_id

    def submit(
        self, *, bundle: DiscoveryScoreBundle, catalogue: ChallengeCatalogue
    ) -> PrefixSealReceipt:
        return self._referee._submit(  # noqa: SLF001 - capability delegation
            arm_id=self._arm_id,
            bundle=bundle,
            catalogue=catalogue,
        )


class AdjudicatorScoreChannel:
    """Post-close capability: make exactly one hidden-scoring attempt."""

    def __init__(self, referee: ScoringReferee, authority_id: str) -> None:
        self._referee = referee
        self._authority_id = authority_id

    def score_all(
        self,
        *,
        catalogues: Mapping[str, ChallengeCatalogue],
        evaluator: Callable[[DiscoveryScoreBundle], object],
    ) -> RefereeScoreBatch:
        return self._referee._score_all(  # noqa: SLF001 - capability delegation
            authority_id=self._authority_id,
            catalogues=catalogues,
            evaluator=evaluator,
        )


class ScoringReferee:
    """Own prefix seals, global close, and delayed one-shot score access."""

    def __init__(
        self,
        *,
        episode_id: str,
        expected_arm_ids: tuple[str, ...],
        halt_authority: HaltAuthority,
        bundle_store: BundleByteStore,
    ) -> None:
        if not isinstance(episode_id, str) or not episode_id.strip():
            raise RefereeProtocolError("episode_id must be a non-empty string")
        if (
            not expected_arm_ids
            or any(not isinstance(item, str) or not item.strip() for item in expected_arm_ids)
            or len(expected_arm_ids) != len(set(expected_arm_ids))
        ):
            raise RefereeProtocolError("expected arm identities must be unique and non-empty")
        self._episode_id = episode_id
        self._expected_arm_ids = expected_arm_ids
        self._halt_authority = halt_authority
        self._bundle_store = bundle_store
        self._seals: dict[str, list[PrefixSealReceipt]] = {
            arm_id: [] for arm_id in expected_arm_ids
        }
        self._catalogue_digests: dict[str, str] = {}
        self._close_receipt: CollectionCloseReceipt | None = None
        self._adjudicator_id: str | None = None
        self._score_started = False

    @property
    def episode_id(self) -> str:
        return self._episode_id

    @property
    def expected_arm_ids(self) -> tuple[str, ...]:
        return self._expected_arm_ids

    @property
    def is_closed(self) -> bool:
        return self._close_receipt is not None

    def _assert_active(self) -> None:
        if self._halt_authority.halted(self._episode_id):
            raise ScoringHalted("external halt authority stopped scoring")

    def actor_channel(self, arm_id: str) -> ActorSealChannel:
        if arm_id not in self._seals:
            raise RefereeProtocolError("actor arm is outside the expected collection")
        if self.is_closed:
            raise RefereeProtocolError("actor channels are globally closed")
        return ActorSealChannel(self, arm_id)

    def _submit(
        self,
        *,
        arm_id: str,
        bundle: DiscoveryScoreBundle,
        catalogue: ChallengeCatalogue,
    ) -> PrefixSealReceipt:
        self._assert_active()
        if self.is_closed:
            raise RefereeProtocolError("actor channels are globally closed")
        seals = self._seals[arm_id]
        expected_prefix = len(seals)
        if expected_prefix > 4 or bundle.prefix_index != expected_prefix:
            raise RefereeProtocolError("bundle is not the next prefix k=0..4")
        if bundle.arm_id != arm_id:
            raise RefereeProtocolError("bundle arm binding mismatch")
        expected_parent = None if not seals else seals[-1].bundle_digest
        if bundle.parent_bundle_digest != expected_parent:
            raise RefereeProtocolError("bundle parent does not bind the prior prefix")
        prior_catalogue_digest = self._catalogue_digests.get(arm_id)
        if (
            prior_catalogue_digest is not None
            and prior_catalogue_digest != catalogue.catalogue_digest
        ):
            raise RefereeProtocolError("arm challenge catalogue changed between prefixes")
        stored = self._bundle_store._seal_validated(  # noqa: SLF001
            bundle=bundle,
            catalogue=catalogue,
        )
        payload = {
            "episode_id": self._episode_id,
            "arm_id": arm_id,
            "prefix_index": bundle.prefix_index,
            "bundle_digest": stored.bundle_digest,
            "canonical_byte_digest": stored.canonical_byte_digest,
            "parent_bundle_digest": bundle.parent_bundle_digest,
        }
        receipt = PrefixSealReceipt(
            **payload,
            seal_digest=content_digest("score-prefix-seal/v1", payload),
        )
        self._catalogue_digests[arm_id] = catalogue.catalogue_digest
        seals.append(receipt)
        return receipt

    def close_actor_channels(self) -> CollectionCloseReceipt:
        self._assert_active()
        if self._close_receipt is not None:
            raise RefereeProtocolError("actor channels already have a global close")
        incomplete = {
            arm_id: len(self._seals[arm_id])
            for arm_id in self._expected_arm_ids
            if len(self._seals[arm_id]) != 5
        }
        if incomplete:
            raise RefereeProtocolError(
                f"global close requires exact prefix chains k=0..4: {incomplete}"
            )
        catalogue_digests = {
            self._catalogue_digests[arm_id] for arm_id in self._expected_arm_ids
        }
        if len(catalogue_digests) != 1:
            raise RefereeProtocolError("global close requires challenge catalogue parity")
        bundle_digests = tuple(
            seal.bundle_digest
            for arm_id in self._expected_arm_ids
            for seal in self._seals[arm_id]
        )
        payload = {
            "episode_id": self._episode_id,
            "expected_arm_ids": list(self._expected_arm_ids),
            "bundle_digests": list(bundle_digests),
            "bundle_count": len(bundle_digests),
        }
        receipt = CollectionCloseReceipt(
            episode_id=self._episode_id,
            expected_arm_ids=self._expected_arm_ids,
            bundle_digests=bundle_digests,
            bundle_count=len(bundle_digests),
            close_digest=content_digest("score-collection-close/v1", payload),
        )
        self._close_receipt = receipt
        return receipt

    def adjudicator_channel(self, *, authority_id: str) -> AdjudicatorScoreChannel:
        self._assert_active()
        if self._close_receipt is None:
            raise RefereeProtocolError("scoring requires a global close")
        if not isinstance(authority_id, str) or not authority_id.strip():
            raise RefereeProtocolError("adjudicator authority_id must be non-empty")
        if self._adjudicator_id is None:
            self._adjudicator_id = authority_id
        elif self._adjudicator_id != authority_id:
            raise RefereeProtocolError("adjudicator authority identity changed")
        return AdjudicatorScoreChannel(self, authority_id)

    def _score_all(
        self,
        *,
        authority_id: str,
        catalogues: Mapping[str, ChallengeCatalogue],
        evaluator: Callable[[DiscoveryScoreBundle], object],
    ) -> RefereeScoreBatch:
        self._assert_active()
        if self._close_receipt is None:
            raise RefereeProtocolError("scoring requires a global close")
        if authority_id != self._adjudicator_id:
            raise RefereeProtocolError("adjudicator authority identity mismatch")
        if self._score_started:
            raise RefereeProtocolError("one-shot scoring attempt already consumed")
        self._score_started = True
        if set(catalogues) != set(self._expected_arm_ids):
            raise RefereeProtocolError("catalogues must cover every expected arm exactly")
        for arm_id in self._expected_arm_ids:
            if catalogue := catalogues.get(arm_id):
                if catalogue.catalogue_digest != self._catalogue_digests[arm_id]:
                    raise RefereeProtocolError("scoring catalogue does not match sealed bytes")
            else:  # pragma: no cover - exact key-set check above catches this
                raise RefereeProtocolError("scoring catalogue is unavailable")

        reader = self._bundle_store._reader_for(  # noqa: SLF001
            self._close_receipt.bundle_digests
        )
        materialized: list[tuple[str, DiscoveryScoreBundle]] = []
        for arm_id in self._expected_arm_ids:
            for seal in self._seals[arm_id]:
                self._assert_active()
                materialized.append(
                    (
                        arm_id,
                        reader.materialize(
                            bundle_digest=seal.bundle_digest,
                            catalogue=catalogues[arm_id],
                        ),
                    )
                )

        scored: list[ScoredBundle] = []
        for arm_id, bundle in materialized:
            self._assert_active()
            score_value = evaluator(bundle)
            scored.append(
                ScoredBundle(
                    arm_id=arm_id,
                    prefix_index=bundle.prefix_index,
                    bundle_digest=bundle.bundle_digest,
                    score_value=score_value,
                )
            )
        return RefereeScoreBatch(
            episode_id=self._episode_id,
            authority_id=authority_id,
            close_digest=self._close_receipt.close_digest,
            scored_bundles=tuple(scored),
        )
