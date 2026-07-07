"""SemanticRegistry consumes the SemanticGraph (wiring slice).

The registry becomes the single entry point for both metrics AND the
object-relation graph, so evidence/lineage resolution can traverse relations.
"""

from __future__ import annotations

import unittest

from agent_os_contracts import LinkType, ObjectLink, SemanticObject
from agent_os_core.semantic_runtime import SemanticGraph, SemanticRegistry


def _obj(name: str, otype: str) -> SemanticObject:
    return SemanticObject(
        object_id=f"obj-{name}",
        name=name,
        object_type=otype,
        description=f"{name}",
        owner="ops",
    )


class SemanticRegistryGraphTest(unittest.TestCase):
    def _graph(self) -> SemanticGraph:
        g = SemanticGraph()
        g.register_object(_obj("campaign", "campaign"))
        g.register_object(_obj("product", "product"))
        g.register_link_type(
            LinkType(
                link_type_id="lt-cp",
                name="drives",
                source_object_type="campaign",
                target_object_type="product",
                description="",
            )
        )
        g.register_link(
            ObjectLink(
                link_id="l1",
                link_type_id="lt-cp",
                source_object_id="obj-campaign",
                target_object_id="obj-product",
            )
        )
        return g

    def test_registry_holds_graph(self) -> None:
        g = self._graph()
        reg = SemanticRegistry(semantic_graph=g)
        self.assertIs(reg.graph, g)

    def test_registry_resolves_object_via_graph(self) -> None:
        g = self._graph()
        reg = SemanticRegistry(semantic_graph=g)
        obj = reg.resolve_object("campaign")
        self.assertEqual(obj.object_type, "campaign")

    def test_registry_neighbors(self) -> None:
        g = self._graph()
        reg = SemanticRegistry(semantic_graph=g)
        neighbors = reg.neighbors("campaign", direction="outgoing")
        self.assertEqual(len(neighbors), 1)
        self.assertEqual(neighbors[0].target_object_id, "obj-product")

    def test_registry_without_graph_resolve_object_raises(self) -> None:
        reg = SemanticRegistry()
        with self.assertRaises(KeyError):
            reg.resolve_object("anything")

    def test_registry_without_graph_neighbors_returns_empty(self) -> None:
        reg = SemanticRegistry()
        self.assertEqual(reg.neighbors("x"), ())


if __name__ == "__main__":
    unittest.main()
