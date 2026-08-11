from __future__ import annotations

from agent_os_contracts import (
    LinkType,
    MetricContract,
    ObjectLink,
    SemanticObject,
)

from .._metric_aliases import DISPLAY_TO_METRIC


class SemanticRegistry:
    def __init__(
        self,
        *,
        semantic_objects: tuple[SemanticObject, ...] = (),
        metric_contracts: tuple[MetricContract, ...] = (),
        semantic_graph: SemanticGraph | None = None,
    ) -> None:
        self._objects = {item.name: item for item in semantic_objects}
        self._metrics = {item.metric_name: item for item in metric_contracts}
        self._graph = semantic_graph or SemanticGraph()
        for obj in semantic_objects:
            if obj.object_id not in self._graph._objects:
                self._graph.register_object(obj)

    @property
    def graph(self) -> SemanticGraph:
        return self._graph

    def resolve_metric(self, metric_name: str) -> MetricContract:
        if metric_name not in self._metrics:
            raise KeyError(f"Unknown metric contract: {metric_name}")
        return self._metrics[metric_name]

    def try_resolve_metric(self, metric_name: str) -> MetricContract | None:
        return self._metrics.get(metric_name)

    def resolve_object(self, object_name: str) -> SemanticObject:
        if object_name in self._objects:
            return self._objects[object_name]
        try:
            return self._graph.resolve_object(object_name)
        except KeyError:
            raise KeyError(f"Unknown semantic object: {object_name}")

    def neighbors(
        self, object_id_or_name: str, *, direction: str = "outgoing"
    ) -> tuple[ObjectLink, ...]:
        """Return links adjacent to an object via the semantic graph.

        Accepts object_id or name for ergonomics.
        """
        oid = self._graph._name_to_id.get(object_id_or_name, object_id_or_name)
        return self._graph.neighbors(oid, direction=direction)

    def metric_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._metrics))

    def search_metrics(self, query: str | None, limit: int = 20) -> tuple[MetricContract, ...]:
        """Return metric contracts matching ``query`` against name, display name, and aliases.

        Matching is case-insensitive substring search. When ``query`` is empty or
        ``None``, all registered metrics are returned (up to ``limit``), sorted by
        metric name.
        """
        query_lower = (query or "").strip().lower()
        aliases_by_metric: dict[str, set[str]] = {}
        for alias, metric_name in DISPLAY_TO_METRIC.items():
            aliases_by_metric.setdefault(metric_name, set()).add(alias.lower())

        matches: list[MetricContract] = []
        for metric in sorted(self._metrics.values(), key=lambda m: m.metric_name):
            terms = {
                metric.metric_name.lower(),
                metric.display_name.lower(),
            }
            terms.update(aliases_by_metric.get(metric.metric_name, set()))
            if not query_lower or any(query_lower in term for term in terms):
                matches.append(metric)
                if len(matches) >= limit:
                    break
        return tuple(matches)


