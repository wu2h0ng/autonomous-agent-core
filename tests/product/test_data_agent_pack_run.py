"""Governed execution path for materialized domain packs (run-pack-metric).

Covers the loop closure: pack files -> load_pack_query validation ->
canonical Task/Commitment/Workflow/ExpectedOutcome -> ActionPipeline ->
MySqlDataQueryCapability -> evidence + observed outcome.  The pymysql
connection is faked through the ``connect`` seam; no network or driver is
required.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from agent_os_contracts.domain_pack_synthesis import (
    ColumnInventory,
    SchemaInventory,
    TableInventory,
)
from agent_os_core.domain_pack_synthesis import synthesize_pack_candidates
from apps.api_server.pack_run import run_pack_metric
from apps.api_server.pack_synthesis import materialize_pack, write_proposal
from domain_packs.data_agent.contracts import DataAgentStatus
from domain_packs.data_agent.pack_loader import load_pack_query

METRIC = "adstable_ads_profit_order_gmv_sum"
PASSWORD_ENV = "FAKE_RDS_PASSWORD_FOR_TEST"


class _FakeCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self.executed: tuple[str, dict] | None = None

    def execute(self, sql: str, params: dict) -> None:
        self.executed = (sql, params)

    def fetchall(self) -> list[dict]:
        return list(self._rows)

    def close(self) -> None:
        return None


class _FakeConnection:
    def __init__(self, rows: list[dict]) -> None:
        self.fake_cursor = _FakeCursor(rows)
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self.fake_cursor

    def close(self) -> None:
        self.closed = True


def _connection_payload() -> dict:
    return {
        "connection_type": "mysql",
        "host": "rm-example.mysql.rds.aliyuncs.com",
        "port": 3306,
        "database": "dw",
        "username": "ro_user",
        "password_env": PASSWORD_ENV,
    }


def _materialized_pack(tmp_path: Path) -> Path:
    inventory = SchemaInventory(
        tables=(
            TableInventory(
                schema="adstable",
                table="ads_profit_order",
                columns=(
                    ColumnInventory(name="order_date", data_type="date"),
                    ColumnInventory(name="gmv", data_type="decimal"),
                ),
            ),
        )
    )
    candidates = synthesize_pack_candidates(inventory, dialect="mysql")
    assert any(c.metric_name == METRIC for c in candidates)
    proposal_path = tmp_path / "proposal.json"
    write_proposal(
        proposal_path,
        inventory=inventory,
        candidates=candidates,
        provider_id="provider:mysql:minhe",
        provider_name="minhe",
        owner="data_platform",
    )
    pack_dir = tmp_path / "packs" / "minhe"
    materialize_pack(
        proposal_path,
        approved_metrics=(METRIC,),
        pack_dir=pack_dir,
        connection=_connection_payload(),
    )
    return pack_dir


def _run(pack_dir: Path, tmp_path: Path, connection: _FakeConnection, **overrides):
    kwargs = {
        "pack_dir": pack_dir,
        "metric_name": METRIC,
        "start_date": "2026-08-01",
        "end_date": "2026-08-02",
        "database": tmp_path / "agent-os.sqlite3",
        "workspace": tmp_path,
        "connect": lambda: connection,
    }
    kwargs.update(overrides)
    return run_pack_metric(**kwargs)


def test_pack_metric_runs_through_governed_spine(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(PASSWORD_ENV, "s3cret")
    pack_dir = _materialized_pack(tmp_path)
    connection = _FakeConnection(
        [{"order_date": date(2026, 8, 1), "value": Decimal("123.45")}]
    )

    result = _run(pack_dir, tmp_path, connection)

    assert result.status is DataAgentStatus.COMPLETED
    assert result.observed_outcome_id is not None
    assert result.query_result is not None
    # driver-native date/Decimal values are normalized before digesting
    assert result.query_result.rows_json == (
        '[{"order_date":"2026-08-01","value":"123.45"}]'
    )
    assert result.query_result.row_count == 1
    assert result.evidence is not None
    assert result.evidence.provider_contract_id == "provider:mysql:minhe"
    assert result.evidence.generic_evidence_ref.startswith("receipt-")
    assert "provider:mysql:minhe" in result.evidence.lineage_refs
    # named placeholders were translated to pymysql style before dispatch
    assert connection.fake_cursor.executed is not None
    executed_sql, executed_params = connection.fake_cursor.executed
    assert ":start_date" not in executed_sql
    assert "%(start_date)s" in executed_sql
    assert executed_params == {
        "start_date": "2026-08-01",
        "end_date": "2026-08-02",
        "limit": 100,
    }
    assert connection.closed


def test_unapproved_metric_fails_closed_before_any_connection(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv(PASSWORD_ENV, "s3cret")
    pack_dir = _materialized_pack(tmp_path)
    connection = _FakeConnection([])

    with pytest.raises(ValueError, match="METRIC_NOT_APPROVED"):
        _run(pack_dir, tmp_path, connection, metric_name="adstable_unknown_sum")

    assert connection.fake_cursor.executed is None


def test_template_sql_drift_fails_closed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(PASSWORD_ENV, "s3cret")
    pack_dir = _materialized_pack(tmp_path)
    templates_path = pack_dir / "sql_templates.json"
    templates = json.loads(templates_path.read_text(encoding="utf-8"))
    templates[0]["sql"] = templates[0]["sql"].replace("sum(", "avg(")
    templates_path.write_text(json.dumps(templates), encoding="utf-8")

    with pytest.raises(ValueError, match="TEMPLATE_SQL_DRIFT"):
        load_pack_query(
            pack_dir, METRIC, start_date="2026-08-01", end_date="2026-08-02"
        )


def test_consistent_unsafe_sql_rewrite_fails_at_safety_gate(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv(PASSWORD_ENV, "s3cret")
    pack_dir = _materialized_pack(tmp_path)
    evil = "delete from `adstable`.`ads_profit_order`"
    metrics_path = pack_dir / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics[0]["verified_queries"][0]["sql"] = evil
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
    templates_path = pack_dir / "sql_templates.json"
    templates = json.loads(templates_path.read_text(encoding="utf-8"))
    templates[0]["sql"] = evil
    templates_path.write_text(json.dumps(templates), encoding="utf-8")

    with pytest.raises(ValueError, match="SQL_SAFETY_DENIED"):
        load_pack_query(
            pack_dir, METRIC, start_date="2026-08-01", end_date="2026-08-02"
        )


def test_inline_secret_in_connection_fails_closed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(PASSWORD_ENV, "s3cret")
    pack_dir = _materialized_pack(tmp_path)
    providers_path = pack_dir / "providers.json"
    providers = json.loads(providers_path.read_text(encoding="utf-8"))
    providers[0]["connection"]["password"] = "inline-secret"
    providers_path.write_text(json.dumps(providers), encoding="utf-8")

    with pytest.raises(ValueError, match="CONNECTION_INLINE_SECRET"):
        load_pack_query(
            pack_dir, METRIC, start_date="2026-08-01", end_date="2026-08-02"
        )


def test_missing_password_env_fails_closed(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(PASSWORD_ENV, raising=False)
    pack_dir = _materialized_pack(tmp_path)
    connection = _FakeConnection([])

    with pytest.raises(ValueError, match="which is not set"):
        _run(pack_dir, tmp_path, connection)

    assert connection.fake_cursor.executed is None


def test_limit_above_template_max_fails_closed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(PASSWORD_ENV, "s3cret")
    pack_dir = _materialized_pack(tmp_path)

    with pytest.raises(ValueError, match="PARAMETER_INVALID"):
        load_pack_query(
            pack_dir,
            METRIC,
            start_date="2026-08-01",
            end_date="2026-08-02",
            limit=5000,
        )


def test_malformed_date_fails_closed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(PASSWORD_ENV, "s3cret")
    pack_dir = _materialized_pack(tmp_path)

    with pytest.raises(ValueError, match="PARAMETER_INVALID"):
        load_pack_query(
            pack_dir, METRIC, start_date="2026/08/01", end_date="2026-08-02"
        )


def test_reversed_date_window_fails_closed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(PASSWORD_ENV, "s3cret")
    pack_dir = _materialized_pack(tmp_path)

    with pytest.raises(ValueError, match="PARAMETER_INVALID"):
        load_pack_query(
            pack_dir, METRIC, start_date="2026-08-02", end_date="2026-08-01"
        )
