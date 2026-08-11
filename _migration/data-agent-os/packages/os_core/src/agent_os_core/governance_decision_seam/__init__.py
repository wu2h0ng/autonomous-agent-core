"""Governed-decision injection seam — OS-side client (RR-0032, R0–R3 wire).

The OS Trusted Loop calls an injected GovernanceDecisionClient at the governance gate; the client can
only TIGHTEN the decision (DENY -> block; ESCALATE/VERIFY_MORE -> force approval), never loosen. This
keeps the OS the subject loop while consuming the external governed brain's verdict.

#19 / RR-0032: the production client is a thin RPC stub to the remote autonomous-agent-core service; it
imports NO core code. LocalGovernanceDecisionClient is a NATIVE reference implementation of the contract
(the five invariants) for dev + acceptance tests — it does not import the core either; both sides
implement the shared versioned spec independently.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import replace
from typing import Any, Callable, Optional

from agent_os_contracts.governance_decision_seam import (
    GovernanceDecisionRequest,
    GovernanceDecisionResponse,
    VerifiedCandidate,
    SEAM_CONTRACT_VERSION,
    ALLOW,
    VERIFY_MORE,
    ESCALATE,
    DENY,
    request_to_json,
    response_from_json,
)

_RISK_ORDER = {f"R{i}": i for i in range(6)}
_ALLOWED_VERDICTS = frozenset((ALLOW, VERIFY_MORE, ESCALATE, DENY))


def _major(version: str) -> str:
    return version.split(".", 1)[0]


def _validate_remote_response(
    request: GovernanceDecisionRequest, response: GovernanceDecisionResponse
) -> GovernanceDecisionResponse:
    if response.task_id != request.task_id:
        raise ValueError("governance decision task mismatch")
    if _major(response.contract_version) != _major(SEAM_CONTRACT_VERSION):
        raise ValueError("incompatible governance decision contract")
    if response.verdict not in _ALLOWED_VERDICTS:
        raise ValueError("invalid governance decision verdict")
    if not response.audit_ref:
        raise ValueError("governance decision audit_ref required")
    return response


def verify_candidates(verifier: "CohortABVerifier", actions) -> tuple[VerifiedCandidate, ...]:
    """OS-side verification: run the cohort A/B verifier on each candidate action (RR-0032 "OS
    verifies"). Produces the VerifiedCandidate tuple the remote brain governs — the OS owns the data,
    so verification MUST happen here, not in the remote core."""
    out = []
    for action in actions:
        effective, confidence, evidence = verifier.verify(action)
        out.append(VerifiedCandidate(action, effective, confidence, evidence))
    return tuple(out)


class CohortABVerifier(ABC):
    """Interventional verifier: did a bounded cohort A/B test confirm the action moves the metric?

    Returns (is_effective, confidence, evidence_count). The OS owns the test; the seam owns the
    verdict. Async tests surface as is_effective=False with confidence 0 -> VERIFY_MORE upstream."""

    @abstractmethod
    def verify(self, action: str) -> tuple[bool, float, int]: ...


class MetricCohortABVerifier(CohortABVerifier):
    """REAL cohort A/B verifier over the OS query path (M4: no more stub verifiers).

    run_cohort_query(action) -> QueryResult whose rows carry {cohort: "A"|"B", metric: float}
    (the composition layer owns the SQL/provider; SQL Safety applies on that path — OS Core
    stays domain-independent, ports-and-adapters like the store ports). This class owns the
    REAL decision logic: standardized mean difference between cohorts; is_effective iff the
    absolute effect clears min_effect_size AND both cohorts have >= min_samples; confidence
    is a bounded monotone map of the effect; evidence_count = min(nA, nB) bound samples.
    Malformed rows, thin samples, or query errors FAIL CLOSED to (False, 0.0, 0) ->
    VERIFY_MORE/ESCALATE upstream, never a silent ALLOW."""

    def __init__(
        self,
        run_cohort_query: Callable[[str], Any],
        *,
        cohort_field: str = "cohort",
        metric_field: str = "metric",
        min_effect_size: float = 0.5,
        min_samples: int = 3,
    ) -> None:
        self.run_cohort_query = run_cohort_query
        self.cohort_field = cohort_field
        self.metric_field = metric_field
        self.min_effect_size = min_effect_size
        self.min_samples = min_samples

    def verify(self, action: str) -> tuple[bool, float, int]:
        try:
            result = self.run_cohort_query(action)
            a: list[float] = []
            b: list[float] = []
            for row in result.rows:
                cohort = row.get(self.cohort_field)
                metric = row.get(self.metric_field)
                if cohort not in ("A", "B") or not isinstance(metric, (int, float)):
                    return (False, 0.0, 0)  # malformed -> fail closed
                (a if cohort == "A" else b).append(float(metric))
            n_a, n_b = len(a), len(b)
            if n_a < self.min_samples or n_b < self.min_samples:
                return (False, 0.0, 0)  # thin -> fail closed
            mean_a = sum(a) / n_a
            mean_b = sum(b) / n_b
            var_a = sum((x - mean_a) ** 2 for x in a) / n_a
            var_b = sum((x - mean_b) ** 2 for x in b) / n_b
            pooled_sd = ((var_a + var_b) / 2) ** 0.5 or 1e-9
            effect = abs(mean_a - mean_b) / pooled_sd
            if effect < self.min_effect_size:
                return (False, 0.0, min(n_a, n_b))
            confidence = min(1.0, effect / (effect + 1.0) + 0.25)  # bounded monotone map
            return (True, round(confidence, 4), min(n_a, n_b))
        except Exception:  # noqa: BLE001 - verifier failures must degrade safely
            return (False, 0.0, 0)


class GovernanceDecisionClient(ABC):
    @abstractmethod
    def decide(self, request: GovernanceDecisionRequest) -> GovernanceDecisionResponse: ...


def _audit_ref(
    req: GovernanceDecisionRequest, verdict: str, chosen: Optional[str], reason: str
) -> str:
    blob = f"{req.task_id}|{verdict}|{chosen}|{reason}".encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


class LocalGovernanceDecisionClient(GovernanceDecisionClient):
    """Native reference implementation of the seam — the five invariants (RR-0032).

    1) act only on a VERIFIED candidate; 2) high-stakes (>= approval tier) never auto-allowed ->
    escalate; 3) C7: a paused shell_view can only DENY; 4) deterministic (no LLM in the control path);
    5) every response carries a resolving audit_ref."""

    def __init__(
        self,
        verifier: CohortABVerifier,
        *,
        approval_required_at_or_above: str = "R4",
        confidence_floor: float = 0.2,
        shell_view: Any | None = None,
    ) -> None:
        self.verifier = verifier
        self.approval_tier = _RISK_ORDER[approval_required_at_or_above]
        self.confidence_floor = confidence_floor
        self.shell_view = shell_view

    def _resp(self, req, verdict, chosen, conf, reason) -> GovernanceDecisionResponse:
        if self.shell_view is not None:
            self.shell_view.observe(
                {"event": "governed_decision", "task_id": req.task_id, "verdict": verdict}
            )
        return GovernanceDecisionResponse(
            req.task_id, verdict, chosen, conf, reason, _audit_ref(req, verdict, chosen, reason)
        )

    def decide(self, req: GovernanceDecisionRequest) -> GovernanceDecisionResponse:
        # invariant: contract version
        if req.contract_version.split(".")[0] != SEAM_CONTRACT_VERSION.split(".")[0]:
            return self._resp(
                req, DENY, None, 0.0, f"incompatible contract version {req.contract_version}"
            )
        # invariant 3: C7 supremacy — a paused operator shell can only tighten
        if self.shell_view is not None and getattr(self.shell_view, "paused", False):
            return self._resp(req, DENY, None, 0.0, "corrigibility shell paused")

        tier = _RISK_ORDER.get(req.risk_tier, 5)
        high_stakes = tier >= self.approval_tier

        for action in req.candidate_actions:
            effective, conf, _ev = self.verifier.verify(action)
            if not effective:
                continue  # invariant 1: never act on unverified
            # verified-effective candidate found
            if high_stakes:  # invariant 2: high-stakes never auto-allowed
                if not req.approved:
                    return self._resp(
                        req, ESCALATE, None, conf, "high-stakes action requires approval"
                    )
                if conf < self.confidence_floor:
                    return self._resp(
                        req, ESCALATE, None, conf, "high-stakes confidence below floor"
                    )
                return self._resp(
                    req, ALLOW, action, conf, "high-stakes: verified, confident, approved"
                )
            if conf < self.confidence_floor:
                return self._resp(req, VERIFY_MORE, None, conf, "confidence below floor")
            return self._resp(req, ALLOW, action, conf, "low-stakes: verified and confident")

        return self._resp(
            req, ESCALATE, None, 0.0, "no verified-effective candidate"
        )  # never silently act


class RemoteGovernanceDecisionClient(GovernanceDecisionClient):
    """RPC client to the remote autonomous-agent-core governed-decision service (#19: no core import).

    v1.1 "OS verifies -> core governs": the OS owns the data, so this client VERIFIES the candidates
    LOCALLY (via the injected verifier) and sends the VerifiedCandidate results to the remote brain,
    which only governs them. If a request already carries verified_candidates, it is sent as-is; if no
    verifier is set and none are supplied, the request goes unverified (the remote will escalate)."""

    def __init__(
        self,
        transport: Optional[Callable[[str], str]] = None,
        verifier: Optional["CohortABVerifier"] = None,
    ) -> None:
        self.transport = transport
        self.verifier = verifier

    def decide(self, request: GovernanceDecisionRequest) -> GovernanceDecisionResponse:
        if self.transport is None:
            raise NotImplementedError(
                "remote governed-decision transport not configured (no autonomous-agent-core service wired)"
            )
        # OS-side verification before the request crosses the wire (the remote brain cannot verify).
        if not request.verified_candidates and self.verifier is not None:
            request = replace(
                request,
                verified_candidates=verify_candidates(self.verifier, request.candidate_actions),
            )
        response = response_from_json(self.transport(request_to_json(request)))
        return _validate_remote_response(request, response)


def http_transport(url: str, timeout_seconds: float = 2.0) -> Callable[[str], str]:
    """A default HTTP POST transport for RemoteGovernanceDecisionClient (RR-0032 #1 step 4).

    POSTs the request JSON to the autonomous-agent-core seam service's /decide endpoint and returns the
    response JSON. A HARD wall-clock timeout (default 2s) means the decision path never blocks on a slow
    remote brain (ADR-0047: never block on the organ) — on timeout/connection failure it raises, which
    FallbackGovernanceDecisionClient turns into a safe local/escalate decision."""
    import urllib.request

    def _post(body: str) -> str:
        req = urllib.request.Request(
            url,
            data=body.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            return resp.read().decode("utf-8")

    return _post


class FallbackGovernanceDecisionClient(GovernanceDecisionClient):
    """Resilience wrapper (RR-0032 #1 step 5): try the primary (remote) client; on ANY failure
    (timeout, connection error, malformed response) fall back to a safe local client. The OS decision
    path must NEVER block or crash because the remote brain is slow/down — degrade, don't fail
    (ADR-0047). The fallback should itself be safe (e.g. LocalGovernanceDecisionClient, or one that
    escalates), so 'brain unreachable' resolves to governed-locally or escalate-to-human, never auto-allow."""

    def __init__(
        self, primary: GovernanceDecisionClient, fallback: GovernanceDecisionClient
    ) -> None:
        self.primary = primary
        self.fallback = fallback

    def decide(self, request: GovernanceDecisionRequest) -> GovernanceDecisionResponse:
        try:
            return self.primary.decide(request)
        except (
            Exception
        ):  # timeout / connection / parse — anything: degrade, never propagate into the loop
            return self.fallback.decide(request)
