"""Typed capability runtime for the Mandate coding terminal.

Invokes WorkspaceSandbox through ActionContract + ActionPermit without
standing up a full Task/Run coordinator. C7 CorrectionAuthority remains
in the path. apply_patch approval is enforced by the REPL caller.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from agent_os_contracts import (
    ActionContract,
    ActionPermit,
    ProviderToolProposal,
    ResourceBudget,
)

from .capability import CapabilityBroker, CapabilityDenied, WorkspaceSandbox
from .governance import CorrectionAuthority

TERMINAL_CAPABILITIES: tuple[str, ...] = (
    "workspace.read",
    "workspace.search",
    "workspace.apply_patch",
    "workspace.run_tests",
    "workspace.shell",
)

WRITE_CAPABILITIES = frozenset({"workspace.apply_patch", "workspace.shell"})


@dataclass(frozen=True)
class ToolInvocationResult:
    capability_id: str
    ok: bool
    output: dict[str, object]
    error: str | None = None
    action_digest: str | None = None


class MandateToolRuntime:
    def __init__(
        self,
        *,
        repo_root: Path,
        principal_id: str,
        tenant_id: str,
        workspace_id: str,
        correction: CorrectionAuthority | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.principal_id = principal_id
        self.tenant_id = tenant_id
        self.workspace_id = workspace_id
        self.correction = correction or CorrectionAuthority()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.sandbox = WorkspaceSandbox(self.repo_root)
        self.broker = CapabilityBroker(self.sandbox, self.correction)
        self.task_id = "task:mandate-terminal"
        self.run_id = f"run:mandate-terminal:{uuid4()}"

    def allowed_capability_ids(self) -> tuple[str, ...]:
        return TERMINAL_CAPABILITIES

    def invoke_proposal(
        self, proposal: ProviderToolProposal, *, approved: bool
    ) -> ToolInvocationResult:
        capability_id = proposal.capability_id
        if capability_id not in TERMINAL_CAPABILITIES:
            return ToolInvocationResult(
                capability_id=capability_id,
                ok=False,
                output={},
                error=f"capability not allowed in terminal: {capability_id}",
            )
        if capability_id in WRITE_CAPABILITIES and not approved:
            return ToolInvocationResult(
                capability_id=capability_id,
                ok=False,
                output={},
                error="write capability requires interactive approval",
            )
        try:
            args = json.loads(proposal.arguments_json)
        except json.JSONDecodeError as exc:
            return ToolInvocationResult(
                capability_id=capability_id,
                ok=False,
                output={},
                error=f"invalid arguments_json: {exc}",
            )
        if not isinstance(args, dict):
            return ToolInvocationResult(
                capability_id=capability_id,
                ok=False,
                output={},
                error="arguments must be a JSON object",
            )
        now = self._clock()
        action = self._build_action(capability_id, args, now=now)
        permit = ActionPermit(
            permit_id=f"permit:{action.action_id}",
            action_id=action.action_id,
            action_digest=action.action_digest(),
            principal_id=action.principal_id,
            tenant_id=action.tenant_id,
            workspace_id=action.workspace_id,
            policy_decision_id=f"decision:mandate-terminal:{uuid4()}",
            grant_id=f"grant:mandate-terminal:{capability_id}",
            correction_epochs=action.observed_correction_epochs,
            lease_fence=0,
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
        )
        try:
            result = self.broker.invoke(action, permit)
        except (CapabilityDenied, PermissionError, FileNotFoundError, OSError) as exc:
            return ToolInvocationResult(
                capability_id=capability_id,
                ok=False,
                output={},
                error=str(exc),
                action_digest=action.action_digest(),
            )
        ok = result.receipt.status.value == "SUCCEEDED"
        return ToolInvocationResult(
            capability_id=capability_id,
            ok=ok,
            output=dict(result.output),
            error=None if ok else result.receipt.error_code,
            action_digest=action.action_digest(),
        )

    def summarize_proposal(self, proposal: ProviderToolProposal) -> str:
        try:
            args: dict[str, Any] = json.loads(proposal.arguments_json)
        except json.JSONDecodeError:
            args = {}
        path = args.get("path", "?")
        if proposal.capability_id == "workspace.apply_patch":
            content = str(args.get("content", ""))
            preview = content if len(content) <= 240 else content[:240] + "…"
            digest = proposal.proposal_id
            return (
                f"apply_patch path={path} bytes={len(content.encode('utf-8'))} "
                f"proposal={digest}\n--- preview ---\n{preview}"
            )
        if proposal.capability_id == "workspace.read":
            return f"read path={path}"
        if proposal.capability_id == "workspace.run_tests":
            return f"run_tests command={args.get('command', 'python -m pytest')}"
        if proposal.capability_id == "workspace.search":
            return (
                f"search pattern={args.get('pattern')} glob={args.get('glob', '**/*')} "
                f"path={args.get('path', '.')}"
            )
        if proposal.capability_id == "workspace.shell":
            return f"shell argv={args.get('argv')}"
        return f"{proposal.capability_id} args={args}"

    def _build_action(
        self, capability_id: str, args: dict[str, Any], *, now: datetime
    ) -> ActionContract:
        return ActionContract(
            action_id=f"action:mandate-terminal:{uuid4()}",
            task_id=self.task_id,
            run_id=self.run_id,
            node_id=f"node:{capability_id}:{uuid4()}",
            principal_id=self.principal_id,
            tenant_id=self.tenant_id,
            workspace_id=self.workspace_id,
            capability_id=capability_id,
            capability_version="1",
            arguments_json=json.dumps(args, sort_keys=True),
            risk_tier=1 if capability_id in WRITE_CAPABILITIES else 0,
            idempotency_key=f"{self.run_id}:{capability_id}:{uuid4()}",
            estimated_budget=ResourceBudget(
                max_cost_usd=Decimal("0"),
                max_duration_seconds=120,
                max_provider_tokens=0,
                max_tool_calls=1,
            ),
            policy_version="policy:mandate-terminal-v0",
            observed_correction_epochs=self.correction.snapshot(
                self.task_id, self.run_id, capability_id
            ),
            expected_outcome_id="expected:mandate-terminal",
            candidate_envelope_id="envelope:mandate-terminal",
            created_at=now,
        )
