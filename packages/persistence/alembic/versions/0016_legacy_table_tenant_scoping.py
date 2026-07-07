"""legacy tables: add tenant_id scoping to pre-0010 schema

Revision ID: 0016_legacy_table_tenant_scoping
Revises: 0015_run_traces_tenant_id
Create Date: 2026-07-07

Aligns feedback_events, knowledge_assets, state_snapshots, approval_records,
approval_operation_contexts, action_records, agent_runtime_checkpoints,
report_snapshots, and knowledge_index with tenant-scoped schema.py.
Existing rows receive tenant_id='default'.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_legacy_table_tenant_scoping"
down_revision: str | None = "0015_run_traces_tenant_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMPOSITE_PK_TABLES: tuple[tuple[str, str], ...] = (
    ("knowledge_assets", "source_trace_id"),
    ("state_snapshots", "snapshot_id"),
    ("approval_records", "approval_id"),
    ("approval_operation_contexts", "approval_id"),
    ("agent_runtime_checkpoints", "run_id"),
)

_INDEXED_TENANT_TABLES: tuple[str, ...] = (
    "feedback_events",
    "action_records",
    "knowledge_index",
)


def _upgrade_postgresql() -> None:
    for table, key_col in _COMPOSITE_PK_TABLES:
        op.add_column(
            table,
            sa.Column("tenant_id", sa.String(), nullable=False, server_default="default"),
        )
        op.drop_constraint(f"{table}_pkey", table, type_="primary")
        op.create_primary_key(f"{table}_pkey", table, ["tenant_id", key_col])

    for table in _INDEXED_TENANT_TABLES:
        op.add_column(
            table,
            sa.Column("tenant_id", sa.String(), nullable=False, server_default="default"),
        )
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

    op.drop_index("ix_knowledge_index_source_trace_id", table_name="knowledge_index")
    op.create_index(
        "ix_knowledge_index_source_trace_id",
        "knowledge_index",
        ["tenant_id", "source_trace_id"],
        unique=True,
    )

    op.add_column(
        "report_snapshots",
        sa.Column("tenant_id", sa.String(), nullable=False, server_default="default"),
    )
    op.drop_constraint("pk_report_snapshots", "report_snapshots", type_="primary")
    op.create_primary_key(
        "pk_report_snapshots",
        "report_snapshots",
        ["tenant_id", "trace_id", "audience"],
    )


def _downgrade_postgresql() -> None:
    op.drop_constraint("pk_report_snapshots", "report_snapshots", type_="primary")
    op.create_primary_key("pk_report_snapshots", "report_snapshots", ["trace_id", "audience"])
    op.drop_column("report_snapshots", "tenant_id")

    op.drop_index("ix_knowledge_index_source_trace_id", table_name="knowledge_index")
    op.create_index(
        "ix_knowledge_index_source_trace_id",
        "knowledge_index",
        ["source_trace_id"],
        unique=True,
    )

    for table in reversed(_INDEXED_TENANT_TABLES):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")

    for table, key_col in reversed(_COMPOSITE_PK_TABLES):
        op.drop_constraint(f"{table}_pkey", table, type_="primary")
        op.create_primary_key(f"{table}_pkey", table, [key_col])
        op.drop_column(table, "tenant_id")


def _upgrade_sqlite() -> None:
    for table, key_col in _COMPOSITE_PK_TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(
                sa.Column("tenant_id", sa.String(), nullable=False, server_default="default")
            )
            batch_op.drop_constraint(f"{table}_pkey", type_="primary")
            batch_op.create_primary_key(f"{table}_pkey", ["tenant_id", key_col])

    for table in _INDEXED_TENANT_TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(
                sa.Column("tenant_id", sa.String(), nullable=False, server_default="default")
            )
            batch_op.create_index(f"ix_{table}_tenant_id", ["tenant_id"])

    with op.batch_alter_table("knowledge_index") as batch_op:
        batch_op.drop_index("ix_knowledge_index_source_trace_id")
        batch_op.create_index(
            "ix_knowledge_index_source_trace_id",
            ["tenant_id", "source_trace_id"],
            unique=True,
        )

    with op.batch_alter_table("report_snapshots") as batch_op:
        batch_op.add_column(
            sa.Column("tenant_id", sa.String(), nullable=False, server_default="default")
        )
        batch_op.drop_constraint("pk_report_snapshots", type_="primary")
        batch_op.create_primary_key("pk_report_snapshots", ["tenant_id", "trace_id", "audience"])


def _downgrade_sqlite() -> None:
    with op.batch_alter_table("report_snapshots") as batch_op:
        batch_op.drop_constraint("pk_report_snapshots", type_="primary")
        batch_op.create_primary_key("pk_report_snapshots", ["trace_id", "audience"])
        batch_op.drop_column("tenant_id")

    with op.batch_alter_table("knowledge_index") as batch_op:
        batch_op.drop_index("ix_knowledge_index_source_trace_id")
        batch_op.create_index("ix_knowledge_index_source_trace_id", ["source_trace_id"], unique=True)

    for table in reversed(_INDEXED_TENANT_TABLES):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_index(f"ix_{table}_tenant_id")
            batch_op.drop_column("tenant_id")

    for table, key_col in reversed(_COMPOSITE_PK_TABLES):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(f"{table}_pkey", type_="primary")
            batch_op.create_primary_key(f"{table}_pkey", [key_col])
            batch_op.drop_column("tenant_id")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _upgrade_postgresql()
    else:
        _upgrade_sqlite()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _downgrade_postgresql()
    else:
        _downgrade_sqlite()
