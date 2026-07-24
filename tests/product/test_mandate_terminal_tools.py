"""Mandate coding terminal tool loop (AGENT-OS-TERMINAL-1 V0)."""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_os_contracts import ProviderToolProposal
from agent_os_core.mandate_repl import (
    MandateRepl,
    SequencedProvider,
    make_tool_response,
)
from agent_os_core.mandate_terminal import attach_mandate, bootstrap_mandate
from agent_os_contracts import (
    EnvironmentBindingAuthorization,
    MandateCommitmentContext,
    MandateOutcomeContext,
    MandateRelevanceContext,
    RatifiedMandateRef,
    RelevanceAssessorRef,
)

NOW = datetime(2026, 7, 24, 8, 0, tzinfo=timezone.utc)
MANDATE_DIGEST = "a" * 64
BINDING_DIGEST = "b" * 64
POLICY_DIGEST = "c" * 64


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    database = tmp_path / "situated.sqlite3"
    workspace = tmp_path / "ws"
    repo = tmp_path / "repo"
    workspace.mkdir()
    repo.mkdir()
    (repo / "hello.txt").write_text("hello\n", encoding="utf-8")
    mandate = RatifiedMandateRef(
        mandate_id="mandate:meta-shadow-0",
        version=1,
        mandate_digest=MANDATE_DIGEST,
        ratification_receipt_id="ratification:founder-1",
        tenant_id="tenant:portfolio",
        workspace_id="workspace:founder",
        owner_principal_id="user:founder",
        ratified_by="user:founder",
        ratified_at=NOW - timedelta(hours=1),
        valid_from=NOW - timedelta(hours=1),
        expires_at=NOW + timedelta(days=7),
        correction_epoch=0,
        authority_envelope_digest="e" * 64,
        allowed_environment_bindings=(
            EnvironmentBindingAuthorization(
                environment_binding_id="binding:portfolio",
                version=1,
                binding_digest=BINDING_DIGEST,
            ),
        ),
        relevance_assessor=RelevanceAssessorRef(
            assessor_id="assessor:terminal-v0",
            version=1,
            policy_digest=POLICY_DIGEST,
        ),
    )
    context = MandateRelevanceContext(
        relevance_context_id="relevance:meta-shadow-0",
        version=1,
        mandate_id="mandate:meta-shadow-0",
        mandate_version=1,
        mandate_digest=MANDATE_DIGEST,
        tenant_id="tenant:portfolio",
        workspace_id="workspace:founder",
        mission_statement="Operate Agent OS terminal like a coding CLI.",
        desired_outcomes=(
            MandateOutcomeContext(
                outcome_id="outcome:terminal",
                statement="Multi-turn tools under Mandate.",
            ),
        ),
        open_commitments=(
            MandateCommitmentContext(
                commitment_id="commitment:tools",
                statement="Ship terminal tool loop.",
            ),
        ),
        permanent_constraints=("C7 non-bypassable",),
    )
    bootstrap_mandate(
        database=database,
        mandate=mandate,
        relevance_context=context,
        workspace=workspace,
    )
    attach_mandate(
        workspace=workspace,
        database=database,
        mandate_id="mandate:meta-shadow-0",
        environment_binding_id="binding:portfolio",
        principal_id="user:founder",
        tenant_id="tenant:portfolio",
        workspace_id="workspace:founder",
        evaluated_at=NOW,
    )
    return workspace, repo


def test_tools_enabled_on_provider_request(tmp_path: Path) -> None:
    workspace, repo = _setup(tmp_path)
    provider = SequencedProvider(
        [
            make_tool_response(
                request_id="req-placeholder",
                text="done",
            )
        ]
    )
    # make_tool_response ignores request_id match; SequencedProvider returns as-is
    lines = iter(["ping", "/quit"])
    out = io.StringIO()
    MandateRepl(
        workspace=workspace,
        provider=provider,
        input_fn=lambda _p: next(lines),
        stdout=out,
        clock=lambda: NOW,
        repo_root=repo,
        tools_enabled=True,
    ).run()
    assert provider.requests[0].allowed_capability_ids == (
        "workspace.apply_patch",
        "workspace.glob",
        "workspace.read",
        "workspace.run_tests",
        "workspace.search",
        "workspace.shell",
    )
    assert "tools: ON" in out.getvalue()


