from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    CredentialRef,
    CredentialStatus,
    ProviderErrorCode,
    ProviderFailure,
    ProviderMessage,
    ProviderMessageRole,
    ProviderProfile,
    ProviderRequest,
    ProviderResponse,
    ProviderToolProposal,
    ProviderUsage,
)


NOW = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)


def _credential_ref(**updates: Any) -> CredentialRef:
    values: dict[str, Any] = {
        "credential_ref_id": "credential-1",
        "owner_principal_id": "principal-1",
        "tenant_id": "tenant-1",
        "workspace_id": "workspace-1",
        "provider_id": "openai-compatible",
        "resolver_key": "OPENAI_TEST_KEY",
        "scopes": ("responses:create",),
        "status": CredentialStatus.ACTIVE,
        "created_at": NOW,
        "expires_at": NOW + timedelta(days=1),
    }
    values.update(updates)
    return CredentialRef(**values)


def _profile(**updates: Any) -> ProviderProfile:
    values: dict[str, Any] = {
        "profile_id": "profile-1",
        "provider_id": "openai-compatible",
        "model_id": "test-model",
        "endpoint_class": "openai-responses",
        "credential_ref_id": "credential-1",
        "capabilities": ("text", "tool-proposal"),
        "max_context_tokens": 8_192,
        "request_timeout_seconds": 30,
        "created_at": NOW,
    }
    values.update(updates)
    return ProviderProfile(**values)


def _request(**updates: Any) -> ProviderRequest:
    values: dict[str, Any] = {
        "request_id": "request-1",
        "task_id": "task-1",
        "run_id": "run-1",
        "provider_profile_id": "profile-1",
        "messages": (
            ProviderMessage(role=ProviderMessageRole.USER, content="Inspect the repository"),
        ),
        "allowed_capability_ids": ("workspace.read",),
        "timeout_seconds": 30,
        "created_at": NOW,
    }
    values.update(updates)
    return ProviderRequest(**values)


def _usage() -> ProviderUsage:
    return ProviderUsage(
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        estimated_cost_usd=Decimal("0.001"),
    )


def test_credential_ref_never_contains_secret_value_field() -> None:
    ref = _credential_ref()

    assert "secret" not in ref.model_dump()
    with pytest.raises(ValidationError):
        CredentialRef.model_validate({**ref.model_dump(), "secret_value": "canary"})


def test_revoked_credential_ref_is_explicit() -> None:
    ref = _credential_ref(status=CredentialStatus.REVOKED)

    assert ref.status is CredentialStatus.REVOKED


def test_provider_profile_normalizes_capabilities() -> None:
    profile = _profile(capabilities=("tool-proposal", "text", "text"))

    assert profile.capabilities == ("text", "tool-proposal")


def test_provider_request_requires_messages() -> None:
    with pytest.raises(ValidationError):
        _request(messages=())


def test_tool_proposal_arguments_are_canonical_objects() -> None:
    proposal = ProviderToolProposal(
        proposal_id="proposal-1",
        capability_id="workspace.read",
        arguments_json=' { "path": "README.md" } ',
    )

    assert proposal.arguments_json == '{"path":"README.md"}'
    with pytest.raises(ValidationError, match="object"):
        ProviderToolProposal(
            proposal_id="proposal-2",
            capability_id="workspace.read",
            arguments_json='["README.md"]',
        )


def test_provider_response_requires_text_or_tool_proposal() -> None:
    with pytest.raises(ValidationError, match="text or tool"):
        ProviderResponse(
            response_id="response-1",
            request_id="request-1",
            text="",
            tool_proposals=(),
            usage=_usage(),
            finish_reason="stop",
            received_at=NOW,
        )


@pytest.mark.parametrize("code", tuple(ProviderErrorCode))
def test_provider_failure_preserves_typed_error_code(code: ProviderErrorCode) -> None:
    failure = ProviderFailure(
        failure_id=f"failure-{code.value.lower()}",
        request_id="request-1",
        code=code,
        retryable=code
        in {
            ProviderErrorCode.RATE_LIMITED,
            ProviderErrorCode.TIMEOUT,
            ProviderErrorCode.UNAVAILABLE,
        },
        safe_message="provider request failed",
        occurred_at=NOW,
    )

    assert failure.code is code
