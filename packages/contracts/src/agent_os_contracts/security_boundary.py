from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, NonEmptyStr, UtcDateTime
from .evidence import Sha256Digest
from .provider import CredentialStatus


class LedgerAccessScope(ContractModel):
    """Authenticated ledger visibility boundary; never inferred from an object id."""

    principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr


class CredentialAuthorizationSnapshot(ContractModel):
    """Credential authorization metadata with resolver material deliberately absent."""

    credential_ref_id: NonEmptyStr
    credential_ref_digest: Sha256Digest
    owner_principal_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    provider_id: NonEmptyStr
    scopes: tuple[NonEmptyStr, ...] = Field(min_length=1)
    status: CredentialStatus
    created_at: UtcDateTime
    expires_at: UtcDateTime

    @field_validator("scopes", mode="after")
    @classmethod
    def _normalize_scopes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @model_validator(mode="after")
    def _validate_expiry(self) -> CredentialAuthorizationSnapshot:
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        return self


__all__ = ["CredentialAuthorizationSnapshot", "LedgerAccessScope"]
