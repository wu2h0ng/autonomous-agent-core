from __future__ import annotations

from datetime import datetime, timezone

from agent_os_contracts import DomainPackManifest

__all__ = ["manifest"]


def manifest(now: datetime | None = None) -> DomainPackManifest:
    return DomainPackManifest(
        pack_id="data-agent",
        version="1.0",
        namespace="data_agent",
        capabilities=(
            "data.query.safe",
            "data.report.observe",
            "data.action.propose",
        ),
        workflow_templates=("data_agent.trusted_decision.v1",),
        evaluator_types=("data_agent.outcome.v1",),
        credential_classes=(),
        created_at=now or datetime.now(timezone.utc),
    )
