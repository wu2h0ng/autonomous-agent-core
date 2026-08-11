"""dashboards: NL Data Product Workspace layouts

Revision ID: 0012_dashboards
Revises: 0011_tenants
Create Date: 2026-07-06

Tenant-scoped dashboard layouts for the Natural Language Data Product Workspace.
Cards (question, metric, chart type) are stored as a JSON payload.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_dashboards"
down_revision: str | None = "0011_tenants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dashboards",
        sa.Column("tenant_id", sa.String(), primary_key=True),
        sa.Column("dashboard_id", sa.String(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("dashboards")
