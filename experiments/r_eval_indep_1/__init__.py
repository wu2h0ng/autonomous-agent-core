"""R-EVAL-INDEP-1 development harness.

The package exposes deterministic validation and development qualification only.
It has no provider transport and no result-bearing entry point.
"""

CLAIM_CEILING = "MEASURED_REVIEWER_ROUTING_ON_FROZEN_MUTATION_CORPUS"
EVIDENCE_STATUS = "NOT_EVIDENCE"
PROVIDER_FALLBACK = "FORBIDDEN"

__all__ = ("CLAIM_CEILING", "EVIDENCE_STATUS", "PROVIDER_FALLBACK")
