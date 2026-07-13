"""Single derived identity source for this SPINE successor."""

from __future__ import annotations

from product_evals.common.spine_identity import SpineEvaluationIdentity

IDENTITY = SpineEvaluationIdentity.create(sequence=3, run_date="20260713")
