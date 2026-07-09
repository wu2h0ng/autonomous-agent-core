"""LLM advisor for the strong-locus intervention-gap analyzer.

This is an advisory organ, not a control path. It receives a deterministic gap
report and returns a suggested next action plus any proposed interventions or
alternative datasets. The deterministic `recommend_action()` in the gap analyzer
remains the binding decision; the LLM advice is logged for human review.

When no API key is present, the advisor falls back to a deterministic stub that
mirrors the gap analyzer's own recommendation. This keeps tests cheap and avoids
burning LLM budget for routine harness verification.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, "src")
sys.path.insert(0, "experiments")

try:
    from aac.llm_client import build_backend
except ImportError:
    from llm_client import build_backend


def _deterministic_advice(gap_report: dict[str, Any]) -> dict[str, Any]:
    """Mirror the gap analyzer's recommendation when LLM is unavailable."""
    rec = gap_report.get("recommendation", {})
    action = rec.get("action", "HONEST_NEGATIVE")
    proposed_guides: dict[str, list[str]] = {}
    suggested_datasets: list[str] = []
    reasoning_parts: list[str] = []

    if action == "PROCEED":
        reasoning_parts.append(
            "Enough locked genes already have interventions in this dataset."
        )
    elif action == "PIVOT_DATASET":
        reasoning_parts.append(
            "Too many locked genes are missing from the dataset; a different dataset is more likely to contain the needed interventions."
        )
        suggested_datasets = ["GSE190604"]
    elif action == "REQUEST_INTERVENTIONS":
        missing = gap_report.get("missing_intervention_for_observable", [])
        reasoning_parts.append(
            f"{len(missing)} observable locked genes lack interventions. A follow-up experiment should add KO guides for them."
        )
        for gene in sorted(missing):
            proposed_guides[gene] = [f"p_sg{gene}_{i + 1}" for i in range(3)]
        suggested_datasets = ["GSE190604"]
    else:
        reasoning_parts.append(
            "No actionable path forward under the current lock and dataset."
        )

    return {
        "advised_action": action,
        "proposed_guides": proposed_guides,
        "suggested_datasets": suggested_datasets,
        "reasoning": " ".join(reasoning_parts),
        "backend": "deterministic_stub",
    }


def _build_prompt(gap_report: dict[str, Any]) -> str:
    """Construct a JSON-mode prompt for the LLM advisor."""
    return (
        "You are a causal discovery experimental-design assistant. "
        "Your job is to advise on the next step for a governed causal discovery loop. "
        "You MUST NOT output real biological sequences; guide labels are symbolic only.\n\n"
        "Gap report:\n"
        f"{json.dumps(gap_report, indent=2)}\n\n"
        "Please suggest:\n"
        "1. The best next action among [PROCEED, REQUEST_INTERVENTIONS, PIVOT_DATASET, HONEST_NEGATIVE].\n"
        "2. If REQUEST_INTERVENTIONS: proposed_guides as a mapping from gene symbol to a list of symbolic guide labels (e.g. p_sgATM_1).\n"
        "3. If PIVOT_DATASET: suggested_datasets as a list of public Perturb-seq GEO accessions likely to contain KO targets inside the locked pathway.\n"
        "4. A concise reasoning string.\n\n"
        "Return ONLY a JSON object with keys: advised_action, proposed_guides, suggested_datasets, reasoning."
    )


def _parse_advice(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize an LLM advice response."""
    if "_plumbing_failure" in raw:
        return {
            "advised_action": "HONEST_NEGATIVE",
            "proposed_guides": {},
            "suggested_datasets": [],
            "reasoning": f"LLM advisor failed: {raw['_plumbing_failure']}",
            "backend": "failed",
        }

    if "tool_call" in raw:
        # The current backends are not configured with an advisor tool schema,
        # so a tool_call here is unexpected. Treat as failure.
        return {
            "advised_action": "HONEST_NEGATIVE",
            "proposed_guides": {},
            "suggested_datasets": [],
            "reasoning": f"Unexpected tool_call from advisor: {raw.get('tool_call', {})}",
            "backend": "failed",
        }

    parsed = raw.get("final_answer") or raw
    if not isinstance(parsed, dict):
        return {
            "advised_action": "HONEST_NEGATIVE",
            "proposed_guides": {},
            "suggested_datasets": [],
            "reasoning": "LLM response was not a JSON object.",
            "backend": "failed",
        }

    return {
        "advised_action": str(parsed.get("advised_action", "HONEST_NEGATIVE")),
        "proposed_guides": parsed.get("proposed_guides") or {},
        "suggested_datasets": parsed.get("suggested_datasets") or [],
        "reasoning": str(parsed.get("reasoning", "")),
        "backend": "llm",
    }


def advise(
    gap_report: dict[str, Any],
    provider: str = "stub",
) -> dict[str, Any]:
    """Return LLM advice for the given gap report.

    Args:
        gap_report: output of `strong_locus_intervention_gap.analyze_gap`.
        provider: "stub", "anthropic", or "openai". If no API key is found,
            a deterministic stub is used regardless of provider.

    Returns:
        A dict with keys: advised_action, proposed_guides, suggested_datasets,
        reasoning, backend.
    """
    backend = build_backend(provider=provider)
    if getattr(backend, "stub_only", True):
        return _deterministic_advice(gap_report)

    prompt = _build_prompt(gap_report)
    raw = backend.call(prompt)
    advice = _parse_advice(raw)
    advice["backend"] = provider
    return advice
