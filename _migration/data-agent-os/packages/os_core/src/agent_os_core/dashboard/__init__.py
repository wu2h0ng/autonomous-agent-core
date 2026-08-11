"""Natural Language Data Product Workspace: dashboard model and store port.

This module keeps the dashboard concept domain-independent: it stores cards that
reference metric contracts by name and preserve the natural-language question
that produced them. Rendering/query execution is handled by the existing
Trusted Loop surfaces; the dashboard store only persists layout metadata.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class DashboardCard:
    """One tile in a dashboard."""

    card_id: str
    title: str
    question: str
    metric_name: str
    chart_type: str


@dataclass(frozen=True)
class Dashboard:
    """A tenant-scoped dashboard composed of metric cards."""

    dashboard_id: str
    tenant_id: str
    title: str
    cards: tuple[DashboardCard, ...]
    created_at: str


class DashboardStorePort(ABC):
    """Persistence port for dashboards. OS Core owns the port; concrete stores
    live in the composition/persistence layer so OS Core stays infra-independent.
    """

    @abstractmethod
    def save(self, dashboard: Dashboard) -> None:
        """Persist ``dashboard``, replacing any existing row with the same id."""
        raise NotImplementedError

    @abstractmethod
    def get(self, dashboard_id: str, tenant_id: str) -> Dashboard | None:
        """Fetch a single dashboard by composite key."""
        raise NotImplementedError

    @abstractmethod
    def list(self, tenant_id: str, limit: int, offset: int) -> tuple[Dashboard, ...]:
        """Return dashboards for ``tenant_id`` ordered by creation time descending."""
        raise NotImplementedError


class InMemoryDashboardStore(DashboardStorePort):
    """Process-local in-memory dashboard store."""

    def __init__(self) -> None:
        self._dashboards: dict[tuple[str, str], Dashboard] = {}

    def save(self, dashboard: Dashboard) -> None:
        self._dashboards[(dashboard.tenant_id, dashboard.dashboard_id)] = dashboard

    def get(self, dashboard_id: str, tenant_id: str) -> Dashboard | None:
        return self._dashboards.get((tenant_id, dashboard_id))

    def list(self, tenant_id: str, limit: int, offset: int) -> tuple[Dashboard, ...]:
        all_dashboards = sorted(
            (dashboard for key, dashboard in self._dashboards.items() if key[0] == tenant_id),
            key=lambda d: d.created_at,
            reverse=True,
        )
        return tuple(all_dashboards[offset : offset + limit])


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
