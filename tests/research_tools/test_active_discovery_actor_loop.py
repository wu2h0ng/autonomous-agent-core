from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from research_tools.active_discovery.actor_loop import (
    ActorLoopError,
    ActorModelOutput,
    BehaviorHypothesis,
    HiddenConfigurationPolicyTrace,
    ProbeHypothesisLikelihood,
    audit_static_voi_reduction,
    run_actor_loop,
)
from research_tools.active_discovery.canonical import content_digest
from research_tools.active_discovery.catalogue import VisibleProbeCandidate
from research_tools.active_discovery.contracts import (
    ProbeObservation,
    ProbeRequest,
    PublicEnvironmentDescriptor,
)
from research_tools.active_discovery.scoring_contracts import (
    BehaviorTrace,
    ChallengeCatalogue,
    ChallengePrediction,
    ChallengeSequence,
    ChallengeStep,
    OutcomeAtom,
    StatefulTestAssertion,
    StatefulTestCase,
    StatefulTestIR,
    StatefulTestStep,
    TraceProbability,
)
from research_tools.active_discovery.selector import (
    HypothesisPrediction,
    OutcomeLikelihood,
)


def _digest(label: str) -> str:
    return content_digest("actor-loop-test", {"label": label})


def _descriptor() -> PublicEnvironmentDescriptor:
    return PublicEnvironmentDescriptor.create(
        environment_id="opaque-service",
        operation_id="apply",
        schema={"type": "object", "properties": {"x": {"type": "integer"}}},
        documentation_fragments=("The operation accepts an integer x.",),
        initial_state_digest=_digest("state-0"),
    )


def _challenge_catalogue(descriptor: PublicEnvironmentDescriptor) -> ChallengeCatalogue:
    traces = tuple(
        sorted(
            (
                BehaviorTrace(
                    atoms=(
                        OutcomeAtom.create(
                            status_code=0,
                            stdout=label,
                            stderr="",
                            output={"value": label},
                            state_relation="SAME",
                        ),
                    )
                )
                for label in ("accepted", "rejected")
            ),
            key=lambda item: item.canonical_bytes,
        )
    )
    return ChallengeCatalogue.create(
        instance_public_digest=descriptor.descriptor_digest,
        sequences=(
            ChallengeSequence.create(
                reset_slot="clean",
                steps=(ChallengeStep.create(operation_id="apply", payload={"x": 91}),),
                traces=traces,
            ),
        ),
        probe_sequence_digests=(),
    )


def _environment_prediction(
    hypothesis_id: str, *, positive_micros: int
) -> HypothesisPrediction:
    return HypothesisPrediction(
        hypothesis_id=hypothesis_id,
        outcomes=(
            OutcomeLikelihood("ZERO", positive_micros),
            OutcomeLikelihood("NONZERO", 1_000_000 - positive_micros),
        ),
    )


def _candidates(*, environment_hypothesis_prefix: str) -> tuple[VisibleProbeCandidate, ...]:
    return tuple(
        VisibleProbeCandidate(
            probe_id=f"probe-{index}",
            stable_order=index,
            payload_json=json.dumps({"x": index}, sort_keys=True, separators=(",", ":")),
            cost_units=1,
            zero_status_label="ZERO",
            nonzero_status_label="NONZERO",
            predictions=(
                _environment_prediction(
                    f"{environment_hypothesis_prefix}-weak", positive_micros=501_000
                ),
                _environment_prediction(
                    f"{environment_hypothesis_prefix}-strong", positive_micros=999_000
                ),
            ),
        )
        for index in range(5)
    )


def _test_ir() -> StatefulTestIR:
    return StatefulTestIR(
        tests=(
            StatefulTestCase.create(
                test_id="generated-boundary-test",
                reset_slot="generated-clean",
                steps=(
                    StatefulTestStep.create(
                        operation_id="apply",
                        payload={"x": -17},
                        assertions=(
                            StatefulTestAssertion.create(
                                source="STATUS_CODE", operator="EQ", expected=0
                            ),
                        ),
                    ),
                ),
                provenance_refs=("public-descriptor",),
            ),
        )
    )


