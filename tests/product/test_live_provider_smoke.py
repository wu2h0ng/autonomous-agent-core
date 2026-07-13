from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from agent_os_contracts import (
    CredentialRef,
    CredentialStatus,
    ProviderMessage,
    ProviderMessageRole,
    ProviderRequest,
)
from agent_os_core import EnvCredentialBroker, OpenAICompatibleProvider


@pytest.mark.skipif(
    not os.environ.get("AGENT_OS_PROVIDER_BASE_URL")
    or not os.environ.get("OPENAI_API_KEY"),
    reason="opt-in live provider smoke requires AGENT_OS_PROVIDER_BASE_URL and OPENAI_API_KEY",
)
def test_live_openai_compatible_provider_smoke() -> None:
    now = datetime.now(timezone.utc)
    ref = CredentialRef(
        credential_ref_id="credential:live-smoke",
        owner_principal_id="smoke",
        tenant_id="tenant:smoke",
        workspace_id="workspace:smoke",
        provider_id="openai-compatible",
        resolver_key="OPENAI_API_KEY",
        scopes=("chat",),
        status=CredentialStatus.ACTIVE,
        created_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    provider = OpenAICompatibleProvider(
        base_url=os.environ["AGENT_OS_PROVIDER_BASE_URL"],
        model=os.environ.get("AGENT_OS_PROVIDER_MODEL", "gpt-4o-mini"),
        credential=ref,
        credentials=EnvCredentialBroker(),
        timeout_seconds=30,
    )
    response = provider.complete(
        ProviderRequest(
            request_id="request:live-smoke",
            task_id="task:live-smoke",
            run_id="run:live-smoke",
            provider_profile_id="profile:live-smoke",
            messages=(
                ProviderMessage(
                    role=ProviderMessageRole.USER, content="Reply with the word OK."
                ),
            ),
            timeout_seconds=30,
            created_at=now,
        )
    )
    assert getattr(response, "text", "").strip()
