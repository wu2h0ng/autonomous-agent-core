from __future__ import annotations

from dataclasses import replace

import pytest

from research_tools.active_discovery.scoring_contracts import (
    BehaviorTrace,
    ChallengeSequence,
    ChallengeStep,
    OutcomeAtom,
)
from research_tools.active_discovery.trace_universe_verifier import (
    TraceUniverseError,
    TraceWitness,
    verify_trace_universe,
)


def _trace(value: int) -> BehaviorTrace:
    return BehaviorTrace(
        atoms=(
            OutcomeAtom.create(
                status_code=0,
                stdout=str(value),
                stderr="",
                output={"value": value},
                state_relation="SAME",
            ),
        )
    )


def _challenge(count: int) -> ChallengeSequence:
    traces = tuple(sorted((_trace(i) for i in range(count)), key=lambda t: t.canonical_bytes))
    return ChallengeSequence.create(
        reset_slot="clean",
        steps=(ChallengeStep.create(operation_id="op", payload={"x": 1}),),
        traces=traces,
    )


def _verify(count: int):  # type: ignore[no-untyped-def]
    challenge = _challenge(count)
    configs = tuple(f"{index:064x}" for index in range(count))
    witnesses = tuple(
        TraceWitness(
            configuration_digest=configs[index],
            trace=challenge.traces[index],
            clean_reset=True,
        )
        for index in range(count)
    )
    return verify_trace_universe(
        domain_manifest_digest="a" * 64,
        challenge=challenge,
        verifier_source_digest="b" * 64,
        expected_configuration_digests=configs,
        witnesses=witnesses,
    )


@pytest.mark.parametrize("count", (2, 16))
def test_full_domain_certificate_accepts_literal_boundaries(count: int) -> None:
    certificate = _verify(count)

    assert certificate.configuration_count == count
    assert certificate.deduplicated_trace_count == count
    assert len(certificate.ordered_trace_encodings) == count
    assert certificate.certificate_digest != "0" * 64
    assert not hasattr(certificate, "configuration_to_trace")


def test_verifier_rejects_one_and_seventeen_deduplicated_traces() -> None:
    for count in (1, 17):
        challenge = _challenge(count)
        configs = tuple(f"{index:064x}" for index in range(count))
        witnesses = tuple(
            TraceWitness(configs[index], challenge.traces[index], True)
            for index in range(count)
        )
        with pytest.raises(TraceUniverseError, match="2-16"):
            verify_trace_universe(
                domain_manifest_digest="a" * 64,
                challenge=challenge,
                verifier_source_digest="b" * 64,
                expected_configuration_digests=configs,
                witnesses=witnesses,
            )


def test_verifier_requires_both_completeness_directions_and_clean_resets() -> None:
    challenge = _challenge(2)
    configs = ("1" * 64, "2" * 64)
    only_one = (TraceWitness(configs[0], challenge.traces[0], True),)
    with pytest.raises(TraceUniverseError, match="configuration witness"):
        verify_trace_universe(
            domain_manifest_digest="a" * 64,
            challenge=challenge,
            verifier_source_digest="b" * 64,
            expected_configuration_digests=configs,
            witnesses=only_one,
        )

    unwitnessed_public_trace = (
        TraceWitness(configs[0], challenge.traces[0], True),
        TraceWitness(configs[1], challenge.traces[0], True),
    )
    with pytest.raises(TraceUniverseError, match="public trace"):
        verify_trace_universe(
            domain_manifest_digest="a" * 64,
            challenge=challenge,
            verifier_source_digest="b" * 64,
            expected_configuration_digests=configs,
            witnesses=unwitnessed_public_trace,
        )

    dirty = (
        TraceWitness(configs[0], challenge.traces[0], True),
        TraceWitness(configs[1], challenge.traces[1], False),
    )
    with pytest.raises(TraceUniverseError, match="clean reset"):
        verify_trace_universe(
            domain_manifest_digest="a" * 64,
            challenge=challenge,
            verifier_source_digest="b" * 64,
            expected_configuration_digests=configs,
            witnesses=dirty,
        )


def test_verifier_rejects_out_of_universe_and_wrong_step_cardinality() -> None:
    challenge = _challenge(2)
    configs = ("1" * 64, "2" * 64)
    outside = _trace(9)
    with pytest.raises(TraceUniverseError, match="outside public trace universe"):
        verify_trace_universe(
            domain_manifest_digest="a" * 64,
            challenge=challenge,
            verifier_source_digest="b" * 64,
            expected_configuration_digests=configs,
            witnesses=(
                TraceWitness(configs[0], challenge.traces[0], True),
                TraceWitness(configs[1], outside, True),
            ),
        )

    wrong_length = replace(
        challenge.traces[1], atoms=challenge.traces[1].atoms * 2
    )
    with pytest.raises(TraceUniverseError, match="step count"):
        verify_trace_universe(
            domain_manifest_digest="a" * 64,
            challenge=challenge,
            verifier_source_digest="b" * 64,
            expected_configuration_digests=configs,
            witnesses=(
                TraceWitness(configs[0], challenge.traces[0], True),
                TraceWitness(configs[1], wrong_length, True),
            ),
        )