class SemanticGraph:
    """Typed object-relation graph (Palantir Ontology core / competitive gap).

    Holds registered ``SemanticObject`` instances and typed ``LinkType`` /
    ``ObjectLink`` relations, providing adjacency traversal and path queries
    so evidence/lineage can traverse object relations rather than a flat list.

    This is the skeleton Palantir's "dynamic lineage across data, logic,
    action" traverses; it does not auto-infer links (future, needs ADR).
    """

    def __init__(self) -> None:
        self._objects: dict[str, SemanticObject] = {}
        self._link_types: dict[str, LinkType] = {}
        self._links: list[ObjectLink] = []
        self._name_to_id: dict[str, str] = {}
        self._outgoing: dict[str, list[ObjectLink]] = {}
        self._incoming: dict[str, list[ObjectLink]] = {}

    def register_object(self, obj: SemanticObject) -> None:
        if obj.object_id in self._objects:
            raise ValueError(f"object already registered: {obj.object_id}")
        self._objects[obj.object_id] = obj
        self._name_to_id[obj.name] = obj.object_id
        self._outgoing.setdefault(obj.object_id, [])
        self._incoming.setdefault(obj.object_id, [])

    def register_link_type(self, link_type: LinkType) -> None:
        if link_type.link_type_id in self._link_types:
            raise ValueError(f"link type already registered: {link_type.link_type_id}")
        self._link_types[link_type.link_type_id] = link_type

    def register_link(self, link: ObjectLink) -> None:
        link_type = self._link_types.get(link.link_type_id)
        if link_type is None:
            raise ValueError(f"unknown link type: {link.link_type_id}")
        if link.source_object_id not in self._objects:
            raise ValueError(f"unknown source object: {link.source_object_id}")
        if link.target_object_id not in self._objects:
            raise ValueError(f"unknown target object: {link.target_object_id}")
        source = self._objects[link.source_object_id]
        target = self._objects[link.target_object_id]
        if source.object_type != link_type.source_object_type:
            raise ValueError(
                f"link {link.link_id} source object type "
                f"{source.object_type!r} does not match link type "
                f"{link_type.source_object_type!r}"
            )
        if target.object_type != link_type.target_object_type:
            raise ValueError(
                f"link {link.link_id} target object type "
                f"{target.object_type!r} does not match link type "
                f"{link_type.target_object_type!r}"
            )
        self._links.append(link)
        self._outgoing.setdefault(link.source_object_id, []).append(link)
        self._incoming.setdefault(link.target_object_id, []).append(link)

    def resolve_object(self, object_id_or_name: str) -> SemanticObject:
        """Resolve by object_id or name (SemanticRegistry uses name; support both)."""
        if object_id_or_name in self._objects:
            return self._objects[object_id_or_name]
        for obj in self._objects.values():
            if obj.name == object_id_or_name:
                return obj
        raise KeyError(f"unknown semantic object: {object_id_or_name}")

    def objects(self) -> tuple[SemanticObject, ...]:
        return tuple(self._objects.values())

    def link_types(self) -> tuple[LinkType, ...]:
        return tuple(self._link_types.values())

    def links(self) -> tuple[ObjectLink, ...]:
        return tuple(self._links)

    def neighbors(self, object_id: str, *, direction: str = "outgoing") -> tuple[ObjectLink, ...]:
        """Return links adjacent to ``object_id``.

        direction: "outgoing" (object as source), "incoming" (object as target),
        or "both".
        """
        out = self._outgoing.get(object_id, [])
        inc = self._incoming.get(object_id, [])
        if direction == "outgoing":
            return tuple(out)
        if direction == "incoming":
            return tuple(inc)
        if direction == "both":
            return tuple(out) + tuple(inc)
        raise ValueError(f"unknown direction: {direction!r}")

    def paths(
        self, source_object_id: str, target_object_id: str, *, max_depth: int = 5
    ) -> tuple[tuple[ObjectLink, ...], ...]:
        """Return all simple paths (no repeated nodes) from source to target.

        Each path is a tuple of ObjectLinks; the path is
        ``[source] --link--> [node] --link--> ... --link--> [target]``.
        Returns an empty tuple when no path exists within ``max_depth``.
        """
        if source_object_id not in self._objects:
            return ()
        if target_object_id not in self._objects:
            return ()
        results: list[tuple[ObjectLink, ...]] = []

        def _dfs(current: str, target: str, visited: set[str], path: list[ObjectLink]) -> None:
            if len(path) >= max_depth and current != target:
                return
            if current == target and path:
                results.append(tuple(path))
                return
            for link in self._outgoing.get(current, []):
                nxt = link.target_object_id
                if nxt in visited:
                    continue
                visited.add(nxt)
                path.append(link)
                _dfs(nxt, target, visited, path)
                path.pop()
                visited.discard(nxt)

        _dfs(source_object_id, target_object_id, {source_object_id}, [])
        return tuple(results)


__all__ = ["SemanticGraph", "SemanticRegistry"]
