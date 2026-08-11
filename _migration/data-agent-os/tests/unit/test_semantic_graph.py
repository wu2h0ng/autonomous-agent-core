"""Test-first: typed object-relation graph (Palantir Ontology core / competitive gap).

Covers the semantic layer deepening: ObjectType properties, LinkType relations,
ObjectLink instances, and SemanticGraph traversal (adjacency + path queries).
"""

from __future__ import annotations

import unittest

from agent_os_contracts import (
    ObjectLink,
    ObjectProperty,
    SemanticObject,
    LinkType,
)
from agent_os_core.semantic_runtime import SemanticGraph


def _obj(name: str, otype: str = "entity", **kw) -> SemanticObject:
    base = dict(
        object_id=f"obj-{name}",
        name=name,
        object_type=otype,
        description=f"{name} object",
        owner="ops",
    )
    base.update(kw)
    return SemanticObject(**base)


class SemanticObjectPropertiesTest(unittest.TestCase):
    def test_object_carries_properties(self) -> None:
        obj = _obj(
            "campaign",
            properties=(
                ObjectProperty(name="campaign_id", data_type="string", required=True),
                ObjectProperty(name="budget", data_type="decimal", required=False),
            ),
        )
        self.assertEqual(len(obj.properties), 2)
        self.assertEqual(obj.properties[0].name, "campaign_id")

    def test_object_without_properties_backward_compatible(self) -> None:
        obj = _obj("simple")
        self.assertEqual(obj.properties, ())


class LinkTypeTest(unittest.TestCase):
    def test_link_type_definition(self) -> None:
        lt = LinkType(
            link_type_id="lt-campaign-product",
            name="drives",
            source_object_type="campaign",
            target_object_type="product",
            description="campaign drives product sales",
        )
        self.assertEqual(lt.source_object_type, "campaign")
        self.assertEqual(lt.target_object_type, "product")

    def test_link_type_rejects_same_source_target(self) -> None:
        with self.assertRaises(ValueError):
            LinkType(
                link_type_id="lt-self",
                name="self",
                source_object_type="campaign",
                target_object_type="campaign",
                description="",
            )


class ObjectLinkTest(unittest.TestCase):
    def test_link_instance(self) -> None:
        link = ObjectLink(
            link_id="link-1",
            link_type_id="lt-campaign-product",
            source_object_id="obj-campaign",
            target_object_id="obj-product",
        )
        self.assertEqual(link.source_object_id, "obj-campaign")
        self.assertEqual(link.target_object_id, "obj-product")


class SemanticGraphTest(unittest.TestCase):
    def _graph(self) -> SemanticGraph:
        g = SemanticGraph()
        g.register_object(_obj("campaign", "campaign"))
        g.register_object(_obj("product", "product"))
        g.register_object(_obj("order", "order"))
        g.register_link_type(
            LinkType(
                link_type_id="lt-cp",
                name="drives",
                source_object_type="campaign",
                target_object_type="product",
                description="",
            )
        )
        g.register_link_type(
            LinkType(
                link_type_id="lt-po",
                name="has",
                source_object_type="product",
                target_object_type="order",
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
        g.register_link(
            ObjectLink(
                link_id="l2",
                link_type_id="lt-po",
                source_object_id="obj-product",
                target_object_id="obj-order",
            )
        )
        return g

    def test_resolve_object(self) -> None:
        g = self._graph()
        obj = g.resolve_object("campaign")
        self.assertEqual(obj.object_type, "campaign")

    def test_resolve_unknown_object_raises(self) -> None:
        g = self._graph()
        with self.assertRaises(KeyError):
            g.resolve_object("nope")

    def test_neighbors_outgoing(self) -> None:
        g = self._graph()
        neighbors = g.neighbors("obj-campaign", direction="outgoing")
        self.assertEqual(len(neighbors), 1)
        self.assertEqual(neighbors[0].target_object_id, "obj-product")

    def test_neighbors_incoming(self) -> None:
        g = self._graph()
        neighbors = g.neighbors("obj-order", direction="incoming")
        self.assertEqual(len(neighbors), 1)
        self.assertEqual(neighbors[0].source_object_id, "obj-product")

    def test_path_finds_two_hop(self) -> None:
        g = self._graph()
        paths = g.paths("obj-campaign", "obj-order", max_depth=3)
        self.assertTrue(len(paths) >= 1)
        # path: campaign -> product -> order
        first = paths[0]
        ids = [first[0].source_object_id] + [link.target_object_id for link in first]
        self.assertEqual(ids, ["obj-campaign", "obj-product", "obj-order"])

    def test_path_no_connection_returns_empty(self) -> None:
        g = self._graph()
        g.register_object(_obj("isolated", "isolated"))
        paths = g.paths("obj-campaign", "obj-isolated", max_depth=3)
        self.assertEqual(paths, ())

    def test_register_link_requires_known_link_type(self) -> None:
        g = self._graph()
        with self.assertRaises(ValueError):
            g.register_link(
                ObjectLink(
                    link_id="bad",
                    link_type_id="nonexistent",
                    source_object_id="obj-campaign",
                    target_object_id="obj-product",
                )
            )

    def test_register_link_requires_known_objects(self) -> None:
        g = self._graph()
        with self.assertRaises(ValueError):
            g.register_link(
                ObjectLink(
                    link_id="bad",
                    link_type_id="lt-cp",
                    source_object_id="unknown",
                    target_object_id="obj-product",
                )
            )

    def test_link_type_type_mismatch_rejected(self) -> None:
        g = self._graph()
        with self.assertRaises(ValueError):
            g.register_link(
                ObjectLink(
                    link_id="bad",
                    link_type_id="lt-cp",  # expects campaign->product
                    source_object_id="obj-order",  # wrong type
                    target_object_id="obj-product",
                )
            )


if __name__ == "__main__":
    unittest.main()
