"""Freeze the downstream verdict grammar while keeping this lane raw-only."""

from __future__ import annotations

import json
from pathlib import Path


def test_candidate_verdict_grammar_is_closed_and_not_owned_by_raw_scorer() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    candidate = json.loads(
        (
            repo_root
            / "docs/pre_spec/R-STATE-CREDIT-1.STAGE-A.PREREG-CANDIDATE-2026-07-15.json"
        ).read_text(encoding="utf-8")
    )
    grammar = candidate["verdict_grammar"]

    assert grammar["allowed_verdicts"] == ["MET", "NOT_MET", "INVALID"]
    assert grammar["route_after_invalid"] == "NEW_LOCK_REQUIRED_NO_RESCUE"
    assert grammar["route_after_not_met"] == "PARK_TYPED_STATE_ROUTE"
    assert grammar["route_after_met"] == "STAGE_B_DESIGN_CANDIDATE_ONLY"

    scorer_source = (
        repo_root / "experiments/r_state_credit_1/real_scorer.py"
    ).read_text(encoding="utf-8")
    assert "allowed_verdicts" not in scorer_source
    assert "route_after_met" not in scorer_source
    assert "adjudicate" not in scorer_source.lower()
