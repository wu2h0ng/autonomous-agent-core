"""Tenant metadata storage port and in-memory reference implementation.

OS Core depends on ``TenantStorePort``; concrete adapters (in-memory for tests,
SQLAlchemy-Core for production) live outside OS Core.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone

__all__ = ["InMemoryTenantStore", "Tenant", "TenantStorePort"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Tenant:
    """Immutable tenant metadata contract."""

    tenant_id: str
    display_name: str
    status: str = "active"
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    config: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "tenant_id": self.tenant_id,
            "display_name": self.display_name,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "config": dict(self.config),
        }


class TenantStorePort(ABC):
    """Persistence port for tenant metadata."""

    @abstractmethod
    def create(
        self,
        tenant_id: str,
        *,
        display_name: str,
        status: str = "active",
        config: dict[str, object] | None = None,
    ) -> Tenant:
        """Create a tenant record and return it.

        Raises:
            ValueError: if the tenant already exists.
        """
        ...

    @abstractmethod
    def get(self, tenant_id: str) -> Tenant | None:
        """Return the tenant record or ``None`` if not found."""
        ...


class InMemoryTenantStore(TenantStorePort):
    """Thread-unsafe in-memory tenant store for tests and single-process demos."""

    def __init__(self) -> None:
        self._tenants: dict[str, Tenant] = {}

    def create(
        self,
        tenant_id: str,
        *,
        display_name: str,
        status: str = "active",
        config: dict[str, object] | None = None,
    ) -> Tenant:
        if tenant_id in self._tenants:
            raise ValueError(f"Tenant {tenant_id!r} already exists.")
        now = _utc_now()
        tenant = Tenant(
            tenant_id=tenant_id,
            display_name=display_name,
            status=status,
            created_at=now,
            updated_at=now,
            config=dict(config or {}),
        )
        self._tenants[tenant_id] = tenant
        return tenant

    def get(self, tenant_id: str) -> Tenant | None:
        return self._tenants.get(tenant_id)
