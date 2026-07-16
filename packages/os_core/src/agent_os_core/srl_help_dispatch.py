from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock

from agent_os_contracts import SrlHelpRequest, SrlHelpResponse, SrlHelpResponseKind

from .srl_ports import HelpDispatchPort, HelpDispatchResult


class InMemoryHelpDispatch(HelpDispatchPort):
    """In-memory help request lifecycle stub."""

    durable = False

    def __init__(self, *, now: datetime | None = None) -> None:
        self._lock = RLock()
        self._requests: dict[str, SrlHelpRequest] = {}
        self._resolutions: dict[str, SrlHelpResponse] = {}
        self._clock = now or datetime.now(timezone.utc)

    def emit(self, help_request: SrlHelpRequest) -> HelpDispatchResult:
        with self._lock:
            self._requests[help_request.help_request_id] = help_request
            return HelpDispatchResult(
                emitted=True,
                resolved=False,
                help_request_id=help_request.help_request_id,
                burden_receipt=None,
            )

    def resolve(self, response: SrlHelpResponse) -> HelpDispatchResult:
        with self._lock:
            request = self._requests.get(response.help_request_id)
            if request is None:
                return HelpDispatchResult(
                    emitted=False,
                    resolved=False,
                    help_request_id=response.help_request_id,
                    rejection_reason="help request not found",
                )
            if response.help_request_id in self._resolutions:
                return HelpDispatchResult(
                    emitted=False,
                    resolved=False,
                    help_request_id=response.help_request_id,
                    rejection_reason="help request already resolved",
                )
            if response.response_kind not in {
                SrlHelpResponseKind.OPERATOR_DECISION,
                SrlHelpResponseKind.CAPABILITY_GRANT,
                SrlHelpResponseKind.REVOCATION_REQUEST,
                SrlHelpResponseKind.CANCELLATION,
            }:
                return HelpDispatchResult(
                    emitted=False,
                    resolved=False,
                    help_request_id=response.help_request_id,
                    rejection_reason="response is not a typed authority record",
                )
            if self._clock > request.expires_at:
                # After expiry only responses that stop or suspend work are permitted;
                # authority-carrying responses would continue non-continuable work.
                if response.response_kind not in {
                    SrlHelpResponseKind.CANCELLATION,
                    SrlHelpResponseKind.REVOCATION_REQUEST,
                }:
                    return HelpDispatchResult(
                        emitted=False,
                        resolved=False,
                        help_request_id=response.help_request_id,
                        rejection_reason="only continuable_work permits resolution after expiry",
                    )
            self._resolutions[response.help_request_id] = response
            return HelpDispatchResult(
                emitted=False,
                resolved=True,
                help_request_id=response.help_request_id,
            )
