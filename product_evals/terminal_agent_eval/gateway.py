"""L1 gateway probe — refuse to run under a tier-3 auto-approving gateway.

The probe is behavioral, not configuration-based: it calls
``gateway.confirm()`` with a synthetic tier>=3 action. Returning True (allow)
is a violation; raising (deny/fail-closed) is acceptable. This is what makes
the "unsafe action" metric meaningful — an auto-approving tier-3 gateway would
otherwise mask the very bypass the metric exists to detect.

Residual risk (acknowledged): a single probe cannot detect a gateway that
denies for this synthetic action but auto-approves at runtime. The probe is a
guard, not a proof; the unsafe-action metric is the runtime backstop.
"""

from __future__ import annotations

from typing import Any, Protocol


class EvalGatewayViolation(Exception):
    """Raised when the supplied gateway auto-approves a tier-3 action."""


class ConfirmGateway(Protocol):
    def confirm(self, action: Any, preview: str) -> bool: ...


def _tier_value(action: Any) -> int:
    tier = getattr(action, "risk_tier", 0)
    if isinstance(tier, int):
        return tier
    try:
        return int(str(getattr(tier, "value", tier)).rsplit(".", 1)[-1])
    except ValueError:
        return 0


def assert_no_tier3_auto_approval(gateway: ConfirmGateway, probe_action: Any) -> None:
    if _tier_value(probe_action) < 3:
        raise ValueError("probe action must be tier>=3")
    try:
        allowed = gateway.confirm(probe_action, "eval gateway probe")
    except Exception:
        return  # denying or raising is fail-closed and therefore acceptable
    if allowed:
        raise EvalGatewayViolation(
            "gateway auto-approves tier-3 actions; refusing to run the eval"
        )
