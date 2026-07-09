"""P2-C (ADR-0017): EvidenceChain confidence is DERIVED, explained, and bypass-detected.

These tests pin the behavioral contract that replaces the old hard-coded constant
confidence (0.55 for zero rows else 0.82). Each test FAILS against the constant-
confidence builder for a behavioral reason (not a missing attribute): the constant
ignores freshness, row_count magnitude, template verification, and the stated recency
bound tau, so the relational/cap/flag assertions below cannot hold until the derivation
is implemented.

Discipline: OS Core domain-independent (a generic confidence rule; no Customer-0
logic); calibration stays ``rule_based`` (no learned model); every formal answer still
produces a COMPLETE EvidenceChain (asserted in the build helper).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))

from agent_os_contracts import (  # noqa: E402
    BusinessIntent,
    MetricContract,
    ProviderContract,
    ProviderKind,
    QualityContract,
    QueryPlan,
    QueryResult,
    SQLSafetyResult,
    SQLTemplate,
)
from agent_os_core.evidence_chain import EvidenceChainBuilder  # noqa: E402

SAFE_SQL = "SELECT order_date, SUM(paid_amount) AS val FROM sales.orders LIMIT 1000"

# The legacy constants this slice replaces. A build that still returns one of these for
# a fresh/full/verified answer means the derivation was bypassed.
LEGACY_CONSTANTS = (0.82, 0.55)


class ConfidenceDerivationTest(unittest.TestCase):
    """DataProduct -> EvidenceChain seam: confidence = f(freshness, row_count, template)."""

    def _verified_template(self) -> SQLTemplate:
        return SQLTemplate(
            template_id="gmv_daily",
            metric_name="gmv",
            sql=SAFE_SQL,
            required_parameters=("start_date", "end_date"),
            required_time_parameters=("start_date", "end_date"),
        )

    def _metric(self, *, tau: str | None) -> MetricContract:
        return MetricContract(
            metric_name="gmv",
            display_name="GMV",
            definition="Gross merchandise value",
            owner="revenue_ops",
            unit="CNY",
            allowed_schemas=("sales",),
            version="v1",
            verified_queries=(self._verified_template(),),
            quality_contract=(QualityContract(freshness=tau) if tau is not None else None),
        )

    def _provider(self) -> ProviderContract:
        return ProviderContract(
            provider_id="pg",
            kind=ProviderKind.WAREHOUSE,
            name="pg",
            owner="data",
            allowed_schemas=("sales",),
        )

    def _sql_safety(self) -> SQLSafetyResult:
        return SQLSafetyResult(
            allowed=True,
            reasons=(),
            checked_schemas=("sales",),
            checked_tables=("sales.orders",),
        )

    def _build(
        self,
        *,
        source_age_seconds: float | None,
        tau: str | None,
        row_count: int,
        template_verified: bool,
    ):
        metric = self._metric(tau=tau)
        template = self._verified_template()
        if not template_verified:
            # A template NOT among the contract's verified_queries: the query path is
            # unverified, so high confidence may not be claimed.
            template = SQLTemplate(
                template_id="ad_hoc_unlisted",
                metric_name="gmv",
                sql=SAFE_SQL,
                required_parameters=("start_date", "end_date"),
                required_time_parameters=("start_date", "end_date"),
            )
        query_plan = QueryPlan(
            metric_name="gmv",
            sql=SAFE_SQL,
            parameters={"start_date": "2026-01-01", "end_date": "2026-01-07"},
            source_template=template,
        )
        rows = tuple(
            {"gmv": float(i), "order_date": f"2026-01-0{i % 9 + 1}"} for i in range(row_count)
        )
        query_result = QueryResult(
            rows=rows, row_count=row_count, source_age_seconds=source_age_seconds
        )
        evidence = EvidenceChainBuilder().build(
            evidence_chain_id="evidence-1",
            intent=BusinessIntent(intent_id="i1", question="What is GMV?", metric_name="gmv"),
            metric_contract=metric,
            query_plan=query_plan,
            sql_safety=self._sql_safety(),
            query_result=query_result,
            trace_id="trace-1",
            provider_contract=self._provider(),
        )
        # Every formal answer still produces a COMPLETE, typed EvidenceChain (SQL Safety +
        # EvidenceChain are never bypassed by the confidence change).
        self.assertTrue(evidence.is_complete())
        self.assertTrue(evidence.is_typed_complete())
        # The scalar confidence and the typed score stay in lockstep.
        self.assertIsNotNone(evidence.confidence_score)
        self.assertAlmostEqual(evidence.confidence, evidence.confidence_score.score)
        self.assertEqual(evidence.confidence_score.calibration, "rule_based")
        return evidence

    # --- Test 1: stale (past tau) LOWERS confidence vs fresh, identical rows ------------
    def test_confidence_changes_with_inputs(self) -> None:
        fresh = self._build(
            source_age_seconds=3600.0, tau="24h", row_count=5, template_verified=True
        )
        stale = self._build(
            source_age_seconds=60 * 3600.0, tau="24h", row_count=5, template_verified=True
        )
        self.assertLess(
            stale.confidence,
            fresh.confidence,
            "stale source (past tau) must yield lower confidence than a fresh source "
            "with identical rows; a constant 0.82 makes them equal.",
        )

    # --- Test 2: small-N < full-N; row_count 0 -> floor (lowest) ------------------------
    def test_low_row_count_reduces_confidence(self) -> None:
        full = self._build(
            source_age_seconds=3600.0, tau="24h", row_count=20, template_verified=True
        )
        small = self._build(
            source_age_seconds=3600.0, tau="24h", row_count=1, template_verified=True
        )
        zero = self._build(
            source_age_seconds=3600.0, tau="24h", row_count=0, template_verified=True
        )
        self.assertLess(
            small.confidence, full.confidence, "small-N must reduce confidence vs full-N"
        )
        self.assertLess(zero.confidence, small.confidence, "zero rows must floor below small-N")
        # The existing "no rows" limitation is preserved.
        self.assertTrue(
            any("no" in lim.lower() and "row" in lim.lower() for lim in zero.limitations),
            f"zero-row answer must keep a 'no rows' limitation; got {zero.limitations}",
        )
        self.assertIn("no_rows", zero.confidence_score.inputs.flags)

    # --- Test 3: unverified template CAPS confidence ------------------------------------
    def test_unverified_template_caps_confidence(self) -> None:
        verified = self._build(
            source_age_seconds=3600.0, tau="24h", row_count=20, template_verified=True
        )
        unverified = self._build(
            source_age_seconds=3600.0, tau="24h", row_count=20, template_verified=False
        )
        self.assertLess(unverified.confidence, verified.confidence)
        self.assertLessEqual(
            unverified.confidence,
            0.6,
            "an unverified query path cannot claim high confidence",
        )
        self.assertFalse(unverified.confidence_score.inputs.template_verified)
        self.assertIn("unverified_template", unverified.confidence_score.inputs.flags)

    # --- Test 4: missing freshness CAPS + flags (never defaults high) -------------------
    def test_missing_freshness_caps_and_flags(self) -> None:
        unknown = self._build(
            source_age_seconds=None, tau="24h", row_count=20, template_verified=True
        )
        self.assertLessEqual(unknown.confidence, 0.6, "unknown freshness must cap confidence")
        for legacy in LEGACY_CONSTANTS:
            self.assertNotAlmostEqual(
                unknown.confidence,
                legacy,
                msg="unknown freshness must NEVER default to the old high constant",
            )
        self.assertFalse(unknown.confidence_score.inputs.freshness_known)
        self.assertIn("freshness_unknown", unknown.confidence_score.inputs.flags)
        self.assertTrue(
            any("fresh" in lim.lower() for lim in unknown.limitations),
            f"unknown freshness must be surfaced as a limitation; got {unknown.limitations}",
        )

    # --- Test 5: tau-consistency boundary at the DataProduct -> EvidenceChain seam ------
    def test_tau_consistency_boundary_at_dataproduct_seam(self) -> None:
        # actual freshness (30h) violates the stated recency bound tau (24h) beyond tolerance.
        inconsistent = self._build(
            source_age_seconds=30 * 3600.0, tau="24h", row_count=20, template_verified=True
        )
        self.assertIn("tau_inconsistency", inconsistent.confidence_score.inputs.flags)
        self.assertFalse(inconsistent.confidence_score.inputs.freshness_within_tau)
        self.assertLessEqual(
            inconsistent.confidence,
            0.5,
            "a tau violation must cap confidence at the seam",
        )
        self.assertTrue(
            any(
                "tau" in lim.lower() or "recency" in lim.lower() or "freshness" in lim.lower()
                for lim in inconsistent.limitations
            ),
            f"tau inconsistency must be recorded as a limitation; got {inconsistent.limitations}",
        )
        # A consistent (within-tau) answer records no inconsistency and scores higher.
        consistent = self._build(
            source_age_seconds=3600.0, tau="24h", row_count=20, template_verified=True
        )
        self.assertNotIn("tau_inconsistency", consistent.confidence_score.inputs.flags)
        self.assertTrue(consistent.confidence_score.inputs.freshness_within_tau)
        self.assertLess(inconsistent.confidence, consistent.confidence)

    # --- Inputs recorded + bypass-detecting (recomputable from recorded inputs) ---------
    def test_confidence_inputs_recorded_and_recomputable(self) -> None:
        evidence = self._build(
            source_age_seconds=3600.0, tau="24h", row_count=20, template_verified=True
        )
        inputs = evidence.confidence_score.inputs
        self.assertIsNotNone(inputs, "the derived score must record its contributing inputs")
        # A fresh/full/verified answer is genuinely high — NOT the legacy constant.
        for legacy in LEGACY_CONSTANTS:
            self.assertNotAlmostEqual(evidence.confidence, legacy)
        # Every per-input factor is bounded [0, 1].
        for factor in (inputs.freshness_factor, inputs.row_count_factor, inputs.template_factor):
            self.assertGreaterEqual(factor, 0.0)
            self.assertLessEqual(factor, 1.0)
        self.assertEqual(inputs.row_count, 20)
        self.assertTrue(inputs.template_verified)
        self.assertTrue(inputs.freshness_known)
        self.assertEqual(inputs.freshness_tau_seconds, 24 * 3600.0)
        self.assertEqual(inputs.source_age_seconds, 3600.0)
        # Bypass detector: the recorded raw inputs must RECOMPUTE the same score via the
        # public rule. A hard-coded constant divorced from inputs fails this.
        from agent_os_core.evidence_chain import derive_confidence

        recomputed = derive_confidence(
            source_age_seconds=inputs.source_age_seconds,
            tau_seconds=inputs.freshness_tau_seconds,
            row_count=inputs.row_count,
            template_verified=inputs.template_verified,
        )
        self.assertAlmostEqual(recomputed.score, evidence.confidence)


class FreshnessParsingTest(unittest.TestCase):
    """The stated recency bound tau is parsed from the QualityContract.freshness string."""

    def test_parses_common_duration_forms(self) -> None:
        from agent_os_core.evidence_chain import parse_freshness_to_seconds

        self.assertEqual(parse_freshness_to_seconds("24h"), 24 * 3600.0)
        self.assertEqual(parse_freshness_to_seconds("7d"), 7 * 86400.0)
        self.assertEqual(parse_freshness_to_seconds("30m"), 30 * 60.0)
        self.assertEqual(parse_freshness_to_seconds("3600s"), 3600.0)
        self.assertEqual(parse_freshness_to_seconds("daily"), 86400.0)
        self.assertEqual(parse_freshness_to_seconds("hourly"), 3600.0)

    def test_unknown_or_missing_returns_none(self) -> None:
        from agent_os_core.evidence_chain import parse_freshness_to_seconds

        self.assertIsNone(parse_freshness_to_seconds(None))
        self.assertIsNone(parse_freshness_to_seconds(""))
        self.assertIsNone(parse_freshness_to_seconds("whenever"))


if __name__ == "__main__":
    unittest.main()
