from __future__ import annotations

from dataclasses import dataclass

from agent_os_contracts import (
    BusinessIntent,
    Claim,
    ConfidenceInputs,
    ConfidenceScore,
    EvidenceChain,
    EvalBinding,
    Limitation,
    MetricContract,
    MetricContractRef,
    ProviderContract,
    ProviderContractRef,
    QueryPlan,
    QueryResult,
    QueryResultSummary,
    SQLSafetyResult,
)

# ============================================================================================
# Confidence derivation rule (P2-C, ADR-0017)
# --------------------------------------------------------------------------------------------
# EvidenceChain confidence is DERIVED from observable inputs, not asserted as a constant. The
# rule is transparent and bounded:
#
#     confidence = clamp( BASE * freshness_factor * row_count_factor * template_factor )
#
# then explicit CAPS (min) apply for each unmet safety condition (unknown freshness, tau
# violation, unverified template) and a FLOOR applies to a zero-row answer. Every factor is
# bounded [0, 1] and every cap/floor names a flag recorded on ConfidenceInputs, so the scalar
# is explainable and recomputable from its recorded inputs. Calibration stays ``rule_based``:
# this is a deterministic rule, NOT a learned/statistical model (that is a separately-gated
# future capability). The rule is domain-independent — it reads only generic freshness / row /
# template-verification signals, never Customer-0 semantics.
# ============================================================================================

_BASE_CONFIDENCE = 0.95
_MIN_CONFIDENCE = 0.05
_MAX_CONFIDENCE = 0.97

# Caps: an unmet condition means confidence may not EXCEED the cap.
_FRESHNESS_UNKNOWN_CAP = 0.60
_UNVERIFIED_TEMPLATE_CAP = 0.55
_TAU_INCONSISTENT_CAP = 0.50

# Floor: a zero-row answer has no data to be confident about, but the refusal is still a
# governed result, so it floors (not zero).
_ROW_ZERO_FLOOR = 0.30

# Per-input factor shaping.
_FRESHNESS_UNKNOWN_FACTOR = 0.60
_UNVERIFIED_TEMPLATE_FACTOR = 0.60
_STALE_FRESHNESS_FLOOR = 0.30  # a KNOWN-but-stale freshness factor never decays below this
_TAU_TOLERANCE = 0.10  # actual age may exceed tau by 10% before it is declared inconsistent
_ROW_COUNT_FULL = 10  # row_count >= this earns the full row factor
_ROW_COUNT_FLOOR = 0.60  # smallest row factor for a non-empty (>=1 row) result
_BORDERLINE_FRESHNESS_FACTOR = 0.85  # within tolerance band but past nominal tau

# Claim.confidence label thresholds (score -> high / medium / low).
_CLAIM_HIGH = 0.70
_CLAIM_MEDIUM = 0.40

_DURATION_UNIT_SECONDS = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0, "w": 604800.0}
_DURATION_CADENCE_WORDS = {
    "hourly": 3600.0,
    "daily": 86400.0,
    "weekly": 604800.0,
    "monthly": 2592000.0,
}


def parse_freshness_to_seconds(text: str | None) -> float | None:
    """Parse a stated recency bound (tau) string into seconds — domain-independent.

    Accepts ``<number><unit>`` where unit is one of ``s/m/h/d/w`` (e.g. ``"24h"``,
    ``"7d"``, ``"30m"``), a bare number (interpreted as seconds), or a common cadence
    word (``"hourly"``, ``"daily"``, ``"weekly"``, ``"monthly"``). Returns ``None`` when
    the text is missing/empty or not a recognized duration; the caller then treats tau as
    unspecified rather than guessing a bound.
    """
    if not text:
        return None
    token = text.strip().lower()
    if not token:
        return None
    if token in _DURATION_CADENCE_WORDS:
        return _DURATION_CADENCE_WORDS[token]
    try:
        value = float(token)
    except ValueError:
        value = None
    if value is not None:
        return value if value >= 0 else None
    unit = token[-1]
    if unit in _DURATION_UNIT_SECONDS:
        try:
            magnitude = float(token[:-1])
        except ValueError:
            return None
        if magnitude < 0:
            return None
        return magnitude * _DURATION_UNIT_SECONDS[unit]
    return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class ConfidenceDerivation:
    """Result of the transparent confidence rule: the score plus its explanation.

    ``inputs`` carries the raw inputs and bounded per-input factors (so the score is
    recomputable); ``limitations`` are the human-readable limitations implied by the flags
    (e.g. the "no rows", "freshness unknown", or "tau inconsistency" notes).
    """

    score: float
    inputs: ConfidenceInputs
    limitations: tuple[str, ...]

    @property
    def claim_confidence_label(self) -> str:
        if self.score >= _CLAIM_HIGH:
            return "high"
        if self.score >= _CLAIM_MEDIUM:
            return "medium"
        return "low"


