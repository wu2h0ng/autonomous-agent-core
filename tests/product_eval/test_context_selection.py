"""Controlled context-selection discriminator tests (WORKING-SET-COGNITIVE-INPUT-0).

These validate the *instrument*, not a product claim. The corpus is the frozen
spec; the arms are mechanical.
"""

from __future__ import annotations

from pathlib import Path

from product_evals.terminal_agent_eval.context_selection import (
    load_spec,
    record_run,
    run_arms,
    spec_digest,
)

SPEC_PATH = (
    Path(__file__).resolve().parents[2]
    / "product_evals"
    / "terminal_agent_eval"
    / "manifests"
    / "context_selection_spec.json"
)


def test_arms_are_deterministic() -> None:
    spec = load_spec(SPEC_PATH)
    assert run_arms(spec) == run_arms(spec)
    assert spec_digest(spec) == spec_digest(load_spec(SPEC_PATH))


def test_positive_stratum_ordering_sensitivity_with_negative_control() -> None:
    spec = load_spec(SPEC_PATH)
    result = run_arms(spec)
    positive = result["strata"]["positive"]
    negative = result["strata"]["negative"]

    # A0 (id-ascending) misses the low-salience critical evidence; oracle fixes it.
    assert positive["A0_scope_only"] == 1.0
    assert positive["A1_oracle_relevance"] == 0.0
    # A2 matched budget shows the positive miss is ordering-under-budget, not missing data.
    assert positive["A2_matched_full"] == 0.0

    # Negative control: no regression when id order already surfaces the critical item.
    assert negative["A0_scope_only"] == 0.0
    assert negative["A1_oracle_relevance"] == 0.0
    assert negative["A2_matched_full"] == 0.0

    assert result["passed"] is True


def test_gate_is_not_hardcoded_and_weakens_fail(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # An unattainable threshold must fail (catches a hardcoded passed=True).
    spec = load_spec(SPEC_PATH)
    spec["gate_min_positive_delta"] = 1.5
    assert run_arms(spec)["passed"] is False
    # A negative-regression must fail too.
    spec = load_spec(SPEC_PATH)
    spec["negative"] = {"tasks": 40, "critical_id_rank": 18}
    assert run_arms(spec)["passed"] is False


def test_record_run_marks_invalid_and_records_provenance(tmp_path) -> None:  # type: ignore[no-untyped-def]
    out = tmp_path / "result.json"
    result = record_run(SPEC_PATH, out)
    assert result["status"] == "INVALID"
    assert result["spec_digest"] == spec_digest(load_spec(SPEC_PATH))
    written = out.read_text("utf-8")
    assert '"status": "INVALID"' in written
    assert '"spec_digest"' in written