class _GroundedModel:
    def __init__(self, catalogue: ChallengeCatalogue) -> None:
        self._challenge = catalogue.sequences[0]
        self.inputs: list[tuple[Any, Any, Any]] = []

    def __call__(self, descriptor: Any, legal_probes: Any, observations: Any) -> ActorModelOutput:
        self.inputs.append((descriptor, legal_probes, observations))
        hypotheses = (
            BehaviorHypothesis("actor-h-a", "accepts a boundary region", 500_000),
            BehaviorHypothesis("actor-h-b", "rejects a boundary region", 500_000),
        )
        likelihoods = tuple(
            ProbeHypothesisLikelihood(
                probe_id=probe.probe_id,
                hypothesis_id=hypothesis.hypothesis_id,
                outcomes=(
                    OutcomeLikelihood(
                        "ZERO", 900_000 if hypothesis.hypothesis_id.endswith("a") else 100_000
                    ),
                    OutcomeLikelihood(
                        "NONZERO",
                        100_000 if hypothesis.hypothesis_id.endswith("a") else 900_000,
                    ),
                ),
            )
            for probe in legal_probes
            for hypothesis in hypotheses
        )
        probabilities = tuple(
            TraceProbability(trace.trace_digest, 500_000)
            for trace in self._challenge.traces
        )
        return ActorModelOutput(
            hypotheses=hypotheses,
            probe_likelihoods=likelihoods,
            selected_probe_id=legal_probes[0].probe_id,
            predictions=(
                ChallengePrediction(
                    challenge_digest=self._challenge.challenge_digest,
                    probabilities=probabilities,
                    predicted_trace_digest=min(
                        probabilities,
                        key=lambda item: item.trace_digest,
                    ).trace_digest,
                ),
            ),
            test_ir=_test_ir(),
        )


class _Executor:
    def __init__(self) -> None:
        self.requests: list[ProbeRequest] = []

    def __call__(self, request: ProbeRequest) -> ProbeObservation:
        self.requests.append(request)
        after = _digest(f"state-{request.step_index + 1}")
        return ProbeObservation.create(
            episode_id=request.episode_id,
            step_index=request.step_index,
            probe_id=request.probe_id,
            status_code=0,
            stdout="ok",
            stderr="",
            output={"accepted": True},
            before_state_digest=request.expected_state_digest,
            after_state_digest=after,
        )


def _run(
    *,
    candidates: tuple[VisibleProbeCandidate, ...],
    model: Any | None = None,
) -> Any:
    descriptor = _descriptor()
    catalogue = _challenge_catalogue(descriptor)
    return run_actor_loop(
        experiment_id="R-ACTIVE-DISCOVERY-1",
        episode_id="episode-1",
        arm_id="ACTIVE_VOI",
        actor_binding_digest=_digest("fixed-model"),
        descriptor=descriptor,
        candidates=candidates,
        challenge_catalogue=catalogue,
        model_callback=model or _GroundedModel(catalogue),
        execute_probe=_Executor(),
        probe_budget=4,
    )


def test_actor_only_exposes_public_descriptor_payloads_and_prefix_observations() -> None:
    descriptor = _descriptor()
    catalogue = _challenge_catalogue(descriptor)
    model = _GroundedModel(catalogue)
    executor = _Executor()

    receipt = run_actor_loop(
        experiment_id="R-ACTIVE-DISCOVERY-1",
        episode_id="episode-1",
        arm_id="ACTIVE_VOI",
        actor_binding_digest=_digest("fixed-model"),
        descriptor=descriptor,
        candidates=_candidates(environment_hypothesis_prefix="oracle-alpha"),
        challenge_catalogue=catalogue,
        model_callback=model,
        execute_probe=executor,
        probe_budget=4,
    )

    assert tuple(bundle.prefix_index for bundle in receipt.prefix_bundles) == tuple(range(5))
    assert receipt.selected_probe_ids == ("probe-0", "probe-1", "probe-2", "probe-3")
    assert len(executor.requests) == 4
    # Determinism is checked by replaying the fixed callback for every exact input.
    assert len(model.inputs) == 10
    for descriptor_input, legal_probes, observations in model.inputs:
        assert descriptor_input is descriptor
        assert all(
            set(probe.to_mapping())
            == {"probe_id", "stable_order", "operation_id", "payload_json", "cost_units"}
            for probe in legal_probes
        )
        assert not any(
            environment_id in repr((legal_probes, observations))
            for environment_id in ("oracle-alpha-weak", "oracle-alpha-strong")
        )