def derive_confidence(
    *,
    source_age_seconds: float | None,
    tau_seconds: float | None,
    row_count: int,
    template_verified: bool,
) -> ConfidenceDerivation:
    """Derive an explainable, bounded EvidenceChain confidence from observable inputs.

    ``confidence = f(source_freshness, row_count, template_verified)`` where each input is
    an explicit bounded factor and each unmet safety condition applies a cap (never a
    silent high default). The seam contract: an actual ``source_age_seconds`` that violates
    the stated recency bound ``tau_seconds`` beyond ``_TAU_TOLERANCE`` records a
    ``tau_inconsistency`` and caps the score (flag-and-cap advisory evidence, per ADR-0017).
    """
    flags: list[str] = []
    limitations: list[str] = []
    caps: list[float] = []

    freshness_known = source_age_seconds is not None
    freshness_within_tau = False

    # --- freshness factor (actual source recency vs the claimed bound tau) --------------
    if not freshness_known:
        # Missing freshness must CAP and FLAG — never default to a high confidence.
        freshness_factor = _FRESHNESS_UNKNOWN_FACTOR
        flags.append("freshness_unknown")
        caps.append(_FRESHNESS_UNKNOWN_CAP)
        limitations.append(
            "Source freshness is unknown; confidence is capped and the answer is not "
            "asserted as fresh."
        )
    elif tau_seconds is None:
        # Data age is known but the contract states no recency bound: there is no claim to
        # violate, so the freshness factor is full; record that tau was unspecified.
        freshness_factor = 1.0
        freshness_within_tau = True
        flags.append("freshness_tau_unspecified")
    elif source_age_seconds <= tau_seconds:
        freshness_factor = 1.0
        freshness_within_tau = True
    elif source_age_seconds <= tau_seconds * (1.0 + _TAU_TOLERANCE):
        # Within the tolerance band: still consistent with the stated tau, but past the
        # nominal freshness, so the factor eases off.
        freshness_factor = _BORDERLINE_FRESHNESS_FACTOR
        freshness_within_tau = True
    else:
        # tau-consistency boundary VIOLATED at the DataProduct -> EvidenceChain seam.
        freshness_factor = _clamp(tau_seconds / source_age_seconds, _STALE_FRESHNESS_FLOOR, 1.0)
        freshness_within_tau = False
        flags.append("stale")
        flags.append("tau_inconsistency")
        caps.append(_TAU_INCONSISTENT_CAP)
        limitations.append(
            "Source freshness exceeds the stated recency bound (tau); a tau_inconsistency "
            "is recorded at the DataProduct seam and confidence is capped."
        )

    # --- template-verification factor ---------------------------------------------------
    if template_verified:
        template_factor = 1.0
    else:
        template_factor = _UNVERIFIED_TEMPLATE_FACTOR
        flags.append("unverified_template")
        caps.append(_UNVERIFIED_TEMPLATE_CAP)
        limitations.append(
            "Query used an unverified SQL template; confidence is capped for the "
            "unverified query path."
        )

    # --- row-count factor ---------------------------------------------------------------
    if row_count <= 0:
        row_count_factor = 0.0
        flags.append("no_rows")
        limitations.append("No data rows were available for the requested scope.")
    else:
        row_count_factor = _ROW_COUNT_FLOOR + (1.0 - _ROW_COUNT_FLOOR) * (
            min(row_count, _ROW_COUNT_FULL) / _ROW_COUNT_FULL
        )
        if row_count < _ROW_COUNT_FULL:
            flags.append("low_row_count")

    score = _BASE_CONFIDENCE * freshness_factor * row_count_factor * template_factor
    for cap in caps:
        score = min(score, cap)
    if row_count <= 0:
        score = max(score, _ROW_ZERO_FLOOR)
    else:
        score = max(score, _MIN_CONFIDENCE)
    score = round(_clamp(score, _MIN_CONFIDENCE, _MAX_CONFIDENCE), 6)

    if not limitations:
        limitations.append("Result depends on the approved SQL template and source freshness.")

    inputs = ConfidenceInputs(
        row_count=row_count,
        template_verified=template_verified,
        freshness_known=freshness_known,
        freshness_within_tau=freshness_within_tau,
        source_age_seconds=source_age_seconds,
        freshness_tau_seconds=tau_seconds,
        freshness_factor=round(freshness_factor, 6),
        row_count_factor=round(row_count_factor, 6),
        template_factor=round(template_factor, 6),
        flags=tuple(flags),
    )
    return ConfidenceDerivation(score=score, inputs=inputs, limitations=tuple(limitations))


def _template_verified(metric_contract: MetricContract, query_plan: QueryPlan) -> bool:
    """True when the executed template is one of the contract's verified_queries.

    The QueryPlanner selects ``source_template`` FROM ``verified_queries``, so the normal
    governed path is verified; a plan whose template is absent (or None) is an unverified
    query path and cannot claim high confidence.
    """
    template = query_plan.source_template
    if template is None:
        return False
    return template.template_id in {t.template_id for t in metric_contract.verified_queries}


