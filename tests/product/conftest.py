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