def test_environment_preloaded_predictions_and_hypothesis_ids_cannot_change_actor() -> None:
    first = _run(candidates=_candidates(environment_hypothesis_prefix="environment-a"))
    second = _run(candidates=_candidates(environment_hypothesis_prefix="environment-b"))

    assert first.selected_probe_ids == second.selected_probe_ids
    assert tuple(bundle.canonical_bytes for bundle in first.prefix_bundles) == tuple(
        bundle.canonical_bytes for bundle in second.prefix_bundles
    )


def test_actor_fails_closed_on_oracle_shaped_callback_fields_and_nondeterminism() -> None:
    descriptor = _descriptor()
    catalogue = _challenge_catalogue(descriptor)
    valid_model = _GroundedModel(catalogue)

    def oracle_shaped(descriptor: Any, legal: Any, observations: Any) -> dict[str, Any]:
        raw = valid_model(descriptor, legal, observations).to_mapping()
        raw["hidden_family"] = "leak"
        return raw

    with pytest.raises(ActorLoopError, match="oracle-shaped"):
        _run(
            candidates=_candidates(environment_hypothesis_prefix="environment"),
            model=oracle_shaped,
        )

    calls = 0

    def unstable(descriptor: Any, legal: Any, observations: Any) -> ActorModelOutput:
        nonlocal calls
        calls += 1
        output = valid_model(descriptor, legal, observations)
        if calls % 2 == 0:
            return replace(output, selected_probe_id=legal[-1].probe_id)
        return output

    with pytest.raises(ActorLoopError, match="non-deterministic"):
        _run(
            candidates=_candidates(environment_hypothesis_prefix="environment"),
            model=unstable,
        )


def test_actor_rejects_non_voi_choice_from_model_generated_likelihoods() -> None:
    descriptor = _descriptor()
    catalogue = _challenge_catalogue(descriptor)
    valid_model = _GroundedModel(catalogue)

    def wrong_choice(descriptor: Any, legal: Any, observations: Any) -> ActorModelOutput:
        return replace(
            valid_model(descriptor, legal, observations),
            selected_probe_id=legal[-1].probe_id,
        )

    with pytest.raises(ActorLoopError, match="VOI choice"):
        _run(
            candidates=_candidates(environment_hypothesis_prefix="environment"),
            model=wrong_choice,
        )


def test_static_reduction_audit_parks_when_voi_equals_systematic_everywhere() -> None:
    equal_domain = tuple(
        HiddenConfigurationPolicyTrace(
            configuration_digest=_digest(f"config-{index}"),
            voi_probe_ids=("probe-0", "probe-1", "probe-2", "probe-3"),
            systematic_probe_ids=("probe-0", "probe-1", "probe-2", "probe-3"),
        )
        for index in range(3)
    )
    parked = audit_static_voi_reduction(equal_domain)

    assert parked.disposition == "PARK_ACTIVE_ADAPTATION"
    assert parked.all_configurations_equal
    assert parked.counterexample_configuration_digests == ()

    changed = replace(
        equal_domain[-1],
        voi_probe_ids=("probe-1", "probe-0", "probe-2", "probe-3"),
    )
    not_reduced = audit_static_voi_reduction((*equal_domain[:-1], changed))
    assert not_reduced.disposition == "ACTIVE_ADAPTATION_NOT_STATICALLY_REDUCED"
    assert not_reduced.counterexample_configuration_digests == (
        changed.configuration_digest,
    )
