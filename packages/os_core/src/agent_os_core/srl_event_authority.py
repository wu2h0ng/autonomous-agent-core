from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from types import MappingProxyType
from typing import Protocol, TypeVar

from pydantic import BaseModel

from agent_os_contracts import (
    CredentialLeaseRef,
    CredentialRef,
    EventOriginRegistration,
    PayloadAdmissionAttestation,
    content_digest,
)


class EventOriginRegistryPort(Protocol):
    def resolve_event(self, event_id: str) -> EventOriginRegistration | None: ...


class CredentialLeaseRegistryPort(Protocol):
    def resolve(self, lease_id: str) -> CredentialLeaseRef | None: ...


class CredentialRefReader(Protocol):
    def resolve(self, credential_ref_id: str) -> CredentialRef | None: ...


class PayloadAdmissionRegistryPort(Protocol):
    def resolve_event(self, event_id: str) -> PayloadAdmissionAttestation | None: ...


_CanonicalValue = TypeVar("_CanonicalValue", bound=BaseModel)


def _canonical_mapping(
    values: Iterable[_CanonicalValue] | Mapping[str, _CanonicalValue],
    *,
    id_of: Callable[[_CanonicalValue], str],
) -> Mapping[str, _CanonicalValue]:
    registered: dict[str, _CanonicalValue] = {}
    entries = values.items() if isinstance(values, Mapping) else (
        (id_of(value), value) for value in values
    )
    for supplied_id, value in entries:
        canonical_id = id_of(value)
        if supplied_id != canonical_id:
            raise ValueError("mapping key does not match canonical id")
        existing = registered.get(canonical_id)
        if existing is not None:
            if content_digest(existing) != content_digest(value):
                raise ValueError(f"duplicate canonical id with different content: {canonical_id}")
            continue
        registered[canonical_id] = value
    return MappingProxyType(registered)


class CanonicalCredentialLeaseRegistry:
    def __init__(
        self,
        leases: Iterable[CredentialLeaseRef] | Mapping[str, CredentialLeaseRef],
    ) -> None:
        self._leases = _canonical_mapping(leases, id_of=lambda lease: lease.lease_id)

    def resolve(self, lease_id: str) -> CredentialLeaseRef | None:
        return self._leases.get(lease_id)


class CanonicalCredentialRefReader:
    def __init__(
        self,
        credentials: Iterable[CredentialRef] | Mapping[str, CredentialRef],
    ) -> None:
        self._credentials = _canonical_mapping(
            credentials,
            id_of=lambda credential: credential.credential_ref_id,
        )

    def resolve(self, credential_ref_id: str) -> CredentialRef | None:
        return self._credentials.get(credential_ref_id)


__all__ = [
    "CanonicalCredentialLeaseRegistry",
    "CanonicalCredentialRefReader",
    "CredentialLeaseRegistryPort",
    "CredentialRefReader",
    "EventOriginRegistryPort",
    "PayloadAdmissionRegistryPort",
]
