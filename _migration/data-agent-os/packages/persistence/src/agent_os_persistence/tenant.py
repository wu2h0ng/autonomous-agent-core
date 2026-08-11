"""SQLAlchemy-Core implementation of ``TenantStorePort``."""

from __future__ import annotations

from datetime import datetime, timezone

from agent_os_core import Tenant, TenantStorePort
from sqlalchemy import select

from . import schema
from .repositories import _SqlStoreBase


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SqlTenantStore(_SqlStoreBase, TenantStorePort):
    """Durable tenant metadata store backed by SQLAlchemy Core."""

    def create(
        self,
        tenant_id: str,
        *,
        display_name: str,
        status: str = "active",
        config: dict[str, object] | None = None,
    ) -> Tenant:
        now = _utc_now()
        payload_config = dict(config or {})
        with self._write() as conn:
            existing = conn.execute(
                select(schema.tenants).where(schema.tenants.c.tenant_id == tenant_id)
            ).fetchone()
            if existing is not None:
                raise ValueError(f"Tenant {tenant_id!r} already exists.")
            conn.execute(
                schema.tenants.insert().values(
                    tenant_id=tenant_id,
                    display_name=display_name,
                    status=status,
                    created_at=now,
                    updated_at=now,
                    config=payload_config,
                )
            )
        return Tenant(
            tenant_id=tenant_id,
            display_name=display_name,
            status=status,
            created_at=now,
            updated_at=now,
            config=payload_config,
        )

    def get(self, tenant_id: str) -> Tenant | None:
        with self._read() as conn:
            row = conn.execute(
                select(schema.tenants).where(schema.tenants.c.tenant_id == tenant_id)
            ).fetchone()
        if row is None:
            return None
        return Tenant(
            tenant_id=row.tenant_id,
            display_name=row.display_name,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
            config=dict(row.config or {}),
        )
