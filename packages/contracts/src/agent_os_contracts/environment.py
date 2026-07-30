from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .common import ContractModel, UtcDateTime


class EnvironmentModelSnapshot(ContractModel):
    """Versioned task-relevant entities, relations, dynamics, source coverage and uncertainty."""

    snapshot_id: str = ""
    task_id: str
    source_capability_ids: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    relations: tuple[dict[str, Any], ...] = ()
    dynamics_hints: tuple[str, ...] = ()
    coverage_gaps: tuple[str, ...] = ()
    uncertainty_score: float | None = None
    frozen_at: UtcDateTime = datetime.now(timezone.utc)

    def model_post_init(self, __context: Any) -> None:
        if not self.snapshot_id:
            object.__setattr__(
                self,
                "snapshot_id",
                f"env-snapshot-{uuid4()}",
            )
