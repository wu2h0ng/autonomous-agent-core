"""Interactive Mandate terminal agent (stdin/stdout REPL).

Product entry aligned with Codex / Claude Code / OpenCode launch shape:
boot loads durable Mandate attach; multi-turn provider loop may invoke
typed workspace capabilities; /help escalates through HelpRequest.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable, Sequence, TextIO
from uuid import uuid4

from agent_os_contracts import (
    CredentialRef,
    CredentialStatus,
    HelpRequest,
    ProviderErrorCode,
    ProviderFailure,
    ProviderMessage,
    ProviderMessageRole,
    ProviderProfile,
    ProviderRequest,
    ProviderResponse,
    ProviderToolProposal,
    ProviderUsage,
)

from .mandate_terminal import (
    MandateAttachSession,
    emit_help_request,
    ensure_local_mandate_session,
    load_attach_session,
    mandate_status,
)
from .terminal_mcp import MandateMcpHub, McpError
from .terminal_tui import TerminalRenderer
from .terminal_session import (
    TerminalSessionState,
    TerminalSessionTurn,
    load_terminal_session,
    save_terminal_session,
)
from .mandate_tool_runtime import (
    TERMINAL_CAPABILITIES,
    WRITE_CAPABILITIES,
    MandateToolRuntime,
)
from .provider import DeterministicProvider, ProviderPort
from .situated_persistence import SQLiteSituatedAssessmentStore

HISTORY_LIMIT = 24
MAX_TOOL_ROUNDS = 32
MAX_CONTINUATION_CYCLES = 8


@dataclass
class MandateReplTurn:
    role: str
    content: str


@dataclass
class MandateReplResult:
    turns: int
    quit_reason: str
    help_emitted: int = 0
    provider_calls: int = 0
    tool_invocations: int = 0
    patches_applied: int = 0
    continuation_cycles: int = 0
    auto_attached: bool = False
    history: list[MandateReplTurn] = field(default_factory=list)


class SequencedProvider(ProviderPort):
    """Test/CI provider that returns a fixed sequence of typed responses."""

    def __init__(self, responses: Sequence[ProviderResponse | ProviderFailure]) -> None:
        if not responses:
            raise ValueError("SequencedProvider requires at least one response")
        self._responses = list(responses)
        self.requests: list[ProviderRequest] = []

    def complete(self, request: ProviderRequest) -> ProviderResponse | ProviderFailure:
        self.requests.append(request)
        if not self._responses:
            return ProviderFailure(
                failure_id=f"failure-{uuid4()}",
                request_id=request.request_id,
                code=ProviderErrorCode.UNAVAILABLE,
                retryable=False,
                safe_message="sequenced provider exhausted",
                occurred_at=datetime.now(timezone.utc),
            )
        return self._responses.pop(0)


def make_tool_response(
    *,
    request_id: str,
    text: str = "",
    tool_proposals: tuple[ProviderToolProposal, ...] = (),
) -> ProviderResponse:
    return ProviderResponse(
        response_id=f"response-{uuid4()}",
        request_id=request_id,
        text=text,
        tool_proposals=tool_proposals,
        usage=ProviderUsage(
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            estimated_cost_usd=Decimal("0"),
        ),
        finish_reason="tool_calls" if tool_proposals else "stop",
        received_at=datetime.now(timezone.utc),
    )


def format_status_banner(
    status: dict[str, object],
    *,
    tools_enabled: bool,
    repo_root: Path,
) -> str:
    commitments = status.get("open_commitments") or []
    lines = [
        "=== Agent OS Mandate Terminal ===",
        f"mandate: {status.get('mandate_id')} v{status.get('mandate_version')} [{status.get('status')}]",
        f"owner: {status.get('owner_principal_id')}  tenant/workspace: {status.get('tenant_id')}/{status.get('workspace_id')}",
        f"expires: {status.get('expires_at')}",
        f"mission: {status.get('mission_statement') or '(no relevance context)'}",
        f"repo: {repo_root}",
        f"tools: {'ON ' + ','.join(TERMINAL_CAPABILITIES) if tools_enabled else 'OFF (chat only)'}",
    ]
    if commitments:
        lines.append("open commitments:")
        for item in commitments:
            if isinstance(item, dict):
                lines.append(f"  - {item.get('commitment_id')}: {item.get('statement')}")
    constraints = status.get("permanent_constraints") or []
    if constraints:
        lines.append("constraints: " + "; ".join(str(c) for c in constraints))
    lines.extend(
        [
            "commands: /status  /tools  /help <q>  /continue  /stop  /save  /resume  /quit",
            "claim_ceiling: AGENT_OS_TERMINAL_V2 / NO_AUTONOMY / NO_HCW_CLAIM",
            "================================",
        ]
    )
    return "\n".join(lines)


def build_system_prompt(status: dict[str, object], *, tools_enabled: bool) -> str:
    tool_clause = (
        "You may call typed tools workspace.read, workspace.search, "
        "workspace.apply_patch, workspace.run_tests, and workspace.shell. "
        "Prefer search/read before write. apply_patch args use path+content. "
        "search args use pattern/glob/path. "
        "shell args use argv list of allowlisted programs only; no shell metacharacters. "
        "run_tests command must be allowlisted pytest. "
        "When continuing autonomously, end with DONE if the goal is complete or BLOCKED if you need the operator."
        if tools_enabled
        else "You have no tools in this session; answer with text only."
    )
    return (
        "You are the Agent OS Mandate terminal agent. "
        "You operate under a durable ratified Mandate already loaded in this process. "
        "Do not ask the operator to restate who you are or what the Mandate is; use the context below. "
        f"{tool_clause} "
        "Escalate irreducible value/authority/irreversible questions with /help. "
        "You have no authority to grant permissions, bypass C7, or claim autonomy.\n\n"
        f"MANDATE_CONTEXT_JSON:\n{json.dumps(status, ensure_ascii=False, indent=2, default=str)}\n"
    )


class MandateRepl:
    def __init__(
        self,
        *,
        workspace: Path,
        provider: ProviderPort,
        session: MandateAttachSession | None = None,
        provider_profile_id: str = "provider-profile:mandate-repl",
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        input_fn: Callable[[str], str] | None = None,
        clock: Callable[[], datetime] | None = None,
        initial_prompt: str | None = None,
        tools_enabled: bool = True,
        repo_root: Path | None = None,
        auto_approve_patches: bool = False,
        max_tool_rounds: int = MAX_TOOL_ROUNDS,
        tool_runtime: MandateToolRuntime | None = None,
        continue_autonomous: bool = False,
        max_continuation_cycles: int = MAX_CONTINUATION_CYCLES,
        auto_attached: bool = False,
        resume_session: bool = False,
        enable_tui: bool = False,
        enable_mcp: bool = True,
    ) -> None:
        self.workspace = Path(workspace)
        self.provider = provider
        self.session = session or load_attach_session(self.workspace)
        self.provider_profile_id = provider_profile_id
        self._stdin = stdin
        self._stdout = stdout
        self._input_fn = input_fn
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._history: list[MandateReplTurn] = []
        self._initial_prompt = (initial_prompt or "").strip() or None
        self.tools_enabled = tools_enabled
        self.repo_root = Path(repo_root or Path.cwd()).resolve()
        self.auto_approve_patches = auto_approve_patches
        self.max_tool_rounds = max_tool_rounds
        self.continue_autonomous = continue_autonomous
        self.max_continuation_cycles = max_continuation_cycles
        self.auto_attached = auto_attached
        self.resume_session = resume_session
        self.enable_tui = enable_tui
        self.enable_mcp = enable_mcp
        self._mcp_hub: MandateMcpHub | None = None
        self._renderer: TerminalRenderer | None = None
        self.tool_runtime = tool_runtime or (
            MandateToolRuntime(
                repo_root=self.repo_root,
                principal_id=self.session.principal_id,
                tenant_id=self.session.tenant_id,
                workspace_id=self.session.workspace_id,
                clock=self._clock,
            )
            if tools_enabled
            else None
        )

    def run(self) -> MandateReplResult:
        status = mandate_status(workspace=self.workspace, session=self.session)
        self._write(
            format_status_banner(
                status, tools_enabled=self.tools_enabled, repo_root=self.repo_root
            )
            + "\n"
        )
        if self.auto_attached:
            self._write("[zero-config] local Mandate bootstrap+attach completed\n")
        if self.enable_tui:
            self._renderer = TerminalRenderer(stdout=self._stdout)
            self._renderer.start("Agent OS Mandate Terminal")
        if self.enable_mcp:
            try:
                self._mcp_hub = MandateMcpHub(self.workspace)
                tools = self._mcp_hub.start()
                if tools:
                    self._write(f"[mcp] loaded {len(tools)} tools\n")
                    if self._renderer:
                        self._renderer.set_status(f"MCP tools={len(tools)}")
            except Exception as exc:  # noqa: BLE001
                self._write(f"[mcp] disabled: {exc}\n")
                self._mcp_hub = None
        try:
            return self._run_session(status=status, goal_from_session_seed=None)
        finally:
            self._shutdown_extras()

    def _shutdown_extras(self) -> None:
        if self._renderer is not None:
            self._renderer.stop()
            self._renderer = None
        if self._mcp_hub is not None:
            self._mcp_hub.close()
            self._mcp_hub = None

    def _run_session(
        self,
        *,
        status: dict[str, object],
        goal_from_session_seed: str | None,
    ) -> MandateReplResult:
        goal_from_session = goal_from_session_seed
        if self.resume_session:
            loaded = load_terminal_session(self.workspace)
            if loaded is None:
                self._write("[resume] no saved session\n")
            else:
                self._history = [
                    MandateReplTurn(role=item.role, content=item.content)
                    for item in loaded.turns
                ]
                goal_from_session = loaded.goal
                self._write(
                    f"[resume] loaded {len(self._history)} turns"
                    + (f" goal={loaded.goal!r}" if loaded.goal else "")
                    + "\n"
                )
        turns = 0
        help_emitted = 0
        provider_calls = 0
        tool_invocations = 0
        patches_applied = 0
        continuation_cycles = 0
        pending: str | None = self._initial_prompt
        autonomous = self.continue_autonomous and (
            self._initial_prompt is not None or goal_from_session is not None
        )
        goal = self._initial_prompt or goal_from_session
        stop_requested = False
        while True:
            try:
                if pending is not None:
                    line = pending
                    pending = None
                    self._write(f"> {line}\n")
                else:
                    line = self._read("> ")
            except EOFError:
                self._write("\n[eof]\n")
                return MandateReplResult(
                    turns=turns,
                    quit_reason="eof",
                    help_emitted=help_emitted,
                    provider_calls=provider_calls,
                    tool_invocations=tool_invocations,
                    patches_applied=patches_applied,
                    continuation_cycles=continuation_cycles,
                    auto_attached=self.auto_attached,
                    history=list(self._history),
                )
            text = line.strip()
            if not text:
                continue
            if text in {"/quit", "/exit", ":q"}:
                self._write("bye\n")
                return MandateReplResult(
                    turns=turns,
                    quit_reason="quit",
                    help_emitted=help_emitted,
                    provider_calls=provider_calls,
                    tool_invocations=tool_invocations,
                    patches_applied=patches_applied,
                    continuation_cycles=continuation_cycles,
                    auto_attached=self.auto_attached,
                    history=list(self._history),
                )
            if text == "/status":
                status = mandate_status(workspace=self.workspace, session=self.session)
                self._write(
                    format_status_banner(
                        status,
                        tools_enabled=self.tools_enabled,
                        repo_root=self.repo_root,
                    )
                    + "\n"
                )
                continue
            if text == "/tools":
                if not self.tools_enabled or self.tool_runtime is None:
                    self._write("tools: OFF\n")
                else:
                    caps = list(self.tool_runtime.allowed_capability_ids())
                    if self._mcp_hub is not None:
                        caps.extend(self._mcp_hub.tool_ids())
                    self._write(
                        "tools: "
                        + ", ".join(caps)
                        + f"\nrepo: {self.repo_root}\n"
                        "writes/mcp require interactive approval "
                        f"(auto_approve={self.auto_approve_patches})\n"
                    )
                continue
            if text == "/stop":
                self._write("[continuation stopped]\n")
                stop_requested = True
                autonomous = False
                continue
            if text == "/save":
                saved = self._persist_session(
                    goal=goal,
                    tool_invocations=tool_invocations,
                    patches_applied=patches_applied,
                    continuation_cycles=continuation_cycles,
                    status=status,
                )
                self._write(f"[session saved] {saved}\n")
                continue
            if text == "/resume":
                loaded = load_terminal_session(self.workspace)
                if loaded is None:
                    self._write("[resume] no saved session\n")
                    continue
                self._history = [
                    MandateReplTurn(role=item.role, content=item.content)
                    for item in loaded.turns
                ]
                if loaded.goal:
                    goal = loaded.goal
                self._write(f"[resume] loaded {len(self._history)} turns\n")
                continue
            if text == "/continue":
                if goal is None:
                    self._write("usage: start with a goal prompt, then /continue\n")
                    continue
                autonomous = True
                pending = self._continuation_prompt(goal)
                continue
            if text.startswith("/help"):
                question = text[len("/help") :].strip()
                if not question:
                    self._write("usage: /help <irreducible question for founder>\n")
                    continue
                receipt = self._emit_help(question, status)
                help_emitted += 1
                turns += 1
                self._write(
                    "[help-request emitted]\n"
                    f"  id: {receipt['help_request_id']}\n"
                    f"  inbox: {receipt['inbox_path']}\n"
                )
                continue

            reply, ok, stats = self._complete_turn(text, status)
            provider_calls += stats["provider_calls"]
            tool_invocations += stats["tool_invocations"]
            patches_applied += stats["patches_applied"]
            turns += 1
            self._history.append(MandateReplTurn("user", text))
            self._history.append(MandateReplTurn("assistant", reply))
            self._trim_history()
            prefix = "" if ok else "[provider-failure] "
            if self._renderer is not None and ok and not prefix:
                # already streamed via renderer
                self._write("\n")
            else:
                self._write(prefix + reply + "\n")
            self._persist_session(
                goal=goal,
                tool_invocations=tool_invocations,
                patches_applied=patches_applied,
                continuation_cycles=continuation_cycles,
                status=status,
            )
            if not ok or stop_requested:
                autonomous = False
            if autonomous and goal is not None:
                if self._is_terminal_reply(reply):
                    self._write("[continuation] terminal signal received\n")
                    autonomous = False
                elif continuation_cycles >= self.max_continuation_cycles:
                    self._write(
                        f"[continuation] reached max cycles ({self.max_continuation_cycles})\n"
                    )
                    autonomous = False
                else:
                    continuation_cycles += 1
                    pending = self._continuation_prompt(goal)
                    self._write(
                        f"[continuation] cycle {continuation_cycles}/{self.max_continuation_cycles}\n"
                    )
                    continue



    def _persist_session(
        self,
        *,
        goal: str | None,
        tool_invocations: int,
        patches_applied: int,
        continuation_cycles: int,
        status: dict[str, object],
    ) -> Path:
        state = TerminalSessionState(
            goal=goal,
            repo_root=str(self.repo_root),
            mandate_id=str(status.get("mandate_id") or ""),
            turns=[
                TerminalSessionTurn(role=item.role, content=item.content)
                for item in self._history
            ],
            tool_invocations=tool_invocations,
            patches_applied=patches_applied,
            continuation_cycles=continuation_cycles,
        )
        return save_terminal_session(self.workspace, state)

    @staticmethod
    def _continuation_prompt(goal: str) -> str:
        return (
            "CONTINUE AUTONOMOUSLY: advance the standing goal without waiting for the "
            "operator. Use tools as needed. If finished, reply with DONE and a short "
            "summary. If blocked on irreducible authority/value, say BLOCKED and recommend "
            f"/help. Goal: {goal}"
        )

    @staticmethod
    def _is_terminal_reply(reply: str) -> bool:
        stripped = reply.strip()
        if not stripped:
            return False
        head = stripped.splitlines()[0].strip().upper()
        return (
            head.startswith("DONE")
            or head.startswith("BLOCKED")
            or head.startswith("HELP")
        )

    def _complete_turn(
        self, user_text: str, status: dict[str, object]
    ) -> tuple[str, bool, dict[str, int]]:
        messages = [
            ProviderMessage(
                role=ProviderMessageRole.SYSTEM,
                content=build_system_prompt(status, tools_enabled=self.tools_enabled),
            )
        ]
        for turn in self._history:
            role = (
                ProviderMessageRole.USER
                if turn.role == "user"
                else ProviderMessageRole.ASSISTANT
            )
            messages.append(ProviderMessage(role=role, content=turn.content))
        messages.append(
            ProviderMessage(role=ProviderMessageRole.USER, content=user_text)
        )
        stats = {"provider_calls": 0, "tool_invocations": 0, "patches_applied": 0}
        allowed = (
            self.tool_runtime.allowed_capability_ids()
            if self.tools_enabled and self.tool_runtime is not None
            else ()
        )
        final_text = ""
        for _round in range(self.max_tool_rounds):
            request = ProviderRequest(
                request_id=f"req:mandate-repl:{uuid4()}",
                task_id="task:mandate-repl",
                run_id="run:mandate-repl",
                provider_profile_id=self.provider_profile_id,
                messages=tuple(messages),
                allowed_capability_ids=allowed,
                timeout_seconds=120,
                created_at=self._clock(),
            )
            extra_tools: tuple[dict, ...] = ()
            if self._mcp_hub is not None:
                extra_tools = tuple(self._mcp_hub.tool_openai_specs())
            on_delta = None
            if self._renderer is not None:
                self._renderer.set_assistant("")
                on_delta = self._renderer.append_assistant
            result = self.provider.complete_streaming(
                request,
                on_text_delta=on_delta,
                extra_tools=extra_tools,
            )
            stats["provider_calls"] += 1
            if isinstance(result, ProviderFailure):
                return (result.safe_message or result.code.value, False, stats)
            if not isinstance(result, ProviderResponse):
                return ("unknown provider result", False, stats)
            if result.text.strip():
                final_text = result.text
                if self._renderer is not None and on_delta is None:
                    self._renderer.set_assistant(final_text)
            if not result.tool_proposals:
                return (final_text or "(empty)", True, stats)
            if self.tool_runtime is None:
                return ("tools disabled but provider returned tool proposals", False, stats)
            tool_notes: list[str] = []
            for proposal in result.tool_proposals:
                note, applied = self._handle_proposal(proposal)
                stats["tool_invocations"] += 1
                if applied:
                    stats["patches_applied"] += 1
                tool_notes.append(note)
                self._write(note + "\n")
                if self._renderer is not None:
                    self._renderer.add_tool(note.splitlines()[0][:160])
            messages.append(
                ProviderMessage(
                    role=ProviderMessageRole.ASSISTANT,
                    content=result.text or "(tool calls)",
                )
            )
            messages.append(
                ProviderMessage(
                    role=ProviderMessageRole.USER,
                    content="TOOL_RESULTS:\n" + "\n\n".join(tool_notes),
                )
            )
        return (
            final_text or f"stopped after {self.max_tool_rounds} tool rounds",
            True,
            stats,
        )

    def _handle_proposal(self, proposal: ProviderToolProposal) -> tuple[str, bool]:
        assert self.tool_runtime is not None
        is_mcp = proposal.capability_id.startswith("mcp.")
        if is_mcp:
            summary = f"MCP {proposal.capability_id} args={proposal.arguments_json[:400]}"
        else:
            summary = self.tool_runtime.summarize_proposal(proposal)
        approved = True
        applied = False
        needs_approval = proposal.capability_id in WRITE_CAPABILITIES or is_mcp
        if needs_approval:
            if self.auto_approve_patches:
                approved = True
                self._write(f"[auto-approve]\n{summary}\n")
            else:
                self._write(f"[approval required]\n{summary}\n")
                try:
                    answer = self._read("Approve write/shell/mcp? [y/N] ").strip().lower()
                except EOFError:
                    answer = "n"
                approved = answer in {"y", "yes"}
                if not approved:
                    return (
                        f"TOOL_DENIED capability={proposal.capability_id} "
                        f"reason=operator_rejected\n{summary}",
                        False,
                    )
        if is_mcp:
            if self._mcp_hub is None:
                payload = {
                    "capability_id": proposal.capability_id,
                    "ok": False,
                    "error": "mcp hub not started",
                    "output": {},
                }
                return (
                    f"TOOL_RESULT {json.dumps(payload, ensure_ascii=False, default=str)}",
                    False,
                )
            try:
                args = json.loads(proposal.arguments_json)
                if not isinstance(args, dict):
                    raise McpError("arguments must be object")
                output = self._mcp_hub.call(proposal.capability_id, args)
                payload = {
                    "capability_id": proposal.capability_id,
                    "ok": True,
                    "error": None,
                    "output": output,
                }
                return (
                    f"TOOL_RESULT {json.dumps(payload, ensure_ascii=False, default=str)}",
                    True,
                )
            except (McpError, json.JSONDecodeError, TypeError, ValueError) as exc:
                payload = {
                    "capability_id": proposal.capability_id,
                    "ok": False,
                    "error": str(exc),
                    "output": {},
                }
                return (
                    f"TOOL_RESULT {json.dumps(payload, ensure_ascii=False, default=str)}",
                    False,
                )
        result = self.tool_runtime.invoke_proposal(proposal, approved=approved)
        if result.ok and proposal.capability_id in WRITE_CAPABILITIES:
            applied = True
        payload = {
            "capability_id": result.capability_id,
            "ok": result.ok,
            "error": result.error,
            "output": result.output,
            "action_digest": result.action_digest,
        }
        return (
            f"TOOL_RESULT {json.dumps(payload, ensure_ascii=False, default=str)}",
            applied,
        )

    def _emit_help(self, question: str, status: dict[str, object]) -> dict[str, object]:
        store = SQLiteSituatedAssessmentStore(Path(self.session.database))
        mandate, binding = store.resolve_active(
            self.session.mandate_id,
            self.session.environment_binding_id,
            principal_id=self.session.principal_id,
            tenant_id=self.session.tenant_id,
            workspace_id=self.session.workspace_id,
            evaluated_at=self._clock(),
        )
        digest = hashlib.sha256(question.encode("utf-8")).hexdigest()
        help_request = HelpRequest(
            help_request_id=f"help:repl:{uuid4()}",
            source_binding_digest=digest,
            mandate_id=mandate.mandate_id,
            mandate_version=mandate.version,
            mandate_digest=mandate.mandate_digest,
            environment_binding_id=binding.environment_binding_id,
            environment_binding_version=binding.version,
            environment_binding_digest=binding.binding_digest,
            correction_epoch=mandate.correction_epoch,
            assessor=mandate.relevance_assessor,
            tenant_id=mandate.tenant_id,
            workspace_id=mandate.workspace_id,
            triggering_event_id=f"event:repl:{uuid4()}",
            event_observation_digest=digest,
            projection_id=f"projection:repl:{uuid4()}",
            projection_digest=digest,
            relevance_assessment_id=f"assessment:repl:{uuid4()}",
            known_facts=(
                f"Mission: {status.get('mission_statement') or 'unspecified'}",
                f"Mandate status: {status.get('status')}",
            ),
            unknown_facts=(question,),
            acquisition_attempts=(
                "Asked within Mandate terminal REPL before escalation.",
            ),
            bounded_options=(
                "Answer the irreducible question",
                "Revoke or amend Mandate",
                "Park this line of work",
            ),
            minimum_external_input=question,
            continuable_work=("Continue non-irreducible Mandate work in REPL.",),
            rationale=(
                "Terminal Mandate agent escalated an irreducible founder decision."
            ),
            evidence_ids=(f"evidence:repl:{digest[:16]}",),
            created_at=self._clock(),
            authority_granted=False,
            external_effects_authorized=False,
        )
        return emit_help_request(
            workspace=self.workspace,
            help_request=help_request,
            evaluated_at=self._clock(),
            session=self.session,
        )

    def _trim_history(self) -> None:
        if len(self._history) > HISTORY_LIMIT:
            self._history = self._history[-HISTORY_LIMIT:]

    def _write(self, text: str) -> None:
        out = self._stdout
        if out is None:
            print(text, end="")
        else:
            out.write(text)
            out.flush()

    def _read(self, prompt: str) -> str:
        if self._input_fn is not None:
            return self._input_fn(prompt)
        if self._stdin is not None:
            self._write(prompt)
            line = self._stdin.readline()
            if line == "":
                raise EOFError
            return line.rstrip("\n")
        return input(prompt)


def default_repl_provider(*, offline: bool = False) -> ProviderPort:
    """Live OpenAI-compatible provider when env is set; else deterministic offline."""
    from .provider import EnvCredentialBroker, OpenAICompatibleProvider

    offline_text = (
        "Acknowledged under the loaded Mandate. "
        "Use tools when enabled, or /help <question> for irreducible escalation."
    )
    if offline or not os.environ.get("AGENT_OS_PROVIDER_BASE_URL"):
        return DeterministicProvider(text=offline_text)

    now = datetime.now(timezone.utc)
    base_url = os.environ["AGENT_OS_PROVIDER_BASE_URL"]
    model = os.environ.get("AGENT_OS_PROVIDER_MODEL", "gpt-4o-mini")
    timeout = int(os.environ.get("AGENT_OS_PROVIDER_TIMEOUT_SECONDS", "60"))
    api_key_env = os.environ.get("AGENT_OS_PROVIDER_API_KEY_ENV", "OPENAI_API_KEY")
    credential = CredentialRef(
        credential_ref_id="credential:mandate-repl",
        owner_principal_id="user:founder",
        tenant_id="tenant:portfolio",
        workspace_id="workspace:founder",
        provider_id="openai-compatible",
        resolver_key=api_key_env,
        scopes=("chat",),
        status=CredentialStatus.ACTIVE,
        created_at=now,
        expires_at=now + timedelta(days=30),
    )
    profile = ProviderProfile(
        profile_id="provider-profile:mandate-repl",
        provider_id="openai-compatible",
        model_id=model,
        model_revision_digest=os.environ.get(
            "AGENT_OS_PROVIDER_MODEL_REVISION_DIGEST"
        ),
        endpoint_class="openai-compatible",
        credential_ref_id=credential.credential_ref_id,
        capabilities=("chat",),
        max_context_tokens=16_000,
        request_timeout_seconds=timeout,
        created_at=datetime(1970, 1, 1, tzinfo=timezone.utc),
    )
    return OpenAICompatibleProvider(
        base_url=base_url,
        model=model,
        credential=credential,
        credentials=EnvCredentialBroker(),
        timeout_seconds=timeout,
        provider_profile=profile,
    )


def run_mandate_repl(
    *,
    workspace: Path,
    provider: ProviderPort | None = None,
    offline: bool = False,
    initial_prompt: str | None = None,
    tools_enabled: bool = True,
    repo_root: Path | None = None,
    auto_approve_patches: bool = False,
    continue_autonomous: bool = False,
    resume_session: bool = False,
    max_continuation_cycles: int = MAX_CONTINUATION_CYCLES,
    database: Path | None = None,
    zero_config: bool = True,
    mission_statement: str | None = None,
    **kwargs: object,
) -> MandateReplResult:
    workspace = Path(workspace)
    database = Path(database) if database is not None else Path("agent-os.sqlite3")
    auto_attached = False
    session = None
    if zero_config:
        try:
            load_attach_session(workspace)
        except Exception:
            session, auto_attached = ensure_local_mandate_session(
                workspace=workspace,
                database=database,
                mission_statement=mission_statement,
                goal_statement=initial_prompt,
            )
    if provider is None:
        provider = default_repl_provider(offline=offline)
    repl = MandateRepl(
        workspace=workspace,
        provider=provider,
        session=session,
        initial_prompt=initial_prompt,
        tools_enabled=tools_enabled,
        repo_root=repo_root,
        auto_approve_patches=auto_approve_patches,
        continue_autonomous=continue_autonomous,
        max_continuation_cycles=max_continuation_cycles,
        auto_attached=auto_attached,
        resume_session=resume_session,
        **kwargs,  # type: ignore[arg-type]
    )
    return repl.run()
