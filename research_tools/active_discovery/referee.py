from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Protocol

from .budget import BudgetLedger
from .canonical import content_digest
from .contracts import ProbeObservation, ProbeRequest, PublicEnvironmentDescriptor


class RefereeError(RuntimeError):
    """Base class for sealed-referee protocol failures."""


class RefereeNotSealed(RefereeError):
    """Hidden scoring was requested before a final immutable seal."""


class RefereeAlreadySealed(RefereeError):
    """The session is immutable after its one final seal."""


class ProbeHalted(RefereeError):
    """The external correction seam halted this episode."""


class ProbeRejected(RefereeError):
    """A probe violated episode, state, operation, or sequence binding."""


@dataclass(frozen=True, slots=True)
class HiddenScore:
    score_micros: int
    details_digest: str


@dataclass(frozen=True, slots=True)
class SealReceipt:
    episode_id: str
    bundle_digest: str
    transcript_digest: str
    budget_ledger_digest: str
    seal_digest: str


class HaltAuthority(Protocol):
    def halted(self, episode_id: str) -> bool: ...


class HiddenAdapter(Protocol):
    def public_descriptor(self) -> PublicEnvironmentDescriptor: ...

    def state_digest(self) -> str: ...

    def execute(self, request: ProbeRequest) -> ProbeObservation: ...

    def hidden_score(
        self, bundle_digest: str, transcript: tuple[ProbeObservation, ...]
    ) -> HiddenScore: ...


class SealedRefereeSession:
    """Only protocol surface between an actor loop and hidden family logic."""

    def __init__(
        self,
        *,
        episode_id: str,
        adapter: HiddenAdapter,
        budget: BudgetLedger,
        halt_authority: HaltAuthority,
    ) -> None:
        if not episode_id:
            raise RefereeError("episode_id must be non-empty")
        self._episode_id = episode_id
        self._adapter = adapter
        self._budget = budget
        self._halt_authority = halt_authority
        self._transcript: tuple[ProbeObservation, ...] = ()
        self._seal_receipt: SealReceipt | None = None

    @property
    def descriptor(self) -> PublicEnvironmentDescriptor:
        return self._adapter.public_descriptor()

    @property
    def transcript(self) -> tuple[ProbeObservation, ...]:
        return self._transcript

    def probe(self, request: ProbeRequest) -> ProbeObservation:
        if self._seal_receipt is not None:
            raise RefereeAlreadySealed("sealed referee cannot execute more probes")
        if request.episode_id != self._episode_id:
            raise ProbeRejected("probe episode binding mismatch")
        if request.step_index != len(self._transcript):
            raise ProbeRejected("probe step index is not the next transcript position")
        if self._halt_authority.halted(self._episode_id):
            raise ProbeHalted("external halt authority blocked the probe")
        before_state = self._adapter.state_digest()
        if request.expected_state_digest != before_state:
            raise ProbeRejected("probe expected state digest is stale")
        if request.operation_id != self.descriptor.operation_id:
            raise ProbeRejected("probe operation is not in the public descriptor")

        self._budget.reserve(
            f"{self._episode_id}:{request.step_index}:{request.request_digest}",
            request.cost_units,
        )
        observation = self._adapter.execute(request)
        if (
            observation.episode_id != self._episode_id
            or observation.step_index != request.step_index
            or observation.probe_id != request.probe_id
            or observation.before_state_digest != before_state
            or observation.after_state_digest != self._adapter.state_digest()
        ):
            raise ProbeRejected("adapter observation binding mismatch")
        self._transcript = (*self._transcript, observation)
        return observation

    def seal(self, *, bundle_digest: str) -> SealReceipt:
        if self._seal_receipt is not None:
            raise RefereeAlreadySealed("referee session is already sealed")
        if re.fullmatch(r"[0-9a-f]{64}", bundle_digest) is None:
            raise RefereeError("bundle_digest must be a lowercase SHA-256 digest")
        transcript_digest = content_digest(
            "probe-transcript",
            [asdict(observation) for observation in self._transcript],
        )
        payload = {
            "episode_id": self._episode_id,
            "bundle_digest": bundle_digest,
            "transcript_digest": transcript_digest,
            "budget_ledger_digest": self._budget.ledger_digest,
        }
        receipt = SealReceipt(
            **payload,
            seal_digest=content_digest("referee-seal", payload),
        )
        self._seal_receipt = receipt
        return receipt

    def score_sealed(self) -> HiddenScore:
        if self._seal_receipt is None:
            raise RefereeNotSealed(
                "hidden score is unavailable until final bundle is sealed"
            )
        return self._adapter.hidden_score(
            self._seal_receipt.bundle_digest,
            self._transcript,
        )
