from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from agent_os_contracts import (
    SURFACE_PROTOCOL_VERSION,
    SurfaceClientRef,
    SurfaceTurnCommand,
)


NOW = datetime(2026, 8, 11, tzinfo=timezone.utc)


def client() -> SurfaceClientRef:
    return SurfaceClientRef(
        client_id="client:cli:1",
        client_type="CLI",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        device_id="device:mac:1",
    )


def test_surface_turn_requires_version_sequence_and_idempotency() -> None:
    command = SurfaceTurnCommand(
        protocol_version=SURFACE_PROTOCOL_VERSION,
        client=client(),
        session_id="session:1",
        text="inspect the failing test",
        expected_event_sequence=12,
        idempotency_key="idem:turn:1",
        requested_at=NOW,
    )
    assert command.expected_event_sequence == 12
    with pytest.raises(ValidationError):
        SurfaceTurnCommand.model_validate(
            command.model_dump() | {"protocol_version": "2.0"}
        )


def test_surface_contracts_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SurfaceClientRef.model_validate(client().model_dump() | {"admin": True})
