from __future__ import annotations

import hashlib
from typing import Protocol

from agent_os_contracts import (
    AuthorizedExternalStateCandidateRef,
    ExternalStateCandidateRef,
    ExternalStateAuthorizationReceipt,
    SelectionManifest,
    SelectionReceipt,
    TrustedWorkingSet,
    WorkingSetRequest,
    content_digest,
)

from .errors import SituationalTrustDenied


MAX_TRUSTED_WORKING_SET_CANDIDATES = 64
MAX_EXTERNAL_STATE_CANDIDATE_BYTES = 64 * 1024
MAX_TRUSTED_WORKING_SET_TOTAL_BYTES = 256 * 1024


WORKING_SET_SELECTION_POLICY_DIGEST = content_digest(
    {
        "policy": "working-set-selection/v1",
        "selection": "all-scope-and-correction-matched-candidates",
        "ordering": "candidate-id-ascending",
        "external_candidates_are_mandatory": False,
        "max_candidate_count": MAX_TRUSTED_WORKING_SET_CANDIDATES,
        "max_candidate_bytes": MAX_EXTERNAL_STATE_CANDIDATE_BYTES,
        "max_total_bytes": MAX_TRUSTED_WORKING_SET_TOTAL_BYTES,
    }
)


class ExternalStateSourceAdapter(Protocol):
    """Untrusted candidate source; it cannot supply mandatory anchors."""

    adapter_id: str
    version: int

    def load(
        self, request: WorkingSetRequest
    ) -> tuple[tuple[ExternalStateCandidateRef, bytes], ...]: ...


class ExternalStateAuthorizationRegistry(Protocol):
    """Trusted authority for source/resource read scope; never adapter-owned."""

    def resolve(
        self, source_adapter_id: str, source_adapter_version: int, resource_id: str
    ) -> ExternalStateAuthorizationReceipt | None: ...


class InMemoryExternalStateAuthorizationRegistry:
    __slots__ = ("_receipts",)

    def __init__(
        self, receipts: tuple[ExternalStateAuthorizationReceipt, ...] = ()
    ) -> None:
        indexed: dict[
            tuple[str, int, str], ExternalStateAuthorizationReceipt
        ] = {}
        for receipt in receipts:
            if type(receipt) is not ExternalStateAuthorizationReceipt:
                raise TypeError("external state authorization receipt is not closed")
            key = (
                receipt.source_adapter_id,
                receipt.source_adapter_version,
                receipt.resource_id,
            )
            if key in indexed:
                raise ValueError("external state resource authorization must be unique")
            indexed[key] = receipt
        self._receipts = indexed

    def resolve(
        self, source_adapter_id: str, source_adapter_version: int, resource_id: str
    ) -> ExternalStateAuthorizationReceipt | None:
        return self._receipts.get(
            (source_adapter_id, source_adapter_version, resource_id)
        )