def test_read_then_patch_requires_approval(tmp_path: Path) -> None:
    workspace, repo = _setup(tmp_path)
    read_proposal = ProviderToolProposal(
        proposal_id="proposal:read-1",
        capability_id="workspace.read",
        arguments_json=json.dumps({"path": "hello.txt"}),
    )
    patch_proposal = ProviderToolProposal(
        proposal_id="proposal:patch-1",
        capability_id="workspace.apply_patch",
        arguments_json=json.dumps({"path": "hello.txt", "content": "hello world\n"}),
    )
    provider = SequencedProvider(
        [
            make_tool_response(
                request_id="r1",
                text="reading",
                tool_proposals=(read_proposal,),
            ),
            make_tool_response(
                request_id="r2",
                text="patching",
                tool_proposals=(patch_proposal,),
            ),
            make_tool_response(request_id="r3", text="finished"),
        ]
    )
    answers = iter(["fix hello.txt", "n", "/quit"])
    out = io.StringIO()
    result = MandateRepl(
        workspace=workspace,
        provider=provider,
        input_fn=lambda _p: next(answers),
        stdout=out,
        clock=lambda: NOW,
        repo_root=repo,
        auto_approve_patches=False,
    ).run()
    assert (repo / "hello.txt").read_text(encoding="utf-8") == "hello\n"
    assert result.tool_invocations >= 2
    assert result.patches_applied == 0
    assert "operator_rejected" in out.getvalue() or "TOOL_DENIED" in out.getvalue()


def test_patch_applies_when_approved(tmp_path: Path) -> None:
    workspace, repo = _setup(tmp_path)
    patch_proposal = ProviderToolProposal(
        proposal_id="proposal:patch-2",
        capability_id="workspace.apply_patch",
        arguments_json=json.dumps({"path": "hello.txt", "content": "patched\n"}),
    )
    provider = SequencedProvider(
        [
            make_tool_response(
                request_id="r1",
                text="will patch",
                tool_proposals=(patch_proposal,),
            ),
            make_tool_response(request_id="r2", text="done"),
        ]
    )
    answers = iter(["patch it", "y", "/quit"])
    out = io.StringIO()
    result = MandateRepl(
        workspace=workspace,
        provider=provider,
        input_fn=lambda _p: next(answers),
        stdout=out,
        clock=lambda: NOW,
        repo_root=repo,
    ).run()
    assert (repo / "hello.txt").read_text(encoding="utf-8") == "patched\n"
    assert result.patches_applied == 1
    assert "TOOL_RESULT" in out.getvalue()


def test_auto_approve_flag_applies_without_prompt(tmp_path: Path) -> None:
    workspace, repo = _setup(tmp_path)
    patch_proposal = ProviderToolProposal(
        proposal_id="proposal:patch-3",
        capability_id="workspace.apply_patch",
        arguments_json=json.dumps({"path": "new.txt", "content": "created\n"}),
    )
    provider = SequencedProvider(
        [
            make_tool_response(
                request_id="r1",
                tool_proposals=(patch_proposal,),
            ),
            make_tool_response(request_id="r2", text="created file"),
        ]
    )
    answers = iter(["create", "/quit"])
    result = MandateRepl(
        workspace=workspace,
        provider=provider,
        input_fn=lambda _p: next(answers),
        stdout=io.StringIO(),
        clock=lambda: NOW,
        repo_root=repo,
        auto_approve_patches=True,
    ).run()
    assert (repo / "new.txt").read_text(encoding="utf-8") == "created\n"
    assert result.patches_applied == 1
