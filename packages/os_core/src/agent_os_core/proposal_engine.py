from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent_os_contracts import (
    BindingStatus,
    ProviderMessage,
    ProviderMessageRole,
    ProviderExecutionReceipt,
    ProviderRequest,
    ProviderFailure,
    ProviderToolProposal,
    WorkingSetRef,
    content_digest,
    provider_execution_receipt_digest,
)

from .errors import RunExecutionError
from .governance import CorrectionReadPort
from .provider import ProviderPort


class ProposalEngine:
    """Provider invocation: request construction, response validation, receipt creation."""

    def __init__(
        self,
        provider: ProviderPort,
        provider_profile: Any,
        correction: CorrectionReadPort,
        tasks: Any,
    ) -> None:
        self._provider = provider
        self._profile = provider_profile
        self._correction = correction
        self._tasks = tasks

    def call(
        self,
        run_id: str,
        task_id: str,
        capability: str,
        node_id: str,
        source_event_id: str,
        context: dict[str, Any],
    ) -> tuple[dict[str, Any], ProviderExecutionReceipt | None]:
        aggregate = self._tasks.get_task(task_id)
        snapshot = aggregate.configuration_snapshot
        run = aggregate.run
        if run is None:
            raise RunExecutionError(
                "provider invocation requires an active Run"
            )
        try:
            invocation_binding = self._provider.invocation_binding
        except RuntimeError as exc:
            if snapshot is not None:
                raise RunExecutionError(
                    "provider invocation binding is unavailable"
                ) from exc
            invocation_binding = None
        if snapshot is None:
            if invocation_binding is not None:
                raise RunExecutionError(
                    "bound provider invocation requires an exact configuration snapshot"
                )
            invocation_binding_digest = None
        else:
            if (
                run.run_id != run_id
                or run.configuration_snapshot_id != snapshot.snapshot_id
                or run.configuration_snapshot_digest
                != snapshot.snapshot_digest
                or run.provider_profile_id
                != snapshot.provider_profile.profile_id
            ):
                raise RunExecutionError(
                    "provider Run snapshot binding drift"
                )
            if (
                self._profile != snapshot.provider_profile
                or content_digest(self._profile)
                != snapshot.provider_profile_digest
            ):
                raise RunExecutionError(
                    "provider profile snapshot binding drift"
                )
            assert invocation_binding is not None
            if (
                invocation_binding.provider_profile != self._profile
                or invocation_binding.provider_id
                != self._profile.provider_id
                or invocation_binding.model_id != self._profile.model_id
            ):
                raise RunExecutionError(
                    "provider profile invocation binding mismatch"
                )
            invocation_binding_digest = invocation_binding.digest()
        target_path = str(
            context.get("target_path") or context.get("path") or ""
        )
        read_output = context.get("workspace.read") or context.get("read")
        if not target_path or not isinstance(read_output, dict):
            raise RunExecutionError(
                "provider requires a target path and completed workspace.read"
            )
        current_content = str(read_output.get("content", ""))
        goal = str(
            context.get("goal")
            or context.get("prompt")
            or "Produce the requested repository patch."
        )
        prompt = (
            f"Repository task: {goal}\n"
            f"Target path: {target_path}\n"
            f"Current SHA-256: {read_output.get('sha256', '')}\n"
            "Current file content follows:\n"
            f"---BEGIN FILE---\n{current_content[:20000]}\n---END FILE---\n"
            "Propose the complete replacement content by calling only the "
            "workspace.apply_patch tool. Include path and content. Do not call any "
            "other capability and do not claim that the patch was applied."
        )
        request = ProviderRequest(
            request_id=f"request-{uuid4()}",
            task_id=task_id,
            run_id=run_id,
            provider_profile_id=self._profile.profile_id,
            messages=(
                ProviderMessage(
                    role=ProviderMessageRole.USER, content=prompt
                ),
            ),
            allowed_capability_ids=("workspace.apply_patch",),
            timeout_seconds=self._profile.request_timeout_seconds,
            created_at=datetime.now(timezone.utc),
        )
        pre_correction_epochs = None
        if snapshot is not None:
            pre_correction_epochs = self._correction.snapshot(
                task_id, run_id, capability
            )
            if self._correction.halted(task_id, run_id, capability):
                raise RunExecutionError(
                    "provider invocation is correction halted"
                )
        response = self._provider.complete(request)
        if isinstance(response, ProviderFailure):
            raise RunExecutionError(
                f"provider {response.code.value}: {response.safe_message}"
            )
        if response.request_id != request.request_id:
            raise RunExecutionError(
                "provider response request binding mismatch"
            )
        if snapshot is not None and (
            response.invocation_binding_digest != invocation_binding_digest
        ):
            raise RunExecutionError(
                "provider response invocation binding mismatch"
            )
        proposals = list(response.tool_proposals)
        if proposals and (
            len(proposals) != 1
            or proposals[0].capability_id != "workspace.apply_patch"
        ):
            raise RunExecutionError(
                "provider returned an ambiguous or unauthorized tool proposal"
            )
        if not proposals:
            fallback = _parse_patch_json(response.text)
            if fallback is not None:
                proposals = [
                    ProviderToolProposal(
                        proposal_id=f"proposal-{uuid4()}",
                        capability_id="workspace.apply_patch",
                        arguments_json=json.dumps(fallback),
                    )
                ]
        if len(proposals) != 1:
            raise RunExecutionError(
                "provider must return exactly one workspace.apply_patch proposal"
            )
        raw_arguments = json.loads(proposals[0].arguments_json)
        if not isinstance(raw_arguments, dict):
            raise RunExecutionError(
                "provider patch arguments must be an object"
            )
        if set(raw_arguments) != {"path", "content"}:
            raise RunExecutionError(
                "provider patch arguments must contain only path and content"
            )
        proposed_path = str(raw_arguments.get("path", ""))
        proposed_content = raw_arguments.get("content")
        if proposed_path != target_path:
            raise RunExecutionError(
                "provider proposal path does not match the reviewed target"
            )
        if not isinstance(proposed_content, str):
            raise RunExecutionError(
                "provider proposal requires complete string content"
            )
        raw_arguments["expected_sha256"] = str(
            read_output.get("sha256", "")
        )
        bound_proposal = ProviderToolProposal(
            proposal_id=proposals[0].proposal_id,
            capability_id="workspace.apply_patch",
            arguments_json=json.dumps(raw_arguments),
        )
        provider_output = {
            "text": response.text,
            "tool_proposals": [
                bound_proposal.model_dump(mode="json")
            ],
            "usage": response.usage.model_dump(mode="json"),
            "finish_reason": response.finish_reason,
        }
        if snapshot is None:
            return provider_output, None
        assert invocation_binding_digest is not None
        assert pre_correction_epochs is not None
        working_set_ref = WorkingSetRef(
            status=BindingStatus.MISSING,
            gap_reason=(
                "developer provider path has no TrustedWorkingSet binding"
            ),
        )
        with self._correction.guard_unchanged(
            task_id, run_id, capability, pre_correction_epochs
        ) as unchanged:
            if not unchanged:
                raise RunExecutionError(
                    "provider correction epoch changed or became halted during invocation"
                )
            post_correction_epochs = self._correction.snapshot(
                task_id, run_id, capability
            )
            if post_correction_epochs != pre_correction_epochs:
                raise RunExecutionError(
                    "provider correction epoch changed during invocation"
                )
            receipt = build_provider_execution_receipt(
                source_event_id=source_event_id,
                node_id=node_id,
                run=run,
                provider_profile=self._profile,
                provider_profile_digest=snapshot.provider_profile_digest,
                request=request,
                response=response,
                invocation_binding_digest=invocation_binding_digest,
                working_set_ref=working_set_ref,
                pre_correction_epochs=pre_correction_epochs,
                post_correction_epochs=post_correction_epochs,
            )
            self._tasks.record_provider_response(
                task_id,
                node_id=node_id,
                provider_output=provider_output,
                receipt=receipt,
            )
        return provider_output, receipt


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


def _parse_patch_json(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None