def _stated_tau_seconds(metric_contract: MetricContract) -> float | None:
    quality_contract = metric_contract.quality_contract
    if quality_contract is None:
        return None
    return parse_freshness_to_seconds(quality_contract.freshness)


class EvidenceChainBuilder:
    def __init__(self, *, semantic_registry=None) -> None:
        self._registry = semantic_registry

    def build(
        self,
        *,
        evidence_chain_id: str,
        intent: BusinessIntent,
        metric_contract: MetricContract,
        query_plan: QueryPlan,
        sql_safety: SQLSafetyResult,
        query_result: QueryResult,
        trace_id: str,
        provider_contract: ProviderContract | None = None,
    ) -> EvidenceChain:
        # Confidence is DERIVED (P2-C, ADR-0017) from observable inputs at the
        # DataProduct -> EvidenceChain seam: actual source freshness vs the contract's
        # stated recency bound (tau), row_count, and whether the executed template is
        # verified. The contributing inputs are recorded on ConfidenceScore.inputs so the
        # number is explainable, not asserted; calibration stays rule_based.
        derivation = derive_confidence(
            source_age_seconds=query_result.source_age_seconds,
            tau_seconds=_stated_tau_seconds(metric_contract),
            row_count=query_result.row_count,
            template_verified=_template_verified(metric_contract, query_plan),
        )
        confidence = derivation.score
        limitations = derivation.limitations
        if query_result.row_count == 0:
            conclusion = f"No rows returned for {metric_contract.display_name}."
        else:
            conclusion = (
                f"{metric_contract.display_name} returned {query_result.row_count} row(s) "
                f"under the approved metric contract."
            )

        column_names = tuple(query_result.rows[0].keys()) if query_result.rows else ()
        query_result_summary = QueryResultSummary(
            row_count=query_result.row_count,
            column_names=column_names,
            sample_fingerprint="",
        )

        metric_contract_refs = (
            MetricContractRef(
                metric_name=metric_contract.metric_name,
                contract_version=metric_contract.version,
            ),
        )
        provider_contract_refs = (
            (ProviderContractRef(provider_id=provider_contract.provider_id),)
            if provider_contract is not None
            else ()
        )

        claims = (
            Claim(
                statement=conclusion,
                evidence_refs=("query_result", "sql_safety", "query_plan"),
                confidence=derivation.claim_confidence_label,
                scope="in-scope",
            ),
        )
        limitation_objects = tuple(Limitation(description=limitation) for limitation in limitations)
        confidence_score = ConfidenceScore(
            score=confidence, calibration="rule_based", inputs=derivation.inputs
        )
        eval_bindings = (EvalBinding(eval_case_id=trace_id, dimension="evidence"),)

        semantic_object_refs: tuple = ()
        semantic_lineage: tuple = ()
        if self._registry is not None:
            semantic_object_refs, semantic_lineage = self._semantic_lineage(
                metric_contract, provider_contract
            )

        evidence = EvidenceChain(
            semantic_object_refs=semantic_object_refs,
            semantic_lineage=semantic_lineage,
            evidence_chain_id=evidence_chain_id,
            intent=intent,
            metric_contract=metric_contract,
            query_plan=query_plan,
            sql_safety=sql_safety,
            query_result=query_result,
            conclusion=conclusion,
            confidence=confidence,
            limitations=limitations,
            trace_id=trace_id,
            metric_contract_refs=metric_contract_refs,
            provider_contract_refs=provider_contract_refs,
            query_result_summary=query_result_summary,
            claims=claims,
            limitation_objects=limitation_objects,
            confidence_score=confidence_score,
            eval_bindings=eval_bindings,
        )

        if not evidence.is_complete():
            raise ValueError("EvidenceChain is incomplete")

        return evidence

    def _semantic_lineage(self, metric_contract, provider_contract):
        """Collect semantic objects + link paths related to this metric.

        Returns (semantic_object_refs, semantic_lineage) tuples. Objects whose
        related_metrics include the metric are collected; all links between
        collected objects form the lineage path.
        """
        from agent_os_contracts import EvidenceObjectLinkRef, EvidenceSemanticObjectRef

        graph = getattr(self._registry, "graph", None)
        if graph is None:
            return (), ()
        related_ids = []
        for obj in graph.objects():
            if metric_contract.metric_name in obj.related_metrics:
                related_ids.append(obj.object_id)
        obj_refs = tuple(
            EvidenceSemanticObjectRef(
                object_id=graph.resolve_object(oid).object_id,
                object_type=graph.resolve_object(oid).object_type,
                name=graph.resolve_object(oid).name,
            )
            for oid in related_ids
        )
        link_refs = []
        for link in graph.links():
            if link.source_object_id in related_ids and link.target_object_id in related_ids:
                link_refs.append(
                    EvidenceObjectLinkRef(
                        link_id=link.link_id,
                        link_type_id=link.link_type_id,
                        source_object_id=link.source_object_id,
                        target_object_id=link.target_object_id,
                    )
                )
        return obj_refs, tuple(link_refs)
