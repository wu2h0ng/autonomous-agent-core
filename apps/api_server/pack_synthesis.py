"""Proposal persistence and operator-approved pack materialization.

``write_proposal`` serializes a secret-free PackProposal for human review.
``materialize_pack`` writes a domain pack directory containing ONLY the
metrics the operator explicitly approved; every other candidate is dropped.

Approval is an explicit human act (naming metrics on the CLI).  Nothing in
this module self-approves, and inline secrets in the connection spec are
rejected: only ``*_env`` references survive.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agent_os_contracts.domain_pack_synthesis import (
    PackCandidateMetric,
    PackProposal,
    SchemaInventory,
)

_SECRET_FREEZER_FIELDS = ("password", "api_token")
_SECRET_ENV_KEYS = ("password_env", "api_token_env")
_TEMPLATE_DEFAULT_LIMIT = 100
_TEMPLATE_MAX_LIMIT = 1000


def _inventory_digest(inventory: SchemaInventory) -> str:
    canonical = json.dumps(
        [
            [t.schema, t.table, [[c.name, c.data_type] for c in t.columns]]
            for t in inventory.tables
        ],
        ensure_ascii=False,
        sort_keys=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def write_proposal(
    path: Path,
    *,
    inventory: SchemaInventory,
    candidates: tuple[PackCandidateMetric, ...],
    provider_id: str,
    provider_name: str,
    owner: str,
    dialect: str = "mysql",
) -> PackProposal:
    """Serialize a PROPOSED pack for human review (never auto-approved)."""
    proposal = PackProposal(
        proposal_id=f"proposal-{_inventory_digest(inventory)[:12]}",
        status="PROPOSED",
        dialect=dialect,
        provider_id=provider_id,
        provider_name=provider_name,
        owner=owner,
        allowed_schemas=tuple(sorted({t.schema for t in inventory.tables})),
        inventory_sha256=_inventory_digest(inventory),
        candidates=candidates,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"proposal already exists: {path}")
    payload = asdict(proposal)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return proposal


def _proposal_from_payload(payload: dict[str, Any]) -> PackProposal:
    candidates = tuple(
        PackCandidateMetric(
            metric_name=c["metric_name"],
            template_id=c["template_id"],
            display_name=c["display_name"],
            definition=c["definition"],
            unit=c["unit"],
            source_schema=c["source_schema"],
            source_table=c["source_table"],
            aggregation_column=c["aggregation_column"],
            time_column=c["time_column"],
            dimensions=tuple(c["dimensions"]),
            sql_dialect=c["sql_dialect"],
            sql=c["sql"],
            rationale=c["rationale"],
        )
        for c in payload["candidates"]
    )
    return PackProposal(
        proposal_id=payload["proposal_id"],
        status=payload["status"],
        dialect=payload["dialect"],
        provider_id=payload["provider_id"],
        provider_name=payload["provider_name"],
        owner=payload["owner"],
        allowed_schemas=tuple(payload["allowed_schemas"]),
        inventory_sha256=payload["inventory_sha256"],
        candidates=candidates,
    )


def _validated_connection(provider_id: str, connection: dict[str, Any]) -> dict[str, Any]:
    for field in _SECRET_FREEZER_FIELDS:
        if field in connection:
            raise ValueError(
                f"Provider {provider_id!r} connection must not carry inline "
                f"'{field}'; use the matching *_env reference instead."
            )
    cleaned = {
        k: v
        for k, v in connection.items()
        if k
        in (
            *_SECRET_ENV_KEYS,
            "connection_type",
            "host",
            "port",
            "database",
            "username",
            "path",
            "table_id",
            "options",
        )
    }
    if "connection_type" not in cleaned:
        raise ValueError(
            f"Provider {provider_id!r} connection requires 'connection_type'."
        )
    return cleaned


def materialize_pack(
    proposal_path: Path,
    *,
    approved_metrics: tuple[str, ...],
    pack_dir: Path,
    connection: dict[str, Any],
) -> tuple[str, ...]:
    """Write a domain pack from operator-approved candidates only.

    The operator's explicit ``approved_metrics`` list IS the approval act.
    Dangling names fail closed; nothing is written on any error.
    """
    payload = json.loads(Path(proposal_path).read_text(encoding="utf-8"))
    proposal = _proposal_from_payload(payload)
    by_name = {c.metric_name: c for c in proposal.candidates}
    unknown = [m for m in approved_metrics if m not in by_name]
    if unknown:
        raise ValueError(
            f"approved metrics not present in proposal "
            f"{proposal.proposal_id}: {unknown}"
        )
    conn = _validated_connection(proposal.provider_id, connection)

    approved = tuple(by_name[m] for m in approved_metrics)

    providers_row = {
        "provider_id": proposal.provider_id,
        "kind": "warehouse",
        "name": proposal.provider_name,
        "owner": proposal.owner,
        "allowed_schemas": list(proposal.allowed_schemas),
        "data_classification": "internal",
        "supports_query": True,
        "supports_write": False,
        "connection": conn,
    }
    metrics_rows = [
        {
            "metric_name": c.metric_name,
            "display_name": c.display_name,
            "definition": c.definition,
            "owner": proposal.owner,
            "unit": c.unit,
            "allowed_schemas": [c.source_schema],
            "dimensions": list(c.dimensions),
            "verified_queries": [
                {
                    "template_id": c.template_id,
                    "metric_name": c.metric_name,
                    "sql": c.sql,
                    "required_parameters": ["start_date", "end_date", "limit"],
                    "sql_dialect": c.sql_dialect,
                }
            ],
        }
        for c in approved
    ]
    templates_rows = [
        {
            "template_id": c.template_id,
            "metric_name": c.metric_name,
            "sql": c.sql,
            "required_parameters": ["start_date", "end_date", "limit"],
            "sql_dialect": c.sql_dialect,
            "default_limit": _TEMPLATE_DEFAULT_LIMIT,
            "max_limit": _TEMPLATE_MAX_LIMIT,
        }
        for c in approved
    ]
    manifest = (
        "domain_pack:\n"
        f"  pack_id: {pack_dir.name}\n"
        f"  name: {proposal.provider_name}\n"
        "  version: 0.1.0\n"
        f"  domain: {pack_dir.name}\n"
        f"  owner: {proposal.owner}\n"
        "  metric_contracts:\n"
        + "".join(f"    - {c.metric_name}\n" for c in approved)
        + "  business_agent_templates: []\n"
        "  operation_contracts: []\n"
        "  eval_pack_ids: []\n"
        "  state: active\n"
    )

    if pack_dir.exists() and any(pack_dir.iterdir()):
        raise FileExistsError(f"pack dir is not empty: {pack_dir}")
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "providers.json").write_text(
        json.dumps([providers_row], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (pack_dir / "metrics.json").write_text(
        json.dumps(metrics_rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (pack_dir / "sql_templates.json").write_text(
        json.dumps(templates_rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (pack_dir / "manifest.yaml").write_text(manifest, encoding="utf-8")

    return tuple(c.metric_name for c in approved)
