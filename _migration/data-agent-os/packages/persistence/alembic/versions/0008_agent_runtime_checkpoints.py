"""agent_runtime_checkpoints: durable runtime checkpoint snapshots

Revision ID: 0008_agent_runtime_checkpoints
Revises: 0007_action_records
Create Date: 2026-06-24

Stores the Agent Runtime's RunStateSnapshot by run_id so a later runtime
instance can resume only after fingerprint validation. This is a runtime
recovery boundary, not a workflow engine, release claim, or permission to bypass
approval/EvidenceChain/Trace gates.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_agent_runtime_checkpoints"
down_revision: str | None = "0007_action_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_runtime_checkpoints",
        sa.Column("run_id", sa.String(), primary_key=True),
        sa.Column("trace_id", sa.String(), nullable=False),
        sa.Column("step_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_agent_runtime_checkpoints_trace_id",
        "agent_runtime_checkpoints",
        ["trace_id"],
    )
    op.create_index(
        "ix_agent_runtime_checkpoints_step_id",
        "agent_runtime_checkpoints",
        ["step_id"],
    )
    op.create_index(
        "ix_agent_runtime_checkpoints_status",
        "agent_runtime_checkpoints",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runtime_checkpoints_status", table_name="agent_runtime_checkpoints")
    op.drop_index("ix_agent_runtime_checkpoints_step_id", table_name="agent_runtime_checkpoints")
    op.drop_index("ix_agent_runtime_checkpoints_trace_id", table_name="agent_runtime_checkpoints")
    op.drop_table("agent_runtime_checkpoints")
