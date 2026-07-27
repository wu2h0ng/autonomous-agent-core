from __future__ import annotations

from typing import Any

from agent_os_contracts import (
    BindingStatus,
    ProviderExecutionReceipt,
    ProviderRequest,
    WorkingSetRef,
    content_digest,
    provider_execution_receipt_digest,
)


def build_provider_execution_receipt(
    *,
    source_event_id: str,
    node_id: str,
    run: Any,
    provider_profile: Any,
    provider_profile_digest: str,
    request: ProviderRequest,
    response: Any,
    invocation_binding_digest: str,
    working_set_ref: WorkingSetRef,
    pre_correction_epochs: Any,
    post_correction_epochs: Any,
) -> ProviderExecutionReceipt:
    missing_fields = (
        ("model_revision_digest",)
        if provider_profile.model_revision_digest is None
        else ()
    ) + (
        ("working_set_digest",)
        if working_set_ref.status is BindingStatus.MISSING
        else ()
    )
    receipt_payload = {
        "schema_version": "1.0",
        "source_event_id": source_event_id,
        "node_id": node_id,
        "task_id": run.task_id,
        "run_id": run.run_id,
        "tenant_id": run.tenant_id,
        "workspace_id": run.workspace_id,
        "provider_profile_id": provider_profile.profile_id,
        "provider_profile_digest": provider_profile_digest,
        "provider_id": provider_profile.provider_id,
        "model_id": provider_profile.model_id,
        "model_revision_digest": provider_profile.model_revision_digest,
        "request_id": request.request_id,
        "request_digest": content_digest(request),
        "response_id": response.response_id,
        "response_digest": content_digest(response),
        "invocation_binding_digest": invocation_binding_digest,
        "working_set_ref": working_set_ref.model_dump(mode="json"),
        "pre_correction_epochs": pre_correction_epochs.model_dump(mode="json"),
        "post_correction_epochs": post_correction_epochs.model_dump(mode="json"),
        "correction_epoch": max(
            pre_correction_epochs.task_epoch,
            pre_correction_epochs.run_epoch,
            pre_correction_epochs.capability_epoch,
        ),
        "missing_fields": tuple(sorted(missing_fields)),
    }
    return ProviderExecutionReceipt(
        **receipt_payload,
        receipt_digest=provider_execution_receipt_digest(receipt_payload),
    )
