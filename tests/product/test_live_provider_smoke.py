from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_os_contracts import (
    CredentialRef,
    CredentialStatus,
    ProviderMessage,
    ProviderMessageRole,
    ProviderRequest,
)
from agent_os_core import DeterministicProvider, EnvCredentialBroker, OpenAICompatibleProvider
from apps.api_server.app import AgentOSApplication
from scripts.live_provider_outcome_smoke import run_smoke


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


def test_live_provider_outcome_smoke_runner_produces_verified_summary(
    tmp_path: Path,
) -> None:
    def app_factory(*, database: Path, workspace: Path) -> AgentOSApplication:
        app = AgentOSApplication(database=database, workspace=workspace)
        app.provider = DeterministicProvider(
            text='{"path":"fixture.txt","content":"after\\n"}',
            invocation_binding=app.provider.invocation_binding,
        )
        app.provider_configured = True
        return app

    summary = run_smoke(
        app_factory=app_factory,
        workspace_root=tmp_path / "workspace",
        model_id="deterministic-v1",
    )

    assert summary["task_status"] == "COMPLETED"
    assert summary["run_status"] == "SUCCEEDED"
    assert summary["outcome_status"] == "VERIFIED"
    assert summary["validated_report"] is True
    assert summary["file_after"] == "after\n"
    assert summary["event_counts"]["TASK_CONFIGURATION_SNAPSHOT_SEALED"] == 1
    assert summary["event_counts"]["OUTCOME_OBSERVED"] == 1
