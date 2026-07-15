from __future__ import annotations

import pytest

from research_tools.active_discovery.budget import BudgetExceeded, BudgetLedger
from research_tools.active_discovery.contracts import (
    ProbeObservation,
    ProbeRequest,
    PublicEnvironmentDescriptor,
)
from research_tools.active_discovery.referee import (
    HiddenScore,
    ProbeHalted,
    RefereeAlreadySealed,
    RefereeNotSealed,
    SealedRefereeSession,
)


class _NeverHalted:
    def halted(self, episode_id: str) -> bool:
        return False


class _AlwaysHalted:
    def halted(self, episode_id: str) -> bool:
        return True


class _FakeAdapter:
    def __init__(self) -> None:
        self.calls = 0
        self._state_digest = "1" * 64

    def public_descriptor(self) -> PublicEnvironmentDescriptor:
        return PublicEnvironmentDescriptor.create(
            environment_id="env_opaque",
            operation_id="op_opaque",
            schema={"fields": {}},
            documentation_fragments=("opaque development fixture",),
            initial_state_digest=self._state_digest,
        )

    def state_digest(self) -> str:
        return self._state_digest

    def execute(self, request: ProbeRequest) -> ProbeObservation:
        self.calls += 1
        return ProbeObservation.create(
            episode_id=request.episode_id,
            step_index=request.step_index,
            probe_id=request.probe_id,
            status_code=0,
            stdout="ok",
            stderr="",
            output={},
            before_state_digest=self._state_digest,
            after_state_digest=self._state_digest,
        )

    def hidden_score(
        self, bundle_digest: str, transcript: tuple[ProbeObservation, ...]
    ) -> HiddenScore:
        return HiddenScore(score_micros=500_000, details_digest="2" * 64)


def _request(expected_state_digest: str = "1" * 64) -> ProbeRequest:
    return ProbeRequest.from_mapping(
        {
            "episode_id": "episode-1",
            "arm_id": "ACTIVE_VOI",
            "step_index": 0,
            "probe_id": "probe-1",
            "operation_id": "op_opaque",
            "payload_json": "{}",
            "expected_state_digest": expected_state_digest,
            "cost_units": 1,
        }
    )


def test_hidden_score_is_unavailable_before_final_bundle_seal() -> None:
    session = SealedRefereeSession(
        episode_id="episode-1",
        adapter=_FakeAdapter(),
        budget=BudgetLedger(1),
        halt_authority=_NeverHalted(),
    )

    with pytest.raises(RefereeNotSealed, match="sealed"):
        session.score_sealed()


def test_final_seal_binds_bundle_transcript_and_budget_before_score() -> None:
    session = SealedRefereeSession(
        episode_id="episode-1",
        adapter=_FakeAdapter(),
        budget=BudgetLedger(1),
        halt_authority=_NeverHalted(),
    )

    receipt = session.seal(bundle_digest="3" * 64)
    score = session.score_sealed()

    assert receipt.bundle_digest == "3" * 64
    assert receipt.transcript_digest != receipt.budget_ledger_digest
    assert score.score_micros == 500_000


def test_budget_exhaustion_is_checked_before_adapter_call() -> None:
    adapter = _FakeAdapter()
    session = SealedRefereeSession(
        episode_id="episode-1",
        adapter=adapter,
        budget=BudgetLedger(0),
        halt_authority=_NeverHalted(),
    )

    with pytest.raises(BudgetExceeded):
        session.probe(_request())

    assert adapter.calls == 0


def test_external_halt_is_checked_before_budget_and_adapter_call() -> None:
    adapter = _FakeAdapter()
    budget = BudgetLedger(1)
    session = SealedRefereeSession(
        episode_id="episode-1",
        adapter=adapter,
        budget=budget,
        halt_authority=_AlwaysHalted(),
    )

    with pytest.raises(ProbeHalted, match="halt"):
        session.probe(_request())

    assert adapter.calls == 0
    assert budget.consumed_units == 0


def test_seal_closes_the_probe_channel() -> None:
    adapter = _FakeAdapter()
    session = SealedRefereeSession(
        episode_id="episode-1",
        adapter=adapter,
        budget=BudgetLedger(1),
        halt_authority=_NeverHalted(),
    )
    session.seal(bundle_digest="3" * 64)

    with pytest.raises(RefereeAlreadySealed, match="sealed"):
        session.probe(_request())

    assert adapter.calls == 0
