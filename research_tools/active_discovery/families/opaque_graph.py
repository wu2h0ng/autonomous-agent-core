from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from typing import Any

from ..canonical import content_digest
from ..contracts import ProbeObservation, ProbeRequest, PublicEnvironmentDescriptor
from ..referee import HiddenScore


class OpaqueGraphError(ValueError):
    """The F4 development family received an invalid hidden configuration."""


@dataclass(frozen=True, slots=True)
class OpaqueGraphSemantics:
    directed: bool
    remove_missing_error: bool
    allow_self_loop: bool

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, bool)
            for value in (
                self.directed,
                self.remove_missing_error,
                self.allow_self_loop,
            )
        ):
            raise OpaqueGraphError("graph switches must be booleans")


@dataclass(frozen=True, slots=True)
class OpaqueGraphSnapshot:
    edges: tuple[tuple[str, str], ...]
    state_digest: str


def _opaque(seed: int, role: str, prefix: str) -> str:
    return f"{prefix}_{content_digest('opaque-f4-label', {'seed': seed, 'role': role})[:12]}"


class OpaqueGraphFamily:
    """F4: deterministic relation mutation and traversal behind opaque labels."""

    def __init__(self, *, seed: int, semantics: OpaqueGraphSemantics) -> None:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise OpaqueGraphError("seed must be an integer")
        self._seed = seed
        self._semantics = semantics
        self._environment_id = _opaque(seed, "environment", "env")
        self._operation_id = _opaque(seed, "operation", "op")
        self._action_field = _opaque(seed, "action-field", "f")
        self._left_field = _opaque(seed, "left-field", "f")
        self._right_field = _opaque(seed, "right-field", "f")
        self._add_token = _opaque(seed, "add-token", "k")
        self._remove_token = _opaque(seed, "remove-token", "k")
        self._query_token = _opaque(seed, "query-token", "k")
        self._reachable_field = _opaque(seed, "reachable-field", "o")
        self._count_field = _opaque(seed, "count-field", "o")
        self._hops_field = _opaque(seed, "hops-field", "o")
        self._true_token = _opaque(seed, "true-token", "v")
        self._false_token = _opaque(seed, "false-token", "v")
        self._error_token = _opaque(seed, "error-token", "e")
        self._edges: set[tuple[str, str]] = set()
        self._initial_state_digest = self.state_digest()

    def public_descriptor(self) -> PublicEnvironmentDescriptor:
        return PublicEnvironmentDescriptor.create(
            environment_id=self._environment_id,
            operation_id=self._operation_id,
            schema={
                "inputs": [
                    {"field_id": self._action_field, "shape": "token"},
                    {"field_id": self._left_field, "shape": "string"},
                    {"field_id": self._right_field, "shape": "string"},
                ],
                "command_tokens": [
                    self._add_token,
                    self._remove_token,
                    self._query_token,
                ],
                "outputs": [
                    {"field_id": self._reachable_field, "shape": "boolean"},
                    {"field_id": self._count_field, "shape": "integer"},
                    {"field_id": self._hops_field, "shape": "integer"},
                ],
                "status_domain": [0, 4, 5],
            },
            documentation_fragments=(
                "One opaque token mutates or inspects pairwise relations among identifiers.",
                "Traversal, orientation, and deletion behavior are intentionally unspecified.",
            ),
            initial_state_digest=self._initial_state_digest,
        )

    def state_digest(self) -> str:
        return content_digest(
            "opaque-f4-state",
            {
                "environment_id": self._environment_id,
                "edges": [list(edge) for edge in sorted(self._edges)],
            },
        )

    def snapshot(self) -> OpaqueGraphSnapshot:
        return OpaqueGraphSnapshot(
            edges=tuple(sorted(self._edges)),
            state_digest=self.state_digest(),
        )

    def restore(self, snapshot: OpaqueGraphSnapshot) -> None:
        expected = content_digest(
            "opaque-f4-state",
            {
                "environment_id": self._environment_id,
                "edges": [list(edge) for edge in snapshot.edges],
            },
        )
        if snapshot.state_digest != expected:
            raise OpaqueGraphError("snapshot digest mismatch")
        self._edges = set(snapshot.edges)

    def execute(self, request: ProbeRequest) -> ProbeObservation:
        if request.operation_id != self._operation_id:
            raise OpaqueGraphError("operation id is outside the public descriptor")
        before = self.state_digest()
        if request.expected_state_digest != before:
            raise OpaqueGraphError("request expected state is stale")
        parsed = self._parse(json.loads(request.payload_json))
        if parsed is None:
            return self._observation(
                request=request,
                before=before,
                status_code=4,
                reachable=False,
                hops=-1,
                stderr=self._error_token,
            )
        action, left, right = parsed
        edge = self._edge(left, right)
        status_code = 0
        if left == right and not self._semantics.allow_self_loop:
            status_code = 5
        elif action == self._add_token:
            self._edges.add(edge)
        elif action == self._remove_token:
            if edge not in self._edges and self._semantics.remove_missing_error:
                status_code = 5
            else:
                self._edges.discard(edge)
        reachable, hops = self._reachable(left, right)
        return self._observation(
            request=request,
            before=before,
            status_code=status_code,
            reachable=reachable,
            hops=hops,
            stderr=self._error_token if status_code else "",
        )

    def _parse(self, payload: dict[str, Any]) -> tuple[str, str, str] | None:
        if set(payload) != {
            self._action_field,
            self._left_field,
            self._right_field,
        }:
            return None
        action = payload[self._action_field]
        left = payload[self._left_field]
        right = payload[self._right_field]
        if (
            not isinstance(action, str)
            or action not in {self._add_token, self._remove_token, self._query_token}
            or not isinstance(left, str)
            or not left
            or not isinstance(right, str)
            or not right
        ):
            return None
        return action, left, right

    def _edge(self, left: str, right: str) -> tuple[str, str]:
        if self._semantics.directed:
            return left, right
        return tuple(sorted((left, right)))  # type: ignore[return-value]

    def _reachable(self, left: str, right: str) -> tuple[bool, int]:
        if left == right:
            return True, 0
        queue: deque[tuple[str, int]] = deque(((left, 0),))
        visited = {left}
        while queue:
            current, distance = queue.popleft()
            neighbors: set[str] = set()
            for source, target in self._edges:
                if source == current:
                    neighbors.add(target)
                if not self._semantics.directed and target == current:
                    neighbors.add(source)
            for neighbor in sorted(neighbors):
                if neighbor == right:
                    return True, distance + 1
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, distance + 1))
        return False, -1

    def _observation(
        self,
        *,
        request: ProbeRequest,
        before: str,
        status_code: int,
        reachable: bool,
        hops: int,
        stderr: str,
    ) -> ProbeObservation:
        return ProbeObservation.create(
            episode_id=request.episode_id,
            step_index=request.step_index,
            probe_id=request.probe_id,
            status_code=status_code,
            stdout=self._true_token if reachable else self._false_token,
            stderr=stderr,
            output={
                self._reachable_field: reachable,
                self._count_field: len(self._edges),
                self._hops_field: hops,
            },
            before_state_digest=before,
            after_state_digest=self.state_digest(),
        )

    def hidden_score(
        self, bundle_digest: str, transcript: tuple[ProbeObservation, ...]
    ) -> HiddenScore:
        return HiddenScore(
            score_micros=0,
            details_digest=content_digest(
                "opaque-f4-development-score",
                {
                    "mode": "NOT_EVIDENCE",
                    "bundle_digest": bundle_digest,
                    "transcript": [item.observation_digest for item in transcript],
                },
            ),
        )
