"""MySQL Data Agent query capability tests (fake driver, no network).

The capability is the MySQL counterpart of SQLiteDataQueryCapability: same
broker-facing receipt shape, provider locked to ``provider:mysql``, AST gate
in the mysql dialect enforced before the driver is touched, and driver
failures mapped to QUERY_EXECUTION_FAILED receipts instead of exceptions.
Secrets are injected at composition time only and never rendered.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from datetime import datetime, timezone
from decimal import Decimal

from domain_packs.data_agent.runtime import (
    DATA_QUERY_CAPABILITY_ID,
    MySqlDataQueryCapability,
    MySqlDataQueryConfig,
)
from agent_os_contracts import (
    ActionContract,
    CorrectionEpochVector,
    ReceiptStatus,
    ResourceBudget,
)


MYSQL_SQL = (
    "select `日期`, sum(`GMV`) as value from `adstable`.`ads_profit_order` "
    "where `日期` >= :start_date and `日期` < :end_date "
    "group by `日期` limit :limit"
)


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.description = tuple((k, None) for k in (rows[0] if rows else {}).keys())

    def execute(self, sql: str, parameters: dict[str, Any]) -> None:
        return None

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    def close(self) -> None:
        return None


class FakeConnection:
    def __init__(self, rows: list[dict[str, Any]], calls: list[str]) -> None:
        self._rows = rows
        self._calls = calls

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._rows)

    def close(self) -> None:
        return None


class FailingConnection:
    def cursor(self) -> None:
        raise RuntimeError("driver boom")

    def close(self) -> None:
        return None


def _action(payload: dict[str, Any]) -> ActionContract:
    return ActionContract(
        action_id="action:test",
        task_id="task:test",
        run_id="run:test",
        node_id="data-query",
        principal_id="user:local",
        tenant_id="tenant:local",
        workspace_id="workspace:local",
        capability_id=DATA_QUERY_CAPABILITY_ID,
        capability_version="1",
        arguments_json=json.dumps(payload),
        risk_tier=0,
        idempotency_key="idempotency:test",
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=30,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        policy_version="policy-1",
        observed_correction_epochs=CorrectionEpochVector(
            task_epoch=0, run_epoch=0, capability_epoch=0
        ),
        expected_outcome_id="expected:test",
        candidate_envelope_id="envelope:test",
        created_at=datetime.now(timezone.utc),
    )


def _capability(
    connect: Any, allowed_schemas: tuple[str, ...] = ("adstable",)
) -> MySqlDataQueryCapability:
    return MySqlDataQueryCapability(
        MySqlDataQueryConfig(
            host="db.example.com",
            port=3306,
            database="adstable",
            username="app_read",
            password="unit-test-secret",
        ),
        allowed_schemas=allowed_schemas,
        _connect=connect,
    )


def test_rejects_non_mysql_provider_contract() -> None:
    calls: list[str] = []
    capability = _capability(lambda **kw: FakeConnection([], calls))
    effect = capability.execute(
        _action(
            {
                "query_id": "query:1",
                "sql": MYSQL_SQL,
                "parameters": {"start_date": "2026-08-01", "end_date": "2026-08-19", "limit": 10},
                "provider_contract_id": "provider:sqlite",
            }
        )
    )

    assert effect.status == ReceiptStatus.FAILED
    assert effect.error_code == "UNSUPPORTED_PROVIDER_CONTRACT"
    assert calls == []


def test_rejects_invalid_arguments() -> None:
    capability = _capability(lambda **kw: FakeConnection([], []))
    effect = capability.execute(
        _action(
            {
                "query_id": "query:1",
                "sql": 42,
                "parameters": "not-a-dict",
                "provider_contract_id": "provider:mysql",
            }
        )
    )

    assert effect.status == ReceiptStatus.FAILED
    assert effect.error_code == "INVALID_QUERY_ARGUMENTS"


def test_blocks_non_select_before_touching_driver() -> None:
    calls: list[str] = []
    capability = _capability(lambda **kw: FakeConnection([], calls))
    with pytest.raises(Exception, match="SQL_SAFETY_DENIED"):
        capability.execute(
            _action(
                {
                    "query_id": "query:1",
                    "sql": "delete from `adstable`.`ads_profit_order` where `日期` >= :start_date",
                    "parameters": {"start_date": "2026-08-01"},
                    "provider_contract_id": "provider:mysql",
                }
            )
        )
    assert calls == []


def test_successful_query_returns_receipt_shape() -> None:
    calls: list[str] = []
    rows = [{"日期": "2026-08-12", "value": 1234.5}]
    capability = _capability(lambda **kw: FakeConnection(rows, calls))
    effect = capability.execute(
        _action(
            {
                "query_id": "query:1",
                "sql": MYSQL_SQL,
                "parameters": {"start_date": "2026-08-01", "end_date": "2026-08-19", "limit": 10},
                "provider_contract_id": "provider:mysql",
            }
        )
    )

    assert effect.status == ReceiptStatus.SUCCEEDED
    assert effect.output["query_id"] == "query:1"
    assert effect.output["row_count"] == 1
    parsed = json.loads(effect.output["rows_json"])
    assert parsed == rows
    assert len(effect.output["sql_fingerprint"]) == 64
    assert len(effect.output["query_result_digest"]) == 64
    assert capability.execution_count == 1


def test_driver_failure_maps_to_failed_receipt() -> None:
    capability = _capability(lambda **kw: FailingConnection())
    effect = capability.execute(
        _action(
            {
                "query_id": "query:1",
                "sql": MYSQL_SQL,
                "parameters": {"start_date": "2026-08-01", "end_date": "2026-08-19", "limit": 10},
                "provider_contract_id": "provider:mysql",
            }
        )
    )

    assert effect.status == ReceiptStatus.FAILED
    assert effect.error_code == "QUERY_EXECUTION_FAILED"


def test_config_from_env_resolves_secret() -> None:
    import os

    os.environ["UNIT_TEST_MYSQL_PASSWORD"] = "env-secret"
    try:
        config = MySqlDataQueryConfig.from_env(
            host="db.example.com",
            port=3306,
            database="adstable",
            username="app_read",
            password_env="UNIT_TEST_MYSQL_PASSWORD",
        )
    finally:
        del os.environ["UNIT_TEST_MYSQL_PASSWORD"]

    assert config.password == "env-secret"
    assert "env-secret" not in repr(config)
    assert "unit-test-secret" not in repr(
        MySqlDataQueryConfig(
            host="h", port=3306, database="d", username="u", password="unit-test-secret"
        )
    )


def test_config_from_env_missing_secret_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNIT_TEST_MISSING_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="UNIT_TEST_MISSING_PASSWORD"):
        MySqlDataQueryConfig.from_env(
            host="h",
            port=3306,
            database="d",
            username="u",
            password_env="UNIT_TEST_MISSING_PASSWORD",
        )
