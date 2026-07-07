"""tenants: minimal tenant metadata table

Revision ID: 0011_tenants
Revises: 0010_usage_events
Create Date: 2026-07-06

Tenant provisioning table backing the internal-only tenant management API.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_tenants"
down_revision: str | None = "0010_usage_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("tenant_id", sa.String(), primary_key=True),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tenants")
