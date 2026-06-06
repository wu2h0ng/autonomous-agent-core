"""Knowledge-asset building and storage for the trusted loop's back half.

This module turns a completed decision loop (``EvidenceChain`` + ``ActionProposal``,
optionally enriched with a ``FeedbackEvent``) into a reusable ``KnowledgeAsset``
candidate, and provides an in-memory store with dedup/versioning so the same
source trace never spawns duplicate candidates.

OS Core stays domain-independent: derivation is driven entirely by the generic
contract fields (metric name, question, owner, outcome) and contains no
domain-, customer-, or connector-specific logic.
"""

from __future__ import annotations

import hashlib
import json

from agent_os_contracts import (
    ActionProposal,
    EvidenceChain,
    FeedbackEvent,
    KnowledgeAsset,
    LifecycleState,
)

__all__ = ["KnowledgeAssetBuilder", "KnowledgeStore"]

DEFAULT_ASSET_TYPE = "decision_loop"


class KnowledgeAssetBuilder:
    """Build ``KnowledgeAsset`` candidates from completed decision loops."""

    def build(
        self,
        *,
        evidence_chain: EvidenceChain,
        action_proposal: ActionProposal,
        trace_id: str,
        feedback: FeedbackEvent | None = None,
        asset_type: str = DEFAULT_ASSET_TYPE,
    ) -> KnowledgeAsset:
        """Produce a DRAFT ``KnowledgeAsset`` candidate capturing the lesson.

        Args:
            evidence_chain: The evidence backing the decision. Drives the
                title (metric + question) and owner (metric contract owner).
            action_proposal: The proposal the loop produced.
            trace_id: The originating trace; becomes ``source_trace_id``.
            feedback: Optional feedback that, when present, is folded into the
                candidate's identity so a reviewed lesson is distinct from an
                unreviewed one.
            asset_type: Classification of the asset. Defaults to
                ``"decision_loop"``.

        The ``asset_id`` is derived deterministically from the trace, metric,
        proposal, and feedback so identical inputs yield identical ids.
        """
        if not trace_id:
            raise ValueError("trace_id is required to build a KnowledgeAsset")

        metric_name = evidence_chain.metric_contract.metric_name
        question = evidence_chain.intent.question
        owner = evidence_chain.metric_contract.owner or action_proposal.target_object

        title = self._derive_title(metric_name=metric_name, question=question)
        asset_id = self._derive_id(
            trace_id=trace_id,
            metric_name=metric_name,
            proposal_id=action_proposal.proposal_id,
            recommended_action=action_proposal.recommended_action,
            feedback_id=feedback.feedback_id if feedback else None,
        )
        return KnowledgeAsset(
            asset_id=asset_id,
            title=title,
            asset_type=asset_type,
            source_trace_id=trace_id,
            owner=owner,
            state=LifecycleState.DRAFT,
        )

    @staticmethod
    def _derive_title(*, metric_name: str, question: str) -> str:
        return f"[{metric_name}] {question}"

    @staticmethod
    def _derive_id(
        *,
        trace_id: str,
        metric_name: str,
        proposal_id: str,
        recommended_action: str,
        feedback_id: str | None,
    ) -> str:
        payload = json.dumps(
            {
                "trace_id": trace_id,
                "metric_name": metric_name,
                "proposal_id": proposal_id,
                "recommended_action": recommended_action,
                "feedback_id": feedback_id,
            },
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
        return f"knowledge-{digest}"


class KnowledgeStore:
    """In-memory store of ``KnowledgeAsset`` candidates with dedup by trace.

    Dedup key is ``source_trace_id``: registering a candidate for a trace that is
    already known is a no-op that returns the originally registered asset. A
    per-trace version counter records how many distinct candidates are stored for
    that trace (always 1 under pure dedup); ``register_version`` can bump it when
    a genuinely new version supersedes the prior one.
    """

    def __init__(self) -> None:
        self._by_trace: dict[str, KnowledgeAsset] = {}
        self._versions: dict[str, int] = {}

    def register(self, asset: KnowledgeAsset) -> KnowledgeAsset:
        """Register a candidate, deduping on ``source_trace_id``.

        Returns the asset now associated with the trace: the freshly registered
        one on first sight, or the previously registered one on a duplicate. A
        duplicate is a no-op and does not change the stored version count.
        """
        key = asset.source_trace_id
        if key is None:
            raise ValueError("KnowledgeAsset.source_trace_id is required for dedup")

        if key in self._by_trace:
            return self._by_trace[key]

        self._by_trace[key] = asset
        self._versions[key] = 1
        return asset

    def register_version(self, asset: KnowledgeAsset) -> KnowledgeAsset:
        """Replace the stored candidate for a trace with a new version.

        Unlike :meth:`register`, this supersedes any existing candidate for the
        same ``source_trace_id`` and increments the version counter. Use when a
        genuinely revised lesson should overwrite the prior one.
        """
        key = asset.source_trace_id
        if key is None:
            raise ValueError("KnowledgeAsset.source_trace_id is required for dedup")

        self._by_trace[key] = asset
        self._versions[key] = self._versions.get(key, 0) + 1
        return asset

    def get_by_trace(self, trace_id: str) -> KnowledgeAsset | None:
        """Return the registered candidate for ``trace_id``, or ``None``."""
        return self._by_trace.get(trace_id)

    def version_of(self, trace_id: str) -> int:
        """Return the stored version count for ``trace_id`` (0 if none)."""
        return self._versions.get(trace_id, 0)

    def all_assets(self) -> tuple[KnowledgeAsset, ...]:
        """Return every registered (deduped) candidate."""
        return tuple(self._by_trace.values())
