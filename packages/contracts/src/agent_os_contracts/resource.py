from __future__ import annotations

from decimal import Decimal
from typing import Annotated, TypeAlias

from pydantic import Field

from .common import ContractModel


RiskTier: TypeAlias = Annotated[int, Field(ge=0, le=5)]


class ResourceBudget(ContractModel):
    max_cost_usd: Decimal = Field(ge=0)
    max_duration_seconds: int = Field(ge=1)
    max_provider_tokens: int = Field(ge=0)
    max_tool_calls: int = Field(ge=0)

    def fits_within(self, limit: ResourceBudget) -> bool:
        return (
            self.max_cost_usd <= limit.max_cost_usd
            and self.max_duration_seconds <= limit.max_duration_seconds
            and self.max_provider_tokens <= limit.max_provider_tokens
            and self.max_tool_calls <= limit.max_tool_calls
        )
