"""run_traces: persisted, queryable run traces (observability v1)

Revision ID: 0005_run_traces
Revises: 0004_pgvector_embedding
Create Date: 2026-06-11

One row per trace_id, written on BOTH exits of run() ("ok" answers and "blocked"
refusals), so any run is auditable after the fact (AR-20260611-observability-
trace-store). Payload is the canonical serialized RunTrace (events + telemetry).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_run_traces"
down_revision: str | None = "0004_pgvector_embedding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "run_traces",
        sa.Column("trace_id", sa.String(), primary_key=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_run_traces_status", "run_traces", ["status"])


def downgrade() -> None:
    op.drop_index("ix_run_traces_status", table_name="run_traces")
    op.drop_table("run_traces")
