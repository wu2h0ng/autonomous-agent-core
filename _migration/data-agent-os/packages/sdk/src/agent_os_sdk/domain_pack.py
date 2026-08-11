"""Domain Pack SDK: registry and loader for DomainPack contracts (ADR-0013 Workstream B)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from agent_os_contracts import BusinessAgentTemplate, DomainPack


class DomainPackRegistry:
    """In-memory registry of DomainPacks and their BusinessAgentTemplates."""

    def __init__(self) -> None:
        self._packs: dict[str, DomainPack] = {}
        self._templates: dict[str, BusinessAgentTemplate] = {}

    def register(self, pack: DomainPack) -> None:
        """Register a domain pack."""
        self._packs[pack.pack_id] = pack

    def register_business_agent_template(self, template: BusinessAgentTemplate) -> None:
        """Register a business agent template independently of a pack load."""
        self._templates[template.template_id] = template

    def get(self, pack_id: str) -> DomainPack | None:
        """Return the registered pack with ``pack_id``, or ``None``."""
        return self._packs.get(pack_id)

    def list_by_domain(self, domain: str) -> tuple[DomainPack, ...]:
        """Return all registered packs whose ``domain`` matches."""
        return tuple(pack for pack in self._packs.values() if pack.domain == domain)

    def get_business_agent_template(self, template_id: str) -> BusinessAgentTemplate | None:
        """Return a registered business agent template by id, or ``None``."""
        return self._templates.get(template_id)


class DomainPackLoader:
    """Load DomainPack manifests from a directory of YAML/JSON files."""

    def load_from_directory(self, path: str) -> tuple[DomainPack, ...]:
        """Load all domain pack manifests found in ``path``.

        A manifest may define a single pack with ``domain_pack`` and
        ``business_agent_templates`` top-level keys, or a list of such packs.
        """
        target = Path(path)
        if target.is_file():
            manifest_files = [target]
        else:
            manifest_files = sorted(
                p
                for p in target.iterdir()
                if p.is_file() and p.stem == "manifest" and p.suffix in {".yaml", ".yml", ".json"}
            )

        packs: list[DomainPack] = []
        for manifest_file in manifest_files:
            raw = self._read_file(manifest_file)
            if isinstance(raw, list):
                for item in raw:
                    packs.append(self._build_pack(item))
            elif isinstance(raw, dict):
                packs.append(self._build_pack(raw))
            else:
                raise ValueError(f"Manifest {manifest_file} must contain a dict or list of dicts")
        return tuple(packs)

    def _read_file(self, path: Path) -> Any:
        with path.open("r", encoding="utf-8") as fh:
            if path.suffix == ".json":
                return json.load(fh)
            return yaml.safe_load(fh)

    def _build_pack(self, raw: dict[str, Any]) -> DomainPack:
        pack_spec = raw.get("domain_pack", raw)
        if not isinstance(pack_spec, dict):
            raise ValueError("Manifest must contain a 'domain_pack' dict")

        templates = raw.get("business_agent_templates", ())
        template_ids = tuple(
            t["template_id"] if isinstance(t, dict) else t.template_id for t in templates
        )

        return DomainPack(
            pack_id=pack_spec["pack_id"],
            name=pack_spec["name"],
            version=str(pack_spec["version"]),
            domain=pack_spec["domain"],
            owner=pack_spec["owner"],
            metric_contracts=tuple(pack_spec.get("metric_contracts", ())),
            business_agent_templates=template_ids
            if template_ids
            else tuple(pack_spec.get("business_agent_templates", ())),
            operation_contracts=tuple(pack_spec.get("operation_contracts", ())),
            eval_pack_ids=tuple(pack_spec.get("eval_pack_ids", ())),
            state=pack_spec.get("state", "draft"),
        )

    def load_templates_from_directory(self, path: str) -> tuple[BusinessAgentTemplate, ...]:
        """Load all business agent templates defined in manifests under ``path``."""
        target = Path(path)
        if target.is_file():
            manifest_files = [target]
        else:
            manifest_files = sorted(
                p
                for p in target.iterdir()
                if p.is_file() and p.stem == "manifest" and p.suffix in {".yaml", ".yml", ".json"}
            )

        templates: list[BusinessAgentTemplate] = []
        for manifest_file in manifest_files:
            raw = self._read_file(manifest_file)
            if isinstance(raw, list):
                items = raw
            elif isinstance(raw, dict):
                items = [raw]
            else:
                continue
            for item in items:
                for template_spec in item.get("business_agent_templates", ()):
                    templates.append(self._build_template(template_spec))
        return tuple(templates)

    def _build_template(self, raw: dict[str, Any]) -> BusinessAgentTemplate:
        return BusinessAgentTemplate(
            template_id=raw["template_id"],
            name=raw["name"],
            domain=raw["domain"],
            responsibilities=tuple(raw.get("responsibilities", ())),
            required_evidence=tuple(raw.get("required_evidence", ())),
            allowed_action_types=tuple(raw.get("allowed_action_types", ())),
            default_approval_policy=dict(raw.get("default_approval_policy", {})),
        )


__all__ = [
    "DomainPackLoader",
    "DomainPackRegistry",
]
