from __future__ import annotations

from agent_os_contracts import MetricContract, SemanticObject


class SemanticRegistry:
    def __init__(
        self,
        *,
        semantic_objects: tuple[SemanticObject, ...] = (),
        metric_contracts: tuple[MetricContract, ...] = (),
    ) -> None:
        self._objects = {item.name: item for item in semantic_objects}
        self._metrics = {item.metric_name: item for item in metric_contracts}

    def resolve_metric(self, metric_name: str) -> MetricContract:
        if metric_name not in self._metrics:
            raise KeyError(f"Unknown metric contract: {metric_name}")
        return self._metrics[metric_name]

    def resolve_object(self, object_name: str) -> SemanticObject:
        if object_name not in self._objects:
            raise KeyError(f"Unknown semantic object: {object_name}")
        return self._objects[object_name]

    def metric_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._metrics))
