from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from agent_os_contracts import (
    ProviderProfile,
    ProviderResponse,
    ProviderToolProposal,
    ProviderUsage,
)
from agent_os_core import ExecutionProfileError
from domain_packs.developer_agent import DeveloperRepositoryPatchProfile


def provider_profile(now: datetime) -> ProviderProfile:
    return ProviderProfile(
        profile_id="provider-profile:test",
        provider_id="deterministic",
        model_id="deterministic-v1",
        endpoint_class="test",
        credential_ref_id="credential:test",
        capabilities=("chat",),
        max_context_tokens=16000,
        request_timeout_seconds=60,
        created_at=now,
    )


def profile_context() -> dict[str, object]:
    return {
        "goal": "replace the fixture",
        "target_path": "fixture.txt",
        "workspace.read": {
            "content": "before\n",
            "sha256": "b" * 64,
        },
    }


def proposal(arguments: dict[str, object], *, proposal_id: str = "proposal:1") -> ProviderToolProposal:
    return ProviderToolProposal(
        proposal_id=proposal_id,
        capability_id="workspace.apply_patch",
        arguments_json=json.dumps(arguments),
    )


def response_with(
    *,
    text: str = "done",
    tool_proposals: tuple[ProviderToolProposal, ...] = (),
) -> ProviderResponse:
    return ProviderResponse(
        response_id="response:1",
        request_id="request:1",
        text=text,
        tool_proposals=tool_proposals,
        usage=ProviderUsage(
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            estimated_cost_usd=Decimal("0"),
        ),
        finish_reason="stop",
        received_at=datetime.now(timezone.utc),
    )


def test_profile_binds_reviewed_path_sha_and_only_patch_capability() -> None:
    now = datetime.now(timezone.utc)
    profile = DeveloperRepositoryPatchProfile()
    request = profile.build_provider_request(
        task_id="task:profile",
        run_id="run:profile",
        provider_profile=provider_profile(now),
        provider_capability="provider.chat",
        context={
            "goal": "replace the fixture",
            "target_path": "fixture.txt",
            "workspace.read": {
                "content": "before\n",
                "sha256": "b" * 64,
            },
        },
        now=now,
    )

    assert request.allowed_capability_ids == ("workspace.apply_patch",)
    assert "Target path: fixture.txt" in request.messages[0].content
    assert "Current SHA-256: " + "b" * 64 in request.messages[0].content
    assert request.task_id == "task:profile"
    assert request.run_id == "run:profile"
    assert request.provider_profile_id == "provider-profile:test"


def test_build_provider_request_requires_target_path() -> None:
    now = datetime.now(timezone.utc)
    profile = DeveloperRepositoryPatchProfile()
    context = profile_context()
    del context["target_path"]

    with pytest.raises(
        ExecutionProfileError,
        match="provider requires a target path and completed workspace.read",
    ):
        profile.build_provider_request(
            task_id="task:profile",
            run_id="run:profile",
            provider_profile=provider_profile(now),
            provider_capability="provider.chat",
            context=context,
            now=now,
        )


def test_build_provider_request_requires_read_output() -> None:
    now = datetime.now(timezone.utc)
    profile = DeveloperRepositoryPatchProfile()
    context = profile_context()
    del context["workspace.read"]

    with pytest.raises(
        ExecutionProfileError,
        match="provider requires a target path and completed workspace.read",
    ):
        profile.build_provider_request(
            task_id="task:profile",
            run_id="run:profile",
            provider_profile=provider_profile(now),
            provider_capability="provider.chat",
            context=context,
            now=now,
        )


def test_bind_provider_response_binds_single_patch_proposal() -> None:
    profile = DeveloperRepositoryPatchProfile()
    response = response_with(
        tool_proposals=(
            proposal({"path": "fixture.txt", "content": "after\n"}),
        ),
    )

    bound = profile.bind_provider_response(response, context=profile_context())

    assert len(bound) == 1
    arguments = json.loads(bound[0].arguments_json)
    assert arguments == {
        "path": "fixture.txt",
        "content": "after\n",
        "expected_sha256": "b" * 64,
    }


def test_bind_provider_response_rejects_two_proposals() -> None:
    profile = DeveloperRepositoryPatchProfile()
    response = response_with(
        tool_proposals=(
            proposal({"path": "fixture.txt", "content": "after\n"}),
            proposal({"path": "fixture.txt", "content": "again\n"}, proposal_id="proposal:2"),
        ),
    )

    with pytest.raises(
        ExecutionProfileError,
        match="provider returned an ambiguous or unauthorized tool proposal",
    ):
        profile.bind_provider_response(response, context=profile_context())


def test_bind_provider_response_rejects_non_patch_capability() -> None:
    profile = DeveloperRepositoryPatchProfile()
    response = response_with(
        tool_proposals=(
            ProviderToolProposal(
                proposal_id="proposal:1",
                capability_id="workspace.read",
                arguments_json=json.dumps({"path": "fixture.txt"}),
            ),
        ),
    )

    with pytest.raises(
        ExecutionProfileError,
        match="provider returned an ambiguous or unauthorized tool proposal",
    ):
        profile.bind_provider_response(response, context=profile_context())


