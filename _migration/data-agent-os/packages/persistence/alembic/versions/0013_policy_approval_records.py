"""policy_approval_records: durable R4/R5 auto-execution approval ledger

Revision ID: 0013_policy_approval_records
Revises: 0012_dashboards
Create Date: 2026-07-07

Tenant-scoped policy-approval records (ADR-0012 / workstream E). One row per
record_id; the full frozen ``PolicyApprovalRecord`` is stored as JSON so the
active/revoked/consumed lifecycle and idempotency semantics survive restarts.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_policy_approval_records"
down_revision: str | None = "0012_dashboards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "policy_approval_records",
        sa.Column("tenant_id", sa.String(), primary_key=True),
        sa.Column("record_id", sa.String(), primary_key=True),
        sa.Column("proposal_id", sa.String(), nullable=False, index=True),
        sa.Column("policy_version", sa.String(), nullable=False, index=True),
        sa.Column("status", sa.String(), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("policy_approval_records")
