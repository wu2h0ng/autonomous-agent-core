from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import uuid4

from agent_os_contracts import (
    ProviderMessage,
    ProviderMessageRole,
    ProviderProfile,
    ProviderRequest,
    ProviderResponse,
    ProviderToolProposal,
)
from agent_os_core import ExecutionProfileError


class DeveloperRepositoryPatchProfile:
    generator_id = "developer-golden-path"
    generator_version = "1"

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
        target_path, read_output = _reviewed_target(context)
        current_content = str(read_output.get("content", ""))
        goal = str(
            context.get("goal")
            or context.get("prompt")
            or "Produce the requested repository patch."
        )
        acceptance_criteria = str(context.get("acceptance_criteria") or "")
        selfdev_envelope = context.get("selfdev_execution_envelope")
        selfdev_contract = ""
        if isinstance(selfdev_envelope, dict):
            prohibited = ", ".join(
                str(value)
                for value in selfdev_envelope.get("prohibited_effects", ())
            )
            selfdev_contract = (
                "SELFDEV persisted execution envelope:\n"
                f"Exact base HEAD: {selfdev_envelope.get('repository_head', '')}\n"
                f"Isolated branch: {selfdev_envelope.get('isolated_branch', '')}\n"
                f"Allowed write path: {selfdev_envelope.get('allowed_write_path', '')}\n"
                f"Verifier: {selfdev_envelope.get('verifier_command', '')}\n"
                f"Rollback: {selfdev_envelope.get('rollback_strategy', '')}\n"
                f"Prohibited effects: {prohibited}.\n"
            )
        prompt = (
            f"Repository task: {goal}\n"
            "Acceptance criteria:\n"
            f"{acceptance_criteria}\n"
            f"{selfdev_contract}"
            f"Target path: {target_path}\n"
            f"Current SHA-256: {read_output.get('sha256', '')}\n"
            "Current file content follows:\n"
            f"---BEGIN FILE---\n{current_content[:20000]}\n---END FILE---\n"
            "Propose the complete replacement content by calling only the "
            "workspace.apply_patch tool. Include path and content. Do not call any "
            "other capability and do not claim that the patch was applied."
        )
        return ProviderRequest(
            request_id=f"request-{uuid4()}",
            task_id=task_id,
            run_id=run_id,
            provider_profile_id=provider_profile.profile_id,
            messages=(ProviderMessage(role=ProviderMessageRole.USER, content=prompt),),
            allowed_capability_ids=("workspace.apply_patch",),
            timeout_seconds=provider_profile.request_timeout_seconds,
            created_at=now,
        )

    def bind_provider_response(
        self,
        response: ProviderResponse,
        *,
        context: Mapping[str, Any],
    ) -> tuple[ProviderToolProposal, ...]:
        target_path, read_output = _reviewed_target(context)
        proposals = list(response.tool_proposals)
        if proposals and (
            len(proposals) != 1 or proposals[0].capability_id != "workspace.apply_patch"
        ):
            raise ExecutionProfileError(
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
            raise ExecutionProfileError(
                "provider must return exactly one workspace.apply_patch proposal"
            )
        raw_arguments = json.loads(proposals[0].arguments_json)
        if not isinstance(raw_arguments, dict):
            raise ExecutionProfileError("provider patch arguments must be an object")
        if set(raw_arguments) != {"path", "content"}:
            raise ExecutionProfileError(
                "provider patch arguments must contain only path and content"
            )
        proposed_path = str(raw_arguments.get("path", ""))
        proposed_content = raw_arguments.get("content")
        if proposed_path != target_path:
            raise ExecutionProfileError(
                "provider proposal path does not match the reviewed target"
            )
        if not isinstance(proposed_content, str):
            raise ExecutionProfileError(
                "provider proposal requires complete string content"
            )
        raw_arguments["expected_sha256"] = str(read_output.get("sha256", ""))
        return (
            ProviderToolProposal(
                proposal_id=proposals[0].proposal_id,
                capability_id="workspace.apply_patch",
                arguments_json=json.dumps(raw_arguments),
            ),
        )

    def tool_arguments(
        self,
        capability_id: str,
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        if capability_id == "workspace.read":
            path = context.get("target_path") or context.get("path")
            if not isinstance(path, str) or not path:
                raise ExecutionProfileError("workspace.read requires target_path")
            return {"path": path}
        if capability_id == "workspace.run_tests":
            command = (
                context.get("test_command")
                or context.get("command")
                or "python -m pytest"
            )
            arguments: dict[str, Any] = {"command": str(command)}
            selfdev_envelope = context.get("selfdev_execution_envelope")
            if isinstance(selfdev_envelope, dict):
                target_paths = selfdev_envelope.get("allowed_write_paths")
                if isinstance(target_paths, tuple):
                    target_paths = list(target_paths)
                arguments["selfdev_verification_snapshot"] = {
                    "repository_head": selfdev_envelope.get("repository_head"),
                    "target_path": selfdev_envelope.get("allowed_write_path"),
                    "target_paths": target_paths,
                }
            return arguments
        explicit = context.get(capability_id)
        if isinstance(explicit, dict):
            return dict(explicit)
        raise ExecutionProfileError(f"no typed arguments available for {capability_id}")

    def requires_provider_bound_action(self, capability_id: str) -> bool:
        return capability_id == "workspace.apply_patch"

    def verification_exit_code(
        self,
        context: Mapping[str, Any],
    ) -> int | None:
        output = context.get("workspace.run_tests")
        if not isinstance(output, dict):
            return None
        value = output.get("exit_code")
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value


def _reviewed_target(context: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
    target_path = str(context.get("target_path") or context.get("path") or "")
    read_output = context.get("workspace.read") or context.get("read")
    if not target_path or not isinstance(read_output, dict):
        raise ExecutionProfileError(
            "provider requires a target path and completed workspace.read"
        )
    return target_path, read_output


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
