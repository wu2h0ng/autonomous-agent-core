from __future__ import annotations

import json
from dataclasses import replace
import subprocess
from typing import Any, cast

import pytest

from research_tools.active_discovery.actor_loop import (
    ActorLoopReceipt,
    ActorLoopError,
    DockerActorPort,
    ExhaustiveConfigurationDomainManifest,
    HiddenConfigurationPolicyTrace,
    audit_static_voi_reduction,
    run_actor_loop,
    trusted_docker_actor_port,
)
from research_tools.active_discovery.canonical import canonical_json, content_digest
from research_tools.active_discovery.catalogue import VisibleProbeCandidate
from research_tools.active_discovery.contracts import (
    ProbeObservation,
    ProbeRequest,
    PublicEnvironmentDescriptor,
)
from research_tools.active_discovery.scoring_contracts import (
    BehaviorTrace,
    ChallengeCatalogue,
    ChallengeSequence,
    ChallengeStep,
    OutcomeAtom,
    StatefulTestAssertion,
    StatefulTestCase,
    StatefulTestIR,
    StatefulTestStep,
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
            payload_json=canonical_json({"x": index}),
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


def _test_ir_mapping() -> dict[str, object]:
    test_ir = StatefulTestIR(
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
    return test_ir.to_mapping()


def _actor_source(
    catalogue: ChallengeCatalogue,
    *,
    stale_binding: bool = False,
    constant_material_update: bool = False,
    length_only_update: bool = False,
) -> bytes:
    challenge = catalogue.sequences[0]
    probabilities = [
        {"trace_digest": trace.trace_digest, "probability_micros": 500_000}
        for trace in challenge.traces
    ]
    fixed = {
        "challenge_digest": challenge.challenge_digest,
        "probabilities": probabilities,
        "predicted_trace_digest": min(
            item["trace_digest"] for item in probabilities
        ),
    }
    source = f"""
import json
import sys

request = json.loads(sys.stdin.buffer.read())
expected_keys = {{
    "schema_version", "public_descriptor", "legal_probe_payloads",
    "prefix_observations", "transcript_prefix_digest"
}}
if set(request) != expected_keys:
    raise SystemExit(41)
legal = request["legal_probe_payloads"]
observations = request["prefix_observations"]
descriptor_keys = {{
    "schema_version", "descriptor_digest", "operation_id", "schema_json",
    "documentation_fragments", "initial_state_digest"
}}
observation_keys = {{
    "step_index", "probe_id", "outcome_label", "state_relation",
    "before_state_digest", "after_state_digest", "public_observation_digest"
}}
if set(request["public_descriptor"]) != descriptor_keys:
    raise SystemExit(42)
if any(set(item) != observation_keys for item in observations):
    raise SystemExit(43)
k = len(observations)
if k == 0 or {constant_material_update!r}:
    delta = 0
elif {length_only_update!r}:
    delta = k * 1000
else:
    delta = int(request["transcript_prefix_digest"][:5], 16) % 400000 + 1
hypotheses = [
    {{"hypothesis_id": "actor-h-a", "description": "accepts boundary", "probability_micros": 500000 + delta}},
    {{"hypothesis_id": "actor-h-b", "description": "rejects boundary", "probability_micros": 500000 - delta}},
]
likelihoods = []
for probe in legal:
    for hypothesis in hypotheses:
        positive = 900000 if hypothesis["hypothesis_id"].endswith("a") else 100000
        likelihoods.append({{
            "probe_id": probe["probe_id"],
            "hypothesis_id": hypothesis["hypothesis_id"],
            "outcomes": [
                {{"outcome_label": "ZERO", "probability_micros": positive}},
                {{"outcome_label": "NONZERO", "probability_micros": 1000000 - positive}},
            ],
        }})
binding = {json.dumps(_digest("stale-transcript"))} if {stale_binding!r} else request["transcript_prefix_digest"]
disposition = "ABSTAIN_INSUFFICIENT_EVIDENCE" if k == 0 else "MATERIAL_UPDATE"
output = {{
    "hypotheses": hypotheses,
    "probe_likelihoods": likelihoods,
    "selected_probe_id": legal[0]["probe_id"],
    "predictions": [{json.dumps(fixed, sort_keys=True)}],
    "test_ir": {json.dumps(_test_ir_mapping(), sort_keys=True)},
    "evidence_binding": {{
        "transcript_prefix_digest": binding,
        "update_disposition": disposition,
    }},
}}
sys.stdout.write(json.dumps(output, sort_keys=True, separators=(",", ":")))
"""
    return source.encode("utf-8")


def _port(source: bytes) -> DockerActorPort:
    return trusted_docker_actor_port(actor_artifact_bytes=source)


class _Executor:
    def __init__(
        self,
        *,
        stdout: str = "ok",
        stderr: str = "",
        output: object | None = None,
    ) -> None:
        self.requests: list[ProbeRequest] = []
        self.stdout = stdout
        self.stderr = stderr
        self.output = {"accepted": True} if output is None else output

    def __call__(self, request: ProbeRequest) -> ProbeObservation:
        self.requests.append(request)
        assert isinstance(self.output, dict)
        return ProbeObservation.create(
            episode_id=request.episode_id,
            step_index=request.step_index,
            probe_id=request.probe_id,
            status_code=0,
            stdout=self.stdout,
            stderr=self.stderr,
            output=self.output,
            before_state_digest=request.expected_state_digest,
            after_state_digest=_digest(f"state-{request.step_index + 1}"),
        )


def _run(
    *,
    candidates: tuple[VisibleProbeCandidate, ...],
    actor_port: DockerActorPort | None = None,
    executor: _Executor | None = None,
) -> ActorLoopReceipt:
    descriptor = _descriptor()
    catalogue = _challenge_catalogue(descriptor)
    return run_actor_loop(
        experiment_id="R-ACTIVE-DISCOVERY-1",
        episode_id="episode-1",
        arm_id="ACTIVE_VOI",
        descriptor=descriptor,
        candidates=candidates,
        challenge_catalogue=catalogue,
        actor_port=actor_port or _port(_actor_source(catalogue)),
        execute_probe=executor or _Executor(),
        probe_budget=4,
    )


def test_actor_uses_fresh_hardened_containers_and_public_projection_only() -> None:
    descriptor = _descriptor()
    catalogue = _challenge_catalogue(descriptor)
    port = _port(_actor_source(catalogue))
    executor = _Executor()

    receipt = run_actor_loop(
        experiment_id="R-ACTIVE-DISCOVERY-1",
        episode_id="episode-1",
        arm_id="ACTIVE_VOI",
        descriptor=descriptor,
        candidates=_candidates(environment_hypothesis_prefix="oracle-alpha"),
        challenge_catalogue=catalogue,
        actor_port=port,
        execute_probe=executor,
        probe_budget=4,
    )

    assert tuple(bundle.prefix_index for bundle in receipt.prefix_bundles) == tuple(range(5))
    assert receipt.selected_probe_ids == ("probe-0", "probe-1", "probe-2", "probe-3")
    assert len(receipt.actor_invocation_receipts) == 18
    assert len({item.container_id for item in receipt.actor_invocation_receipts}) == 18
    assert all(
        item.actor_artifact_digest == port.actor_artifact_digest
        and item.resolved_image_id == port.resolved_image_id
        and item.allowed_projection_digest == port.allowed_projection_digest
        and item.network_mode == "none"
        and item.rootfs_read_only
        and item.cap_drop_all
        and item.no_new_privileges
        and item.cleanup_absent
        for item in receipt.actor_invocation_receipts
    )
    assert len(executor.requests) == 4


def test_environment_preloaded_predictions_and_hypothesis_ids_cannot_change_actor() -> None:
    first = _run(candidates=_candidates(environment_hypothesis_prefix="environment-a"))
    second = _run(candidates=_candidates(environment_hypothesis_prefix="environment-b"))

    assert first.selected_probe_ids == second.selected_probe_ids
    assert tuple(bundle.canonical_bytes for bundle in first.prefix_bundles) == tuple(
        bundle.canonical_bytes for bundle in second.prefix_bundles
    )


def test_raw_observation_channels_are_not_projected_to_actor() -> None:
    receipt = _run(
        candidates=_candidates(environment_hypothesis_prefix="environment"),
        executor=_Executor(
            stdout="oracle score=9",
            stderr="hidden-family",
            output={"outer": {"configuration_truth": "x"}},
        ),
    )
    assert receipt.selected_probe_ids == ("probe-0", "probe-1", "probe-2", "probe-3")


def test_actor_rejects_stale_constant_and_same_length_transcript_ignorance() -> None:
    descriptor = _descriptor()
    catalogue = _challenge_catalogue(descriptor)
    candidates = _candidates(environment_hypothesis_prefix="environment")

    with pytest.raises(ActorLoopError, match="transcript evidence binding"):
        _run(candidates=candidates, actor_port=_port(_actor_source(catalogue, stale_binding=True)))

    with pytest.raises(ActorLoopError, match="material update"):
        _run(
            candidates=candidates,
            actor_port=_port(_actor_source(catalogue, constant_material_update=True)),
        )

    with pytest.raises(ActorLoopError, match="same-length counterfactual"):
        _run(
            candidates=candidates,
            actor_port=_port(_actor_source(catalogue, length_only_update=True)),
        )


def test_docker_policy_is_fixed_has_no_host_mount_and_cleanup_is_real() -> None:
    descriptor = _descriptor()
    catalogue = _challenge_catalogue(descriptor)
    port = _port(_actor_source(catalogue))
    joined = " ".join(port.docker_security_args)
    for required in (
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--pids-limit 32",
        "--memory 64m",
        "--memory-swap 64m",
        "--cpus 0.5",
    ):
        assert required in joined
    for forbidden in ("--mount", "--volume", "-v", "docker.sock", "--privileged"):
        assert forbidden not in port.docker_security_args
    with pytest.raises(TypeError):
        cast(Any, trusted_docker_actor_port)(
            actor_artifact_bytes=_actor_source(catalogue), image="alpine:latest"
        )

    run_receipt = _run(
        candidates=_candidates(environment_hypothesis_prefix="environment"),
        actor_port=port,
    )
    assert all(item.cleanup_absent for item in run_receipt.actor_invocation_receipts)
    for item in run_receipt.actor_invocation_receipts:
        assert subprocess.run(
            ["docker", "container", "inspect", item.container_id],
            capture_output=True,
            check=False,
        ).returncode != 0


def _domain_manifest(configuration_digests: tuple[str, ...]) -> ExhaustiveConfigurationDomainManifest:
    return ExhaustiveConfigurationDomainManifest.create(
        domain_definition_digest=_digest("legal-domain-definition"),
        configuration_digests=configuration_digests,
        declared_cardinality=len(configuration_digests),
        enumeration_certificate_digest=_digest("exhaustive-enumeration-certificate"),
    )


def test_static_reduction_requires_exhaustive_manifest_and_parks_only_exact_domain() -> None:
    digests = tuple(_digest(f"config-{index}") for index in range(3))
    manifest = _domain_manifest(digests)
    equal_domain = tuple(
        HiddenConfigurationPolicyTrace(
            configuration_digest=digest,
            voi_probe_ids=("probe-0", "probe-1", "probe-2", "probe-3"),
            systematic_probe_ids=("probe-0", "probe-1", "probe-2", "probe-3"),
        )
        for digest in digests
    )
    parked = audit_static_voi_reduction(
        manifest=manifest,
        policy_traces=equal_domain,
    )

    assert parked.disposition == "NEEDS_INDEPENDENT_DOMAIN_CERTIFICATE"
    assert parked.domain_manifest_digest == manifest.manifest_digest

    with pytest.raises(ActorLoopError, match="exact exhaustive domain"):
        audit_static_voi_reduction(manifest=manifest, policy_traces=equal_domain[:-1])
    with pytest.raises(ActorLoopError, match="at least two"):
        _domain_manifest((_digest("singleton"),))

    changed = replace(
        equal_domain[-1],
        voi_probe_ids=("probe-1", "probe-0", "probe-2", "probe-3"),
    )
    not_reduced = audit_static_voi_reduction(
        manifest=manifest,
        policy_traces=(*equal_domain[:-1], changed),
    )
    assert not_reduced.disposition == "ACTIVE_ADAPTATION_NOT_STATICALLY_REDUCED"
    assert not_reduced.counterexample_configuration_digests == (
        changed.configuration_digest,
    )