def test_bind_provider_response_rejects_extra_argument_keys() -> None:
    profile = DeveloperRepositoryPatchProfile()
    response = response_with(
        tool_proposals=(
            proposal({"path": "fixture.txt", "content": "after\n", "extra": 1}),
        ),
    )

    with pytest.raises(
        ExecutionProfileError,
        match="provider patch arguments must contain only path and content",
    ):
        profile.bind_provider_response(response, context=profile_context())


def test_bind_provider_response_rejects_path_mismatch() -> None:
    profile = DeveloperRepositoryPatchProfile()
    response = response_with(
        tool_proposals=(
            proposal({"path": "other.txt", "content": "after\n"}),
        ),
    )

    with pytest.raises(
        ExecutionProfileError,
        match="provider proposal path does not match the reviewed target",
    ):
        profile.bind_provider_response(response, context=profile_context())


def test_bind_provider_response_rejects_non_string_content() -> None:
    profile = DeveloperRepositoryPatchProfile()
    response = response_with(
        tool_proposals=(
            proposal({"path": "fixture.txt", "content": 42}),
        ),
    )

    with pytest.raises(
        ExecutionProfileError,
        match="provider proposal requires complete string content",
    ):
        profile.bind_provider_response(response, context=profile_context())


def test_bind_provider_response_parses_text_fallback() -> None:
    profile = DeveloperRepositoryPatchProfile()
    response = response_with(
        text='```json\n{"path": "fixture.txt", "content": "after\\n"}\n```',
    )

    bound = profile.bind_provider_response(response, context=profile_context())

    assert len(bound) == 1
    arguments = json.loads(bound[0].arguments_json)
    assert arguments["path"] == "fixture.txt"
    assert arguments["content"] == "after\n"
    assert arguments["expected_sha256"] == "b" * 64


def test_bind_provider_response_rejects_malformed_text_fallback() -> None:
    profile = DeveloperRepositoryPatchProfile()
    response = response_with(text="no json here at all")

    with pytest.raises(
        ExecutionProfileError,
        match="provider must return exactly one workspace.apply_patch proposal",
    ):
        profile.bind_provider_response(response, context=profile_context())


def test_tool_arguments_for_workspace_read() -> None:
    profile = DeveloperRepositoryPatchProfile()

    assert profile.tool_arguments("workspace.read", {"target_path": "a.txt"}) == {
        "path": "a.txt"
    }
    with pytest.raises(
        ExecutionProfileError,
        match="workspace.read requires target_path",
    ):
        profile.tool_arguments("workspace.read", {})


def test_tool_arguments_for_workspace_run_tests() -> None:
    profile = DeveloperRepositoryPatchProfile()

    assert profile.tool_arguments("workspace.run_tests", {}) == {
        "command": "python -m pytest"
    }
    assert profile.tool_arguments(
        "workspace.run_tests",
        {"test_command": "pytest"},
    ) == {"command": "pytest"}


def test_tool_arguments_for_explicit_and_unknown_capability() -> None:
    profile = DeveloperRepositoryPatchProfile()

    assert profile.tool_arguments("artifact.write", {"artifact.write": {"content": "x"}}) == {
        "content": "x"
    }
    with pytest.raises(
        ExecutionProfileError,
        match="no typed arguments available for artifact.write",
    ):
        profile.tool_arguments("artifact.write", {})


def test_requires_provider_bound_action_only_for_apply_patch() -> None:
    profile = DeveloperRepositoryPatchProfile()

    assert profile.requires_provider_bound_action("workspace.apply_patch") is True
    for capability_id in (
        "workspace.read",
        "workspace.run_tests",
        "artifact.write",
        "workspace.compensate_patch",
    ):
        assert profile.requires_provider_bound_action(capability_id) is False


def test_verification_exit_code_strict_extraction() -> None:
    profile = DeveloperRepositoryPatchProfile()

    assert profile.verification_exit_code({"workspace.run_tests": {"exit_code": 0}}) == 0
    assert profile.verification_exit_code({"workspace.run_tests": {"exit_code": 2}}) == 2
    assert profile.verification_exit_code({"workspace.run_tests": {"exit_code": True}}) is None
    assert profile.verification_exit_code({"workspace.run_tests": {"exit_code": "0"}}) is None
    assert profile.verification_exit_code({"workspace.run_tests": {}}) is None
    assert profile.verification_exit_code({"workspace.run_tests": "report"}) is None
    assert profile.verification_exit_code({}) is None


def test_generator_identity_and_no_run_execution_error_import() -> None:
    profile = DeveloperRepositoryPatchProfile()

    assert profile.generator_id == "developer-golden-path"
    assert profile.generator_version == "1"

    source = (
        Path(__file__).parents[2]
        / "domain_packs"
        / "developer_agent"
        / "repository_patch_profile.py"
    ).read_text(encoding="utf-8")
    assert "RunExecutionError" not in source
