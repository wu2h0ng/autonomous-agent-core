"""Direct Responses actor candidate tests. No test performs a network call."""

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from experiments.r_state_credit_1.ark_responses_actor import (
    ARK_AGENT_PLAN_BASE_PROFILE,
    ARK_CREDENTIAL_ENV_REF,
    ARK_MODEL_ALIAS,
    ARK_RESPONSES_PATH,
    ActorClientFailure,
    ActorFailureCategory,
    ArkResponsesActorClient,
    ResponsesHttpResponse,
)
from experiments.r_state_credit_1.contracts import ArmId, ProbeAction, canonical_json
from experiments.r_state_credit_1.run_contracts import (
    ActorBinding,
    ActorCostStatus,
    ActorRequest,
    ActorTransport,
)


SYSTEM_PROMPT = "Return one closed action object."
TOOL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action"],
    "properties": {"action": {"enum": [item.value for item in ProbeAction]}},
}


def _binding() -> ActorBinding:
    return ActorBinding(
        transport=ActorTransport.API_ONLY,
        provider="volcengine-ark-agent-plan",
        base_profile=ARK_AGENT_PLAN_BASE_PROFILE,
        responses_path=ARK_RESPONSES_PATH,
        credential_env_ref=ARK_CREDENTIAL_ENV_REF,
        model_id=ARK_MODEL_ALIAS,
        model_revision_or_snapshot=ARK_MODEL_ALIAS,
        temperature=0.0,
        top_p=1.0,
        max_output_tokens=256,
        request_timeout_seconds=30.0,
        system_prompt_sha256=hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
        tool_schema_sha256=hashlib.sha256(
            canonical_json(TOOL_SCHEMA).encode("utf-8")
        ).hexdigest(),
    )


def _request(binding: ActorBinding) -> ActorRequest:
    return ActorRequest(
        request_id="run:episode:checkpoint:A0",
        run_id="run-1",
        episode_id="episode-1",
        checkpoint_id="BEFORE_PERTURBATION",
        arm_id=ArmId.A0_FULL_LOG,
        observable_digest="c" * 64,
        representation="visible repository state",
        allowed_actions=tuple(ProbeAction),
        tool_schema_sha256=binding.tool_schema_sha256,
    )


