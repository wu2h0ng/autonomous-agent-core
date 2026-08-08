from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

from agent_os_contracts import (
    ProviderProfile,
    ProviderRequest,
    ProviderResponse,
    ProviderToolProposal,
)


class ExecutionProfileError(ValueError):
    """Fail-closed profile validation without execution authority."""


class ExecutionProfilePort(Protocol):
    @property
    def generator_id(self) -> str:
        raise NotImplementedError

    @property
    def generator_version(self) -> str:
        raise NotImplementedError

    def build_provider_request(
        self,
        *,
        task_id: str,
        run_id: str,
        provider_profile: ProviderProfile,
        provider_capability: str,
        context: Mapping[str, Any],
        now: datetime,
    ) -> ProviderRequest:
        raise NotImplementedError

    def bind_provider_response(
        self,
        response: ProviderResponse,
        *,
        context: Mapping[str, Any],
    ) -> tuple[ProviderToolProposal, ...]:
        raise NotImplementedError

    def tool_arguments(
        self,
        capability_id: str,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    def requires_provider_bound_action(self, capability_id: str) -> bool:
        raise NotImplementedError

    def verification_exit_code(
        self,
        context: Mapping[str, Any],
    ) -> int | None:
        raise NotImplementedError
