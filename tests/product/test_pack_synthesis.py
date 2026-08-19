"""Tests for proposal persistence and operator-approved pack materialization.

Verifies that proposals are serialized secret-free, materialization only
writes operator-approved metrics, inline secrets are rejected, and dangling
approval names fail closed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_os_contracts.domain_pack_synthesis import (
    ColumnInventory,
    PackCandidateMetric,
    SchemaInventory,
    TableInventory,
)
from apps.api_server.pack_synthesis import materialize_pack, write_proposal


def _inventory() -> SchemaInventory:
    return SchemaInventory(
        tables=(
            TableInventory(
                schema="adstable",
                table="ads_profit_order",
                columns=(
                    ColumnInventory(name="日期", data_type="date"),
                    ColumnInventory(name="GMV", data_type="decimal"),
                ),
            ),
        )
    )


def _candidate(name: str = "adstable_ads_profit_order_gmv_sum") -> PackCandidateMetric:
    return PackCandidateMetric(
        metric_name=name,
        template_id=f"{name}_daily",
        display_name="SUM(GMV) daily",
        definition="Daily sum of GMV",
        unit="unknown",
        source_schema="adstable",
        source_table="ads_profit_order",
        aggregation_column="GMV",
        time_column="日期",
        dimensions=("日期",),
        sql_dialect="mysql",
        sql="select `日期`, sum(`GMV`) as value from `adstable`.`ads_profit_order` where `日期` >= :start_date and `日期` < :end_date group by `日期` limit :limit",
        rationale="numeric column (GMV) on table with time column 日期",
    )


class TestWriteProposal:
    def test_writes_proposal_file(self, tmp_path: Path) -> None:
        path = tmp_path / "proposal.json"
        proposal = write_proposal(
            path,
            inventory=_inventory(),
            candidates=(_candidate(),),
            provider_id="provider:mysql",
            provider_name="Customer-0 MySQL",
            owner="data_platform",
            dialect="mysql",
        )
        assert path.exists()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["status"] == "PROPOSED"
        assert payload["provider_id"] == "provider:mysql"
        assert len(payload["candidates"]) == 1
        assert proposal.proposal_id.startswith("proposal-")

    def test_existing_file_fails_closed(self, tmp_path: Path) -> None:
        path = tmp_path / "proposal.json"
        path.write_text("{}")
        with pytest.raises(FileExistsError, match="proposal already exists"):
            write_proposal(
                path,
                inventory=_inventory(),
                candidates=(_candidate(),),
                provider_id="provider:mysql",
                provider_name="Customer-0 MySQL",
                owner="data_platform",
            )


class TestMaterializePack:
    def _write_proposal(self, tmp_path: Path) -> Path:
        path = tmp_path / "proposal.json"
        write_proposal(
            path,
            inventory=_inventory(),
            candidates=(_candidate(),),
            provider_id="provider:mysql",
            provider_name="Customer-0 MySQL",
            owner="data_platform",
        )
        return path

    def test_materializes_approved_metrics_only(self, tmp_path: Path) -> None:
        proposal_path = self._write_proposal(tmp_path)
        pack_dir = tmp_path / "pack"
        written = materialize_pack(
            proposal_path,
            approved_metrics=("adstable_ads_profit_order_gmv_sum",),
            pack_dir=pack_dir,
            connection={
                "connection_type": "mysql",
                "host": "db.example.com",
                "port": 3306,
                "database": "adstable",
                "username": "app_read",
                "password_env": "MYSQL_PASSWORD",
            },
        )
        assert written == ("adstable_ads_profit_order_gmv_sum",)
        assert (pack_dir / "providers.json").exists()
        assert (pack_dir / "metrics.json").exists()
        assert (pack_dir / "sql_templates.json").exists()
        assert (pack_dir / "manifest.yaml").exists()

        providers = json.loads((pack_dir / "providers.json").read_text(encoding="utf-8"))
        assert providers[0]["provider_id"] == "provider:mysql"
        assert providers[0]["connection"]["password_env"] == "MYSQL_PASSWORD"
        assert "password" not in providers[0]["connection"]

        metrics = json.loads((pack_dir / "metrics.json").read_text(encoding="utf-8"))
        assert len(metrics) == 1
        assert metrics[0]["metric_name"] == "adstable_ads_profit_order_gmv_sum"

    def test_unapproved_metric_fails_closed(self, tmp_path: Path) -> None:
        proposal_path = self._write_proposal(tmp_path)
        pack_dir = tmp_path / "pack"
        with pytest.raises(ValueError, match="approved metrics not present"):
            materialize_pack(
                proposal_path,
                approved_metrics=("nonexistent_metric",),
                pack_dir=pack_dir,
                connection={"connection_type": "mysql"},
            )
        assert not pack_dir.exists()

    def test_inline_secret_rejected(self, tmp_path: Path) -> None:
        proposal_path = self._write_proposal(tmp_path)
        pack_dir = tmp_path / "pack"
        with pytest.raises(ValueError, match="must not carry inline 'password'"):
            materialize_pack(
                proposal_path,
                approved_metrics=("adstable_ads_profit_order_gmv_sum",),
                pack_dir=pack_dir,
                connection={
                    "connection_type": "mysql",
                    "host": "db.example.com",
                    "password": "super-secret",
                },
            )
        assert not pack_dir.exists()

    def test_non_empty_pack_dir_fails_closed(self, tmp_path: Path) -> None:
        proposal_path = self._write_proposal(tmp_path)
        pack_dir = tmp_path / "pack"
        pack_dir.mkdir()
        (pack_dir / "existing.txt").write_text("occupied")
        with pytest.raises(FileExistsError, match="pack dir is not empty"):
            materialize_pack(
                proposal_path,
                approved_metrics=("adstable_ads_profit_order_gmv_sum",),
                pack_dir=pack_dir,
                connection={"connection_type": "mysql"},
            )