class TrustedWorkingSetAssembler:
    """Deterministically select inferred candidates under internal anchors."""

    __slots__ = (
        "_adapters",
        "_authorization_registry",
        "_selection_policy_digest",
    )

    def __init__(
        self,
        *,
        adapters: tuple[ExternalStateSourceAdapter, ...] = (),
        authorization_registry: ExternalStateAuthorizationRegistry | None = None,
        selection_policy_digest: str,
    ) -> None:
        if len(selection_policy_digest) != 64:
            raise ValueError("selection policy digest must be sha256")
        indexed: dict[tuple[str, int], ExternalStateSourceAdapter] = {}
        for adapter in adapters:
            if not adapter.adapter_id.strip() or adapter.version < 1:
                raise ValueError("external state adapter identity is invalid")
            key = (adapter.adapter_id, adapter.version)
            if key in indexed:
                raise ValueError("external state adapter identities must be unique")
            indexed[key] = adapter
        self._adapters = tuple(indexed[key] for key in sorted(indexed))
        if authorization_registry is None:
            if self._adapters:
                raise ValueError(
                    "external state adapters require an authorization registry"
                )
            authorization_registry = InMemoryExternalStateAuthorizationRegistry()
        self._authorization_registry = authorization_registry
        self._selection_policy_digest = selection_policy_digest

    @property
    def selection_policy_digest(self) -> str:
        return self._selection_policy_digest

    def assemble(self, request: WorkingSetRequest) -> TrustedWorkingSet:
        if request.selection_policy_digest != self._selection_policy_digest:
            raise SituationalTrustDenied("working set selection policy mismatch")
        loaded: dict[
            str,
            tuple[
                AuthorizedExternalStateCandidateRef,
                bytes,
                ExternalStateAuthorizationReceipt,
            ],
        ] = {}
        loaded_count = 0
        loaded_bytes = 0
        for adapter in self._adapters:
            try:
                candidates = adapter.load(request)
            except Exception:
                raise SituationalTrustDenied(
                    "external state candidate source is unavailable"
                ) from None
            if type(candidates) is not tuple:
                raise SituationalTrustDenied("external state candidates are not closed")
            loaded_count += len(candidates)
            if loaded_count > MAX_TRUSTED_WORKING_SET_CANDIDATES:
                raise SituationalTrustDenied(
                    "external state candidate count exceeds frozen budget"
                )
            for item in candidates:
                if (
                    type(item) is not tuple
                    or len(item) != 2
                    or type(item[0]) is not ExternalStateCandidateRef
                    or type(item[1]) is not bytes
                ):
                    raise SituationalTrustDenied(
                        "external state candidate payload is not closed"
                    )
                candidate, payload = item
                if len(payload) > MAX_EXTERNAL_STATE_CANDIDATE_BYTES:
                    raise SituationalTrustDenied(
                        "external state candidate bytes exceed frozen budget"
                    )
                loaded_bytes += len(payload)
                if loaded_bytes > MAX_TRUSTED_WORKING_SET_TOTAL_BYTES:
                    raise SituationalTrustDenied(
                        "external state total bytes exceed frozen budget"
                    )
                if (
                    candidate.source_adapter_id != adapter.adapter_id
                    or candidate.source_adapter_version != adapter.version
                ):
                    raise SituationalTrustDenied(
                        "external state candidate adapter binding mismatch"
                    )
                if hashlib.sha256(payload).hexdigest() != candidate.content_digest:
                    raise SituationalTrustDenied(
                        "external state candidate content digest mismatch"
                    )
                try:
                    authorization = self._authorization_registry.resolve(
                        adapter.adapter_id,
                        adapter.version,
                        candidate.resource_id,
                    )
                except Exception:
                    raise SituationalTrustDenied(
                        "external state authorization registry is unavailable"
                    ) from None
                if authorization is None:
                    raise SituationalTrustDenied(
                        "external state resource authorization is unavailable"
                    )
                if (
                    authorization.source_adapter_id != adapter.adapter_id
                    or authorization.source_adapter_version != adapter.version
                    or authorization.resource_id != candidate.resource_id
                    or authorization.content_digest != candidate.content_digest
                ):
                    raise SituationalTrustDenied(
                        "external state resource authorization binding mismatch"
                    )
                authorized = AuthorizedExternalStateCandidateRef(
                    candidate_id=candidate.candidate_id,
                    source_kind=candidate.source_kind,
                    source_adapter_id=candidate.source_adapter_id,
                    source_adapter_version=candidate.source_adapter_version,
                    resource_id=candidate.resource_id,
                    principal_id=authorization.principal_id,
                    tenant_id=authorization.tenant_id,
                    workspace_id=authorization.workspace_id,
                    authorization_scope_digest=(
                        authorization.authorization_scope_digest
                    ),
                    authorization_receipt_digest=(
                        authorization.authorization_receipt_digest
                    ),
                    observed_correction_epoch=candidate.observed_correction_epoch,
                    media_type=candidate.media_type,
                    content_digest=candidate.content_digest,
                )
                loaded_item = (authorized, payload, authorization)
                existing = loaded.get(candidate.candidate_id)
                if existing is not None and existing != loaded_item:
                    raise SituationalTrustDenied(
                        "external state candidate identity conflicts"
                    )
                loaded[candidate.candidate_id] = loaded_item

        selected: list[tuple[AuthorizedExternalStateCandidateRef, bytes]] = []
        excluded: list[str] = []
        for candidate_id in sorted(loaded):
            candidate, payload, _authorization = loaded[candidate_id]
            if candidate.principal_id != request.principal_id:
                raise SituationalTrustDenied(
                    "external state resource authorization principal mismatch"
                )
            if (
                candidate.authorization_scope_digest
                != request.authorization_scope_digest
            ):
                raise SituationalTrustDenied(
                    "external state resource authorization scope mismatch"
                )
            if (
                candidate.tenant_id != request.tenant_id
                or candidate.workspace_id != request.workspace_id
            ):
                raise SituationalTrustDenied(
                    "external state resource authorization workspace mismatch"
                )
            if candidate.observed_correction_epoch != request.correction_epoch:
                excluded.append(f"{candidate_id}:CORRECTION_EPOCH_MISMATCH")
                continue
            selected.append((candidate, payload))

        manifest_payload = {
            "schema_version": "1.0",
            "adapter_bindings": tuple(
                f"{adapter.adapter_id}@{adapter.version}" for adapter in self._adapters
            ),
            "candidate_digests": tuple(
                content_digest(loaded[candidate_id][0])
                for candidate_id in sorted(loaded)
            ),
            "candidate_authorization_receipt_digests": tuple(
                loaded[candidate_id][2].authorization_receipt_digest
                for candidate_id in sorted(loaded)
            ),
            "selected_candidate_ids": tuple(item[0].candidate_id for item in selected),
            "selected_reasons": tuple(
                f"{item[0].candidate_id}:SCOPE_AND_CORRECTION_MATCH"
                for item in selected
            ),
            "excluded_reasons": tuple(excluded),
            "principal_id": request.principal_id,
            "tenant_id": request.tenant_id,
            "workspace_id": request.workspace_id,
            "authorization_scope_digest": request.authorization_scope_digest,
            "correction_epoch": request.correction_epoch,
            "selection_policy_digest": request.selection_policy_digest,
        }
        manifest_digest = content_digest(manifest_payload)
        manifest = SelectionManifest(
            manifest_id=f"selection-manifest:{manifest_digest}",
            manifest_digest=manifest_digest,
            **manifest_payload,
        )
        selected_payload_digest = content_digest(
            {
                "candidate_digests": tuple(
                    content_digest(candidate) for candidate, _ in selected
                ),
                "payload_digests": tuple(
                    hashlib.sha256(payload).hexdigest() for _, payload in selected
                ),
            }
        )
        receipt_payload = {
            "schema_version": "1.0",
            "working_set_request_digest": content_digest(request),
            "selection_manifest_digest": content_digest(manifest),
            "selected_payload_digest": selected_payload_digest,
            "selected_count": len(selected),
        }
        receipt_digest = content_digest(receipt_payload)
        receipt = SelectionReceipt(
            receipt_id=f"selection-receipt:{receipt_digest}",
            receipt_digest=receipt_digest,
            **receipt_payload,
        )
        return TrustedWorkingSet(
            request=request,
            manifest=manifest,
            receipt=receipt,
            selected_candidates=tuple(candidate for candidate, _ in selected),
            selected_candidate_bytes=tuple(payload for _, payload in selected),
        )


__all__ = [
    "ExternalStateSourceAdapter",
    "ExternalStateAuthorizationRegistry",
    "InMemoryExternalStateAuthorizationRegistry",
    "TrustedWorkingSetAssembler",
    "WORKING_SET_SELECTION_POLICY_DIGEST",
    "MAX_EXTERNAL_STATE_CANDIDATE_BYTES",
    "MAX_TRUSTED_WORKING_SET_CANDIDATES",
    "MAX_TRUSTED_WORKING_SET_TOTAL_BYTES",
]
