"""Tests for the Domain Pack SDK (ADR-0013 Workstream B)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "sdk" / "src"))

from agent_os_contracts import BusinessAgentTemplate, DomainPack  # noqa: E402
from agent_os_sdk.domain_pack import DomainPackLoader, DomainPackRegistry  # noqa: E402


class DomainPackRegistryTest(unittest.TestCase):
    def test_register_get_and_list(self) -> None:
        registry = DomainPackRegistry()
        pack = DomainPack(
            pack_id="content_commerce",
            name="Content Commerce",
            version="1.0.0",
            domain="content_commerce",
            owner="content_commerce_ops",
            metric_contracts=("gmv",),
            business_agent_templates=("content_commerce_analyst",),
            operation_contracts=(),
            eval_pack_ids=(),
            state="active",
        )
        registry.register(pack)
        self.assertEqual(registry.get("content_commerce"), pack)
        self.assertIsNone(registry.get("missing"))
        self.assertEqual(registry.list_by_domain("content_commerce"), (pack,))
        self.assertEqual(registry.list_by_domain("other"), ())

    def test_get_business_agent_template(self) -> None:
        registry = DomainPackRegistry()
        template = BusinessAgentTemplate(
            template_id="content_commerce_analyst",
            name="Content Commerce Analyst",
            domain="content_commerce",
            responsibilities=("monitor",),
            required_evidence=("metric",),
            allowed_action_types=("propose",),
            default_approval_policy={"R4": "required"},
        )
        pack = DomainPack(
            pack_id="content_commerce",
            name="Content Commerce",
            version="1.0.0",
            domain="content_commerce",
            owner="content_commerce_ops",
            metric_contracts=("gmv",),
            business_agent_templates=("content_commerce_analyst",),
            operation_contracts=(),
            eval_pack_ids=(),
            state="active",
        )
        registry.register(pack)
        registry.register_business_agent_template(template)
        self.assertEqual(
            registry.get_business_agent_template("content_commerce_analyst"),
            template,
        )
        self.assertIsNone(registry.get_business_agent_template("missing"))


class DomainPackLoaderTest(unittest.TestCase):
    def test_load_content_commerce_manifest(self) -> None:
        loader = DomainPackLoader()
        packs = loader.load_from_directory(str(ROOT / "domain_packs" / "content_commerce"))
        self.assertEqual(len(packs), 1)
        pack = packs[0]
        self.assertEqual(pack.pack_id, "content_commerce")
        self.assertEqual(pack.domain, "content_commerce")
        self.assertIn("gmv", pack.metric_contracts)
        self.assertIn("content_commerce_analyst", pack.business_agent_templates)


if __name__ == "__main__":
    unittest.main()
