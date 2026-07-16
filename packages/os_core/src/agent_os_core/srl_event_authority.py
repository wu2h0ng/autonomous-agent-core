from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from types import MappingProxyType
from typing import Protocol, TypeVar, cast

from pydantic import BaseModel

from agent_os_contracts import (
    CredentialLeaseRef,
    CredentialRef,
    EventOriginRegistration,
    PayloadAdmissionAttestation,
    canonical_json,
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


def _canonical_snapshots(
    values: Iterable[_CanonicalValue] | Mapping[str, _CanonicalValue],
    *,
    id_of: Callable[[_CanonicalValue], str],
    model_type: type[_CanonicalValue],
) -> Mapping[str, bytes]:
    registered: dict[str, bytes] = {}
    entries: Iterable[tuple[str, _CanonicalValue]]
    if isinstance(values, Mapping):
        entries = cast(Mapping[str, _CanonicalValue], values).items()
    else:
        entries = ((id_of(value), value) for value in values)
    for supplied_id, value in entries:
        snapshot = canonical_json(value).encode("utf-8")
        existing = registered.get(supplied_id)
        if existing is not None:
            if existing != snapshot:
                raise ValueError(
                    f"duplicate canonical id with different content: {supplied_id}"
                )
            continue
        canonical_value = model_type.model_validate_json(snapshot, strict=True)
        canonical_snapshot = canonical_json(canonical_value).encode("utf-8")
        if snapshot != canonical_snapshot:
            raise ValueError("input is not a canonical contract snapshot")
        canonical_id = id_of(canonical_value)
        if supplied_id != canonical_id:
            raise ValueError("mapping key does not match canonical id")
        registered[canonical_id] = canonical_snapshot
    return MappingProxyType(registered)


class CanonicalCredentialLeaseRegistry:
    def __init__(
        self,
        leases: Iterable[CredentialLeaseRef] | Mapping[str, CredentialLeaseRef],
    ) -> None:
        self._leases = _canonical_snapshots(
            leases,
            id_of=lambda lease: lease.lease_id,
            model_type=CredentialLeaseRef,
        )

    def resolve(self, lease_id: str) -> CredentialLeaseRef | None:
        snapshot = self._leases.get(lease_id)
        if snapshot is None:
            return None
        return CredentialLeaseRef.model_validate_json(snapshot, strict=True)


class CanonicalCredentialRefReader:
    def __init__(
        self,
        credentials: Iterable[CredentialRef] | Mapping[str, CredentialRef],
    ) -> None:
        self._credentials = _canonical_snapshots(
            credentials,
            id_of=lambda credential: credential.credential_ref_id,
            model_type=CredentialRef,
        )

    def resolve(self, credential_ref_id: str) -> CredentialRef | None:
        snapshot = self._credentials.get(credential_ref_id)
        if snapshot is None:
            return None
        return CredentialRef.model_validate_json(snapshot, strict=True)


__all__ = [
    "CanonicalCredentialLeaseRegistry",
    "CanonicalCredentialRefReader",
    "CredentialLeaseRegistryPort",
    "CredentialRefReader",
    "EventOriginRegistryPort",
    "PayloadAdmissionRegistryPort",
]