class _FakeTransport:
    def __init__(
        self,
        response: ResponsesHttpResponse | None = None,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[str, dict[str, str], bytes, float]] = []

    def post(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> ResponsesHttpResponse:
        self.calls.append((url, headers, body, timeout_seconds))
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def _success_body(*, model: str = ARK_MODEL_ALIAS) -> bytes:
    return (
        json.dumps(
            {
                "id": "resp_candidate_001",
                "status": "completed",
                "model": model,
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"action":"REVIEW"}',
                            }
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 17,
                    "output_tokens": 5,
                    "total_tokens": 22,
                },
                "error": None,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _client(
    transport: _FakeTransport,
    *,
    environ: dict[str, str] | None = None,
) -> ArkResponsesActorClient:
    return ArkResponsesActorClient(
        binding=_binding(),
        system_prompt=SYSTEM_PROMPT,
        tool_schema=TOOL_SCHEMA,
        transport=transport,
        environ={} if environ is None else environ,
    )


def test_ark_actor_binding_is_direct_api_env_only_and_immutable() -> None:
    binding = _binding()
    assert binding.base_profile == "https://ark.cn-beijing.volces.com/api/plan/v3"
    assert binding.responses_path == "/responses"
    assert binding.credential_env_ref == "ARK_API_KEY"
    assert binding.model_id == "ark-code-latest"
    assert "api_key" not in binding.to_mapping()
    with pytest.raises(FrozenInstanceError):
        binding.base_profile = "changed"  # type: ignore[misc]
    with pytest.raises(Exception, match="unknown field"):
        ActorBinding.from_mapping({**binding.to_mapping(), "api_key": "secret"})


def test_missing_credential_fails_before_transport_and_never_exposes_a_secret() -> None:
    transport = _FakeTransport(
        ResponsesHttpResponse(status=200, headers={}, body=_success_body())
    )
    client = _client(transport)
    with pytest.raises(ActorClientFailure) as raised:
        client.complete(_request(client.binding))
    assert raised.value.category is ActorFailureCategory.CREDENTIAL_MISSING
    assert raised.value.error_code == "ARK_API_KEY_MISSING"
    assert raised.value.response_sha256 is None
    assert transport.calls == []
    assert "Bearer" not in repr(raised.value)


def test_direct_responses_success_is_closed_and_digest_bound() -> None:
    body = _success_body()
    transport = _FakeTransport(
        ResponsesHttpResponse(
            status=200,
            headers={"x-request-id": "request-001"},
            body=body,
        )
    )
    client = _client(transport, environ={"ARK_API_KEY": "tests-only-secret"})
    request = _request(client.binding)
    response = client.complete(request)

    assert response.request_id == request.request_id
    assert response.response_id == "resp_candidate_001"
    assert response.model_id == ARK_MODEL_ALIAS
    assert response.action is ProbeAction.REVIEW
    assert response.actor_request_sha256 == request.digest()
    assert response.provider_response_sha256 == hashlib.sha256(body).hexdigest()
    assert response.usage.input_tokens == 17
    assert response.usage.output_tokens == 5
    assert response.usage.total_tokens == 22
    assert response.cost.status is ActorCostStatus.UNAVAILABLE_NOT_GUESSED
    assert response.cost.amount_microunits is None
    assert response.error_code is None
    assert response.timed_out is False
    assert response.timeout_seconds == 30.0

    assert len(transport.calls) == 1
    url, headers, request_body, timeout = transport.calls[0]
    assert url == "https://ark.cn-beijing.volces.com/api/plan/v3/responses"
    assert headers["Authorization"] == "Bearer tests-only-secret"
    assert timeout == 30.0
    request_payload = json.loads(request_body)
    assert request_payload["model"] == ARK_MODEL_ALIAS
    assert request_payload["stream"] is False
    assert hashlib.sha256(request_body).hexdigest() == response.provider_request_sha256
    assert b"tests-only-secret" not in request_body


def test_response_model_identity_drift_fails_closed() -> None:
    body = _success_body(model="different-model")
    client = _client(
        _FakeTransport(ResponsesHttpResponse(status=200, headers={}, body=body)),
        environ={"ARK_API_KEY": "tests-only-secret"},
    )
    with pytest.raises(ActorClientFailure) as raised:
        client.complete(_request(client.binding))
    assert raised.value.category is ActorFailureCategory.SCHEMA_ERROR
    assert raised.value.error_code == "MODEL_IDENTITY_DRIFT"
    assert raised.value.response_sha256 == hashlib.sha256(body).hexdigest()


def test_http_error_is_typed_digest_only_and_secret_free() -> None:
    body = b'{"error":{"code":"rate_limit","message":"retry later"}}\n'
    client = _client(
        _FakeTransport(ResponsesHttpResponse(status=429, headers={}, body=body)),
        environ={"ARK_API_KEY": "tests-only-secret"},
    )
    with pytest.raises(ActorClientFailure) as raised:
        client.complete(_request(client.binding))
    failure = raised.value
    assert failure.category is ActorFailureCategory.HTTP_ERROR
    assert failure.http_status == 429
    assert failure.error_code == "rate_limit"
    assert failure.response_sha256 == hashlib.sha256(body).hexdigest()
    assert failure.timed_out is False
    assert "retry later" not in repr(failure)
    assert "tests-only-secret" not in repr(failure)


def test_timeout_is_typed_and_carries_exact_timeout_without_response_guessing() -> None:
    client = _client(
        _FakeTransport(error=TimeoutError("tests-only timeout")),
        environ={"ARK_API_KEY": "tests-only-secret"},
    )
    with pytest.raises(ActorClientFailure) as raised:
        client.complete(_request(client.binding))
    failure = raised.value
    assert failure.category is ActorFailureCategory.TIMEOUT
    assert failure.error_code == "RESPONSES_TIMEOUT"
    assert failure.timed_out is True
    assert failure.timeout_seconds == 30.0
    assert failure.response_sha256 is None


def test_committed_actor_candidate_binds_real_prompt_schema_and_stays_unrun() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    binding_root = repo_root / "experiments/r_state_credit_1/bindings"
    descriptor = json.loads(
        (binding_root / "ark-agent-plan-actor-candidate.json").read_text(
            encoding="utf-8"
        )
    )
    prompt = (binding_root / "system-prompt.txt").read_text(encoding="utf-8")
    schema = json.loads((binding_root / "tool-schema.json").read_text(encoding="utf-8"))
    candidate = ActorBinding.from_mapping(descriptor["actor_binding_candidate"])

    assert hashlib.sha256(prompt.encode("utf-8")).hexdigest() == (
        candidate.system_prompt_sha256
    )
    assert hashlib.sha256(canonical_json(schema).encode("utf-8")).hexdigest() == (
        candidate.tool_schema_sha256
    )
    transport = _FakeTransport()
    ArkResponsesActorClient(
        binding=candidate,
        system_prompt=prompt,
        tool_schema=schema,
        transport=transport,
        environ={},
    )
    assert transport.calls == []
    assert descriptor["connectivity_canary"]["status"] == "UNRUN"
    assert descriptor["connectivity_canary"]["provider_call_performed"] is False
    assert descriptor["status"].endswith("NOT_RUNNABLE")


def test_c7_and_run_authority_candidates_do_not_forge_acceptance() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    binding_root = repo_root / "experiments/r_state_credit_1/bindings"
    c7 = json.loads(
        (binding_root / "c7-signal-candidate.json").read_text(encoding="utf-8")
    )
    authority = json.loads(
        (binding_root / "run-authority-candidate.json").read_text(encoding="utf-8")
    )

    assert c7["per_run_bindings"]["owner_id"] == "UNBOUND_PER_RUN"
    assert c7["authority_boundary"]["actor_access"] == "FORBIDDEN"
    assert authority["founder_portfolio_authority"]["warning"] == (
        "PORTFOLIO_AUTHORITY_IS_NOT_A_PER_RUN_SIGNATURE"
    )
    assert authority["independent_reviewer_acceptance"] == "ABSENT"
    assert authority["c7_acceptance"] == "ABSENT"
    assert set(authority["per_run"].values()) == {"UNSIGNED"}
    assert authority["provider_call_authorized"] is False
    assert authority["result_bearing_execution_authorized"] is False
