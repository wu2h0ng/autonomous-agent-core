"""SPINE-1 batch 9: Data Agent concrete connectors + content_commerce sample pack."""

from __future__ import annotations

from pathlib import Path

from domain_packs.data_agent.connectors.action_record.connector import (
    ActionRecordConnector,
    ActionRecordStore,
)
from domain_packs.data_agent.connectors.manual_review.connector import ManualReviewConnector
from domain_packs.data_agent.domain_contracts import OperationContract
from domain_packs.data_agent.metric_contract_loader import load_metric_contract

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _operation() -> OperationContract:
    return OperationContract(
        operation_id="op-1",
        name="notify finance",
        target_connector="manual_review",
        risk_level="R2",
        approval_required=True,
        dry_run_required=False,
        rollback_supported=False,
        snapshot_required=False,
        snapshot_id=None,
        compensating_action=None,
        connector_name="manual_review",
        action_type="notify",
        idempotency_key="idem-1",
        auto_executable=False,
        required_policy_guardrails=(),
    )


def test_manual_review_connector_executes_safe_noop() -> None:
    connector = ManualReviewConnector()

    result = connector.execute(_operation(), {"message": "review me"})

    assert connector.connector_name == "manual_review"
    assert connector.can_rollback() is False
    assert isinstance(result, dict)


def test_action_record_connector_snapshots_executes_and_rolls_back() -> None:
    store = ActionRecordStore()
    connector = ActionRecordConnector(store=store)
    operation = _operation()

    snapshot = connector.take_snapshot(operation)
    executed = connector.execute(operation, {"note": "reversible"})

    assert connector.can_rollback() is True
    assert isinstance(executed, dict)
    if snapshot is not None:
        assert isinstance(connector.rollback(snapshot), dict)


def test_content_commerce_sample_pack_loads_as_metric_contract() -> None:
    path = _REPO_ROOT / "domain_packs/data_agent/content_commerce/metrics/gmv.yaml"

    contract = load_metric_contract(path)

    assert contract.metric_name == "gmv"
    assert contract.allowed_schemas == ("sales",)
    assert contract.verified_queries[0].template_id == "gmv_daily"
