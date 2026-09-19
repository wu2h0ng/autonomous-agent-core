"""Marker for the vendored ``agent_workflow_runner`` package."""

from .team_event_contract import (  # noqa: F401
    TEAM_EVENT_SCHEMA,
    build_team_event_record,
    get_team_event_schema,
)

__version__ = "hermetic-pinned-v1"
