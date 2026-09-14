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
    ``~/.agent-os/provider.json``. Tests that exercise persistence override this
    with their own tmp config path.
    """

    from apps.api_server.provider_settings import KeychainCredentialStore

    monkeypatch.setenv(
        "AGENT_OS_PROVIDER_CONFIG", str(tmp_path / "provider.json")
    )
    monkeypatch.setattr(KeychainCredentialStore, "available", lambda self: False)
    monkeypatch.setattr(
        KeychainCredentialStore, "store", lambda self, account, secret: False
    )
    monkeypatch.setattr(
        KeychainCredentialStore, "load", lambda self, account: None
    )
