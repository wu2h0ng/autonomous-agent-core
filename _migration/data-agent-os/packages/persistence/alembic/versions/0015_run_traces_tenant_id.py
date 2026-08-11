"""run_traces: add tenant_id composite primary key

Revision ID: 0015_run_traces_tenant_id
Revises: 0014_staged_out_stores
Create Date: 2026-07-07

Aligns persisted run_traces with tenant-scoped schema (tenant_id + trace_id PK).
Existing rows receive tenant_id='default'.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_run_traces_tenant_id"
down_revision: str | None = "0014_staged_out_stores"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("run_traces") as batch_op:
        batch_op.add_column(
            sa.Column("tenant_id", sa.String(), nullable=False, server_default="default")
        )
        batch_op.drop_constraint("run_traces_pkey", type_="primary")
        batch_op.create_primary_key("run_traces_pkey", ["tenant_id", "trace_id"])


def downgrade() -> None:
    with op.batch_alter_table("run_traces") as batch_op:
        batch_op.drop_constraint("run_traces_pkey", type_="primary")
        batch_op.create_primary_key("run_traces_pkey", ["trace_id"])
        batch_op.drop_column("tenant_id")
