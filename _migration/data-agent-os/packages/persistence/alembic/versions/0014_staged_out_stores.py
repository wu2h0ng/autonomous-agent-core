"""approval_workflows + workflow_instances + auto_execution_policies

Revision ID: 0014_staged_out_stores
Revises: 0013_policy_approval_records
Create Date: 2026-07-07

Durable stores for workstreams D (BPM) and E (tenant auto-execution policy).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_staged_out_stores"
down_revision: str | None = "0013_policy_approval_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approval_workflows",
        sa.Column("tenant_id", sa.String(), primary_key=True),
        sa.Column("workflow_id", sa.String(), primary_key=True),
        sa.Column("state", sa.String(), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "workflow_instances",
        sa.Column("tenant_id", sa.String(), primary_key=True),
        sa.Column("instance_id", sa.String(), primary_key=True),
        sa.Column("workflow_id", sa.String(), nullable=False, index=True),
        sa.Column("proposal_id", sa.String(), nullable=False, index=True),
        sa.Column("state", sa.String(), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "auto_execution_policies",
        sa.Column("tenant_id", sa.String(), primary_key=True),
        sa.Column("policy_version", sa.String(), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("auto_execution_policies")
    op.drop_table("workflow_instances")
    op.drop_table("approval_workflows")
