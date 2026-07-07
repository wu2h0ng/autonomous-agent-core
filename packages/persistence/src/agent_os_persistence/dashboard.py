"""SQLAlchemy-Core implementation of ``DashboardStorePort``."""

from __future__ import annotations

from agent_os_core import Dashboard, DashboardCard, DashboardStorePort
from sqlalchemy import select

from . import schema
from .repositories import _SqlStoreBase


class SqlDashboardStore(_SqlStoreBase, DashboardStorePort):
    """Durable dashboard store backed by SQLAlchemy Core."""

    def save(self, dashboard: Dashboard) -> None:
        payload = {
            "title": dashboard.title,
            "created_at": dashboard.created_at,
            "cards": [
                {
                    "card_id": card.card_id,
                    "title": card.title,
                    "question": card.question,
                    "metric_name": card.metric_name,
                    "chart_type": card.chart_type,
                }
                for card in dashboard.cards
            ],
        }
        with self._write() as conn:
            existing = conn.execute(
                select(schema.dashboards).where(
                    schema.dashboards.c.tenant_id == dashboard.tenant_id,
                    schema.dashboards.c.dashboard_id == dashboard.dashboard_id,
                )
            ).fetchone()
            if existing is not None:
                conn.execute(
                    schema.dashboards.update()
                    .where(
                        schema.dashboards.c.tenant_id == dashboard.tenant_id,
                        schema.dashboards.c.dashboard_id == dashboard.dashboard_id,
                    )
                    .values(title=dashboard.title, payload=payload)
                )
            else:
                conn.execute(
                    schema.dashboards.insert().values(
                        tenant_id=dashboard.tenant_id,
                        dashboard_id=dashboard.dashboard_id,
                        title=dashboard.title,
                        created_at=dashboard.created_at,
                        payload=payload,
                    )
                )

    def get(self, dashboard_id: str, tenant_id: str) -> Dashboard | None:
        with self._read() as conn:
            row = conn.execute(
                select(schema.dashboards).where(
                    schema.dashboards.c.tenant_id == tenant_id,
                    schema.dashboards.c.dashboard_id == dashboard_id,
                )
            ).fetchone()
        if row is None:
            return None
        return _row_to_dashboard(row)

    def list(self, tenant_id: str, limit: int, offset: int) -> tuple[Dashboard, ...]:
        with self._read() as conn:
            rows = conn.execute(
                select(schema.dashboards)
                .where(schema.dashboards.c.tenant_id == tenant_id)
                .order_by(schema.dashboards.c.created_at.desc())
                .limit(limit)
                .offset(offset)
            ).fetchall()
        return tuple(_row_to_dashboard(row) for row in rows)


def _row_to_dashboard(row: object) -> Dashboard:
    payload = dict(row.payload or {})
    cards = tuple(
        DashboardCard(
            card_id=card["card_id"],
            title=card["title"],
            question=card["question"],
            metric_name=card["metric_name"],
            chart_type=card["chart_type"],
        )
        for card in payload.get("cards", [])
    )
    return Dashboard(
        dashboard_id=row.dashboard_id,
        tenant_id=row.tenant_id,
        title=row.title,
        cards=cards,
        created_at=row.created_at,
    )
