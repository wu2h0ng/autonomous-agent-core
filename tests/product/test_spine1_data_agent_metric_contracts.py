"""SPINE-1: Data Agent metric contracts, aliases, and YAML loader (domain pack).

Ported from the donor `trusted_loop` contracts + `metric_contract_loader`. Tests would FAIL if the
loader ignored required fields, defaults, or the domain alias maps.
"""

from __future__ import annotations

import pytest

from domain_packs.data_agent.metric_aliases import DISPLAY_TO_METRIC, METRIC_DISPLAY_NAMES
from domain_packs.data_agent.metric_contract_loader import (
    MetricContractLoadError,
    load_metric_contract,
    load_metric_contracts,
)
from domain_packs.data_agent.metric_contracts import DataClassification, RiskLevel

_VALID_YAML = """
name: monthly_gmv
display_name: Monthly GMV
definition: Gross merchandise value over paid orders in the selected window.
owner: revenue_ops
unit: CNY
allowed_schemas:
  - sales
dimensions:
  - month
  - channel
quality_contract:
  freshness: 24h
  null_rate: "<0.01"
verified_queries:
  - template_id: monthly_gmv_by_channel
    metric_name: monthly_gmv
    sql: |
      SELECT SUM(order_amount) AS monthly_gmv FROM sales.orders LIMIT 1000
action_candidates:
  - id: investigate_gmv_drop
    trigger: monthly_gmv < baseline * 0.9
    risk_level: R3
feedback_metric: weekly_gmv_recovery
"""


def _write(tmp_path, name: str, text: str):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_valid_metric_contract(tmp_path) -> None:
    contract = load_metric_contract(_write(tmp_path, "monthly_gmv.yaml", _VALID_YAML))

    assert contract.metric_name == "monthly_gmv"
    assert contract.display_name == "Monthly GMV"
    assert contract.allowed_schemas == ("sales",)
    assert contract.dimensions == ("month", "channel")
    assert contract.data_classification is DataClassification.INTERNAL
    assert contract.quality_contract is not None
    assert contract.quality_contract.freshness == "24h"
    assert len(contract.verified_queries) == 1
    assert contract.verified_queries[0].template_id == "monthly_gmv_by_channel"
    assert len(contract.action_candidates) == 1
    assert contract.action_candidates[0].risk_level is RiskLevel.R3
    assert contract.feedback_metric == "weekly_gmv_recovery"


def test_action_candidate_defaults_to_r2_without_risk_level(tmp_path) -> None:
    text = _VALID_YAML.replace("    risk_level: R3\n", "")
    contract = load_metric_contract(_write(tmp_path, "m.yaml", text))

    assert contract.action_candidates[0].risk_level is RiskLevel.R2


def test_missing_required_field_raises(tmp_path) -> None:
    text = _VALID_YAML.replace("owner: revenue_ops\n", "")
    with pytest.raises(MetricContractLoadError, match="owner"):
        load_metric_contract(_write(tmp_path, "m.yaml", text))


def test_missing_file_raises(tmp_path) -> None:
    with pytest.raises(MetricContractLoadError, match="not found"):
        load_metric_contract(tmp_path / "nope.yaml")


def test_invalid_risk_level_raises(tmp_path) -> None:
    text = _VALID_YAML.replace("risk_level: R3", "risk_level: R9")
    with pytest.raises(MetricContractLoadError, match="risk_level"):
        load_metric_contract(_write(tmp_path, "m.yaml", text))


def test_invalid_data_classification_raises(tmp_path) -> None:
    text = _VALID_YAML + "\ndata_classification: secret\n"
    with pytest.raises(MetricContractLoadError, match="data_classification"):
        load_metric_contract(_write(tmp_path, "m.yaml", text))


def test_non_mapping_yaml_raises(tmp_path) -> None:
    with pytest.raises(MetricContractLoadError, match="mapping"):
        load_metric_contract(_write(tmp_path, "m.yaml", "- just\n- a\n- list\n"))


def test_loads_a_directory_of_contracts(tmp_path) -> None:
    _write(tmp_path, "a.yaml", _VALID_YAML)
    _write(tmp_path, "b.yml", _VALID_YAML.replace("monthly_gmv", "weekly_roi"))

    contracts = load_metric_contracts(tmp_path)

    assert set(contracts) == {"monthly_gmv", "weekly_roi"}


def test_metric_aliases_cover_display_and_chinese_forms() -> None:
    assert METRIC_DISPLAY_NAMES["gmv"] == "GMV"
    assert DISPLAY_TO_METRIC["gmv"] == "gmv"
    assert DISPLAY_TO_METRIC["成交额"] == "gmv"
    assert DISPLAY_TO_METRIC["转化率"] == "conversion_rate"
