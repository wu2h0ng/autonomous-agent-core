from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainPack:
    pack_id: str
    name: str
    version: str
    domain: str
    owner: str
    metric_contracts: tuple[str, ...]
    business_agent_templates: tuple[str, ...]
    operation_contracts: tuple[str, ...]
    eval_pack_ids: tuple[str, ...]
    state: str = "draft"  # "draft" | "active" | "deprecated"


@dataclass(frozen=True)
class BusinessAgentTemplate:
    template_id: str
    name: str
    domain: str
    responsibilities: tuple[str, ...]
    required_evidence: tuple[str, ...]
    allowed_action_types: tuple[str, ...]
    default_approval_policy: dict[str, str]


__all__ = [
    "BusinessAgentTemplate",
    "DomainPack",
]
