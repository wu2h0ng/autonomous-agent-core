from __future__ import annotations

from datetime import datetime, timezone

import pytest


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def goal(now: datetime):
    from agent_os_contracts import Goal

    return Goal(
        goal_id="goal-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        created_by="user-1",
        created_at=now,
        statement="Ship a verified patch",
        constraints=("stay in sandbox",),
    )


@pytest.fixture(autouse=True)
def _hermetic_provider_persistence(tmp_path, monkeypatch):
    """Keep provider persistence out of the real OS keychain and home directory.

    configure_provider persists the non-secret config and stores the key in the
    OS keychain; tests must never touch either the developer's real keychain or
    ``~/.agent-os/provider.json``. The config path is redirected to tmp and the
    keychain is disabled via AGENT_OS_DISABLE_KEYCHAIN (the credential-store
    classes stay real so their own tests can exercise them).
    """

    monkeypatch.setenv(
        "AGENT_OS_PROVIDER_CONFIG", str(tmp_path / "provider.json")
    )
    monkeypatch.setenv("AGENT_OS_DISABLE_KEYCHAIN", "1")
    # Keep pricing hermetic: never read the developer's ~/.agent-os/pricing.json.
    monkeypatch.setenv(
        "AGENT_OS_PRICING_FILE", str(tmp_path / "pricing.json")
    )
