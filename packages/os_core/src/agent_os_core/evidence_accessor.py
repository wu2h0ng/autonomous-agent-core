"""Evidence accessor protocol for predicate evaluation.

The evaluator reads evidence through this protocol; the run-time implementation
is wired in step 5 (EvidenceAccessor over event store + artifact reader).
Tests use an in-memory implementation.
"""

from __future__ import annotations

from typing import Any, Protocol


class EvidenceAccessor(Protocol):
    """Read-only access to evidence produced during a run.

    All methods return None when the evidence is absent (not when it is empty).
    Checkers interpret None as INSUFFICIENT_EVIDENCE → UNRESOLVED.
    """

    def artifact_content(self, artifact_id: str) -> bytes | None:
        """Raw artifact bytes by artifact ID."""
        ...

    def artifact_json(self, artifact_id: str) -> Any:
        """Parsed JSON artifact content, or None."""
        ...

    def tool_result(
        self, tool_name: str, *, latest: bool = True
    ) -> dict[str, Any] | None:
        """Most recent (or named) tool call result dict from NODE_COMPLETED events."""
        ...

    def state_snapshot(self, label: str) -> dict[str, Any] | None:
        """Pre/post-run environment snapshot by label (e.g. 'pre-run')."""
        ...
