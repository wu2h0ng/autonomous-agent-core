from domain_packs.data_agent.evidence import derive_data_confidence


def test_unknown_freshness_and_unverified_template_are_flagged_and_capped() -> None:
    result = derive_data_confidence(row_count=10)

    assert result.score <= 0.55
    assert set(result.flags) >= {"freshness_unknown", "unverified_template"}


def test_verified_fresh_evidence_scores_above_unknown_evidence() -> None:
    verified = derive_data_confidence(
        row_count=10,
        source_age_seconds=60,
        freshness_tau_seconds=300,
        template_verified=True,
    )
    unknown = derive_data_confidence(row_count=10)

    assert verified.score > unknown.score
    assert "freshness_unknown" not in verified.flags
    assert "unverified_template" not in verified.flags


def test_tau_violation_is_visible_and_capped() -> None:
    result = derive_data_confidence(
        row_count=10,
        source_age_seconds=1_000,
        freshness_tau_seconds=100,
        template_verified=True,
    )

    assert result.score <= 0.50
    assert set(result.flags) >= {"stale", "tau_inconsistency"}


def test_zero_rows_has_explicit_floor_and_limitation_flag() -> None:
    result = derive_data_confidence(
        row_count=0,
        source_age_seconds=0,
        freshness_tau_seconds=100,
        template_verified=True,
    )

    assert result.score == 0.30
    assert "no_rows" in result.flags
