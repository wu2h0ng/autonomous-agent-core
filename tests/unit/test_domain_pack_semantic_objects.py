"""Domain pack semantic objects + runtime factory loading (wiring slice).

Proves content_commerce domain pack defines real business objects (campaign,
ad_group, product, order) and their typed relations, and the RuntimeFactory
loads them into the SemanticRegistry so the graph is real in a live run path.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "domain_packs" / "content_commerce"


class DomainPackSemanticObjectsTest(unittest.TestCase):
    def test_semantic_objects_json_exists(self) -> None:
        self.assertTrue((PACK / "semantic_objects.json").exists())

    def test_semantic_objects_have_types_and_properties(self) -> None:
        data = json.loads((PACK / "semantic_objects.json").read_text())
        ids = {o["object_id"] for o in data["objects"]}
        self.assertIn("obj-campaign", ids)
        self.assertIn("obj-product", ids)
        for obj in data["objects"]:
            self.assertIn("object_type", obj)
            self.assertIn("properties", obj)

    def test_link_types_and_links_defined(self) -> None:
        data = json.loads((PACK / "semantic_objects.json").read_text())
        link_type_ids = {lt["link_type_id"] for lt in data["link_types"]}
        self.assertIn("lt-campaign-product", link_type_ids)
        links = data.get("links", [])
        self.assertGreaterEqual(len(links), 1)
        for lt in data["link_types"]:
            self.assertNotEqual(lt["source_object_type"], lt["target_object_type"])


class RuntimeFactorySemanticGraphTest(unittest.TestCase):
    def test_factory_loads_semantic_objects_into_registry(self) -> None:
        import sys

        for seg in (
            "packages/contracts/src",
            "packages/os_core/src",
            "packages/persistence/src",
            "packages/sdk/src",
            "action_connectors",
            "apps/api_server/src",
        ):
            sys.path.insert(0, str(ROOT / seg))
        from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig

        cfg = RuntimeFactoryConfig(domain_pack_path=PACK)
        factory = ContentCommerceRuntimeFactory(cfg)
        runtime = factory.build()
        # the registry holds a graph with the domain objects
        reg = runtime.semantic_registry
        obj = reg.resolve_object("campaign")
        self.assertEqual(obj.object_type, "campaign")
        # neighbors: campaign -> product exists
        neighbors = reg.neighbors("campaign", direction="outgoing")
        self.assertGreaterEqual(len(neighbors), 1)

    def test_factory_graph_has_path_campaign_to_order(self) -> None:
        import sys

        for seg in (
            "packages/contracts/src",
            "packages/os_core/src",
            "packages/persistence/src",
            "packages/sdk/src",
            "action_connectors",
            "apps/api_server/src",
        ):
            sys.path.insert(0, str(ROOT / seg))
        from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig

        cfg = RuntimeFactoryConfig(domain_pack_path=PACK)
        factory = ContentCommerceRuntimeFactory(cfg)
        runtime = factory.build()
        paths = runtime.semantic_registry.graph.paths("obj-campaign", "obj-order", max_depth=5)
        self.assertGreaterEqual(len(paths), 1)


if __name__ == "__main__":
    unittest.main()
