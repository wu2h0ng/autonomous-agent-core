"""R-EVAL-INDEP-1 deterministic harness and native readiness contracts.

The package has no concrete provider client, provider call, freeze operation,
result-bearing runner, adjudicator, or promotion entry point.
"""

CLAIM_CEILING = "MEASURED_REVIEWER_ROUTING_ON_FROZEN_MUTATION_CORPUS"
EVIDENCE_STATUS = "NOT_EVIDENCE"
PROVIDER_FALLBACK = "FORBIDDEN"

__all__ = ("CLAIM_CEILING", "EVIDENCE_STATUS", "PROVIDER_FALLBACK")
