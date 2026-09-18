"""Load MetricContract objects from YAML domain-pack specs.

Rewritten from the donor loader to import the domain-pack-native contracts
(``.metric_contracts``) instead of the donor ``agent_os_contracts`` package.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .metric_contracts import (
    ActionCandidate,
    DataClassification,
    MetricContract,
    QualityContract,
    RiskLevel,
    SQLTemplate,
)


class MetricContractLoadError(Exception):
    """Raised when a metric YAML file cannot be loaded or validated."""


REQUIRED_FIELDS = ("name", "display_name", "definition", "owner", "unit")


def _load_risk_level(value: str | None) -> RiskLevel:
    if value is None:
        return RiskLevel.R2
    try:
        return RiskLevel(value)
    except ValueError as exc:
        raise MetricContractLoadError(f"Invalid risk_level: {value}") from exc


def _load_quality_contract(raw: dict[str, Any] | None) -> QualityContract | None:
    if raw is None:
        return None
    return QualityContract(
        freshness=raw.get("freshness"),
        null_rate=raw.get("null_rate"),
        owner=raw.get("owner"),
    )


def _load_action_candidates(raw: list[dict[str, Any]] | None) -> tuple[ActionCandidate, ...]:
    if raw is None:
        return ()
    candidates: list[ActionCandidate] = []
    for item in raw:
        action_id = item.get("id")
        if not action_id:
            raise MetricContractLoadError("Action candidate missing required 'id' field")
        candidates.append(
            ActionCandidate(
                action_id=action_id,
                trigger=item.get("trigger"),
                risk_level=_load_risk_level(item.get("risk_level")),
                description=item.get("description", ""),
            )
        )
    return tuple(candidates)


def _load_verified_queries(raw: list[dict[str, Any]] | None) -> tuple[SQLTemplate, ...]:
    if raw is None:
        return ()
    templates: list[SQLTemplate] = []
    for item in raw:
        template_id = item.get("template_id")
        metric_name = item.get("metric_name")
        sql = item.get("sql")
        if not template_id or not metric_name or sql is None:
            raise MetricContractLoadError(
                "Verified query missing required 'template_id', 'metric_name', or 'sql'"
            )
        templates.append(
            SQLTemplate(
                template_id=template_id,
                metric_name=metric_name,
                sql=sql,
                required_parameters=tuple(item.get("required_parameters", ())),
                required_time_parameters=tuple(
                    item.get("required_time_parameters", ("start_date", "end_date"))
                ),
                default_limit=int(item.get("default_limit", 100)),
                max_limit=int(item.get("max_limit", 1000)),
                allow_select_star=bool(item.get("allow_select_star", False)),
            )
        )
    return tuple(templates)


def load_metric_contract(path: str | Path) -> MetricContract:
    """Load a single MetricContract from a YAML file."""
    path = Path(path)
    if not path.exists():
        raise MetricContractLoadError(f"Metric contract file not found: {path}")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise MetricContractLoadError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise MetricContractLoadError(f"Metric contract {path} must be a YAML mapping")

    missing = [field for field in REQUIRED_FIELDS if field not in raw]
    if missing:
        raise MetricContractLoadError(
            f"Metric contract {path} missing required fields: {', '.join(missing)}"
        )

    classification = raw.get("data_classification", "internal")
    try:
        data_classification = DataClassification(classification)
    except ValueError as exc:
        raise MetricContractLoadError(
            f"Invalid data_classification '{classification}' in {path}"
        ) from exc

    return MetricContract(
        metric_name=raw["name"],
        display_name=raw["display_name"],
        definition=raw["definition"],
        owner=raw["owner"],
        unit=raw["unit"],
        allowed_schemas=tuple(raw.get("allowed_schemas", ())),
        version=str(raw.get("version", "v1")),
        dimensions=tuple(raw.get("dimensions", ())),
        data_classification=data_classification,
        verified_queries=_load_verified_queries(raw.get("verified_queries")),
        quality_contract=_load_quality_contract(raw.get("quality_contract")),
        action_candidates=_load_action_candidates(raw.get("action_candidates")),
        feedback_metric=raw.get("feedback_metric"),
    )


def load_metric_contracts(directory: str | Path) -> dict[str, MetricContract]:
    """Load all metric YAML files from a directory; maps metric_name -> MetricContract."""
    directory = Path(directory)
    contracts: dict[str, MetricContract] = {}
    for path in sorted(directory.glob("*.yaml")):
        contract = load_metric_contract(path)
        contracts[contract.metric_name] = contract
    for path in sorted(directory.glob("*.yml")):
        contract = load_metric_contract(path)
        contracts[contract.metric_name] = contract
    return contracts
