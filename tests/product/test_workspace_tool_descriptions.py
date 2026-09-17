"""The tool list must tell the model what each tool is and what it returns.

``_tool_definition`` used to send every capability the same sentence --
"Propose typed capability <id>" -- so the model received no tool semantics at
all. The sharpest cost was ``workspace.search``: its truncation diagnostics
(``truncated_reason``, ``scanned_files``, ``unexamined_files``) were invisible
to their only consumer, and ``matches: []`` under the scan cap read exactly
like a completed search that found nothing.

These tests pin one factual description per model-facing tool, pin the scan-cap
diagnostics into the ``workspace.search`` description, and keep every claim the
descriptions make (effect class, risk tier, search caps, tool-result budget) in
sync with the code that owns it. Deleting a description back to the generic
sentence, or letting one of those facts drift away from the implementation,
turns them red.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

from agent_os_contracts import (
    ActionContract,
    CorrectionEpochVector,
    CredentialRef,
    CredentialStatus,
    ProviderMessage,
    ProviderMessageRole,
    ProviderRequest,
    ResourceBudget,
)

from agent_os_core import provider as provider_module
from agent_os_core.agent_loop import CHAT_CAPABILITY_IDS, _MAX_TOOL_RESULT_CHARS
from agent_os_core.permission_gate import ACTION_RISK_TIERS
from domain_packs.developer_agent import DeveloperWorkspaceAdapter

# Every tool that reaches the model with a capability-specific description.
# CHAT_CAPABILITY_IDS is the interactive chat surface; artifact.write is in the
# developer pack's specs(), which the execution path sends in full.
DESCRIBED: tuple[str, ...] = (
    "workspace.read",
    "workspace.search",
    "workspace.edit",
    "workspace.apply_patch",
    "workspace.run_tests",
    "workspace.shell",
    "artifact.write",
    "session.todo_write",
)
GENERIC_DESCRIPTION = "Propose typed capability {capability_id}"
NEEDLE = "TOOL_DESCRIPTION_SCAN_CAP_NEEDLE"


def _function(capability_id: str) -> dict[str, Any]:
    definition = provider_module._tool_definition(capability_id)
    return cast("dict[str, Any]", definition["function"])


def _description(capability_id: str) -> str:
    return cast("str", _function(capability_id)["description"])


def _search(
    adapter: DeveloperWorkspaceAdapter, arguments: dict[str, object]
) -> dict[str, Any]:
    action = ActionContract(
        action_id="action:tool-description",
        task_id="task:tool-description",
        run_id="run:tool-description",
        node_id="node:tool-description",
        principal_id="principal:tool-description",
        tenant_id="tenant:tool-description",
        workspace_id="workspace:tool-description",
        capability_id="workspace.search",
        capability_version="1",
        arguments_json=json.dumps(arguments),
        risk_tier=1,
        idempotency_key="idempotency:tool-description",
        estimated_budget=ResourceBudget(
            max_cost_usd=Decimal("0"),
            max_duration_seconds=120,
            max_provider_tokens=0,
            max_tool_calls=1,
        ),
        policy_version="policy-1",
        observed_correction_epochs=CorrectionEpochVector(
            task_epoch=0, run_epoch=0, capability_epoch=0
        ),
        expected_outcome_id="expected:tool-description",
        candidate_envelope_id="envelope:tool-description",
        created_at=datetime(2026, 9, 18, tzinfo=timezone.utc),
    )
    return cast("dict[str, Any]", adapter.execute(action).output)


# --- the description surface itself ---------------------------------------


def test_exactly_the_model_facing_tools_have_a_specific_description() -> None:
    assert set(provider_module._TOOL_DESCRIPTIONS) == set(DESCRIBED)
    for capability_id in DESCRIBED:
        description = _description(capability_id)
        assert description.strip(), capability_id
        # The regression this test exists for: falling back to the generic
        # sentence, which names the capability and says nothing about it.
        assert description != GENERIC_DESCRIPTION.format(
            capability_id=capability_id
        ), capability_id
        assert len(description) > 80, capability_id


def test_every_chat_tool_is_described() -> None:
    assert set(CHAT_CAPABILITY_IDS) <= set(DESCRIBED)


def test_capabilities_without_a_description_keep_the_generic_sentence() -> None:
    for capability_id in ("workspace.compensate_patch", "policy.revoke", "nope"):
        assert _description(capability_id) == GENERIC_DESCRIPTION.format(
            capability_id=capability_id
        )


# --- workspace.search: the payload fields the model must know about -------


def test_search_description_publishes_the_truncation_diagnostics() -> None:
    description = _description("workspace.search")
    for token in (
        "truncated_reason",
        "scan_cap",
        "result_cap",
        "output_cap",
        "scanned_files",
        "unexamined_files",
        "matches",
        "entries",
    ):
        assert token in description, token
    # The honesty rule itself: an empty match list under the scan cap is not a
    # completed negative result.
    assert "does not establish that no match exists" in description
    # The caps the description promises are the caps the adapter enforces.
    assert str(DeveloperWorkspaceAdapter._SEARCH_MAX_SCANNED_FILES) in description
    assert str(DeveloperWorkspaceAdapter._SEARCH_MAX_RESULTS) in description
    assert str(DeveloperWorkspaceAdapter._SEARCH_MAX_OUTPUT_CHARS) in description


def test_scan_cap_empty_match_list_is_the_result_the_description_warns_about(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """The warning describes a payload the adapter really produces.

    The scan cap is lowered so the case is cheap to reproduce: the needle sits
    in the fourth file, the walk stops after the second, and the report is an
    empty match list with ``truncated_reason == "scan_cap"`` -- indistinguishable
    from "no match" unless the description says the list was not exhaustive.
    """

    monkeypatch.setattr(DeveloperWorkspaceAdapter, "_SEARCH_MAX_SCANNED_FILES", 2)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for name in ("a.txt", "b.txt", "c.txt"):
        (workspace / name).write_text("filler\n", encoding="utf-8")
    (workspace / "z.txt").write_text(f"filler\n{NEEDLE}\n", encoding="utf-8")

    result = _search(
        DeveloperWorkspaceAdapter(workspace), {"mode": "grep", "pattern": NEEDLE}
    )

    assert result["matches"] == []
    assert result["truncated_reason"] == "scan_cap"
    assert result["scanned_files"] == 2
    assert result["unexamined_files"] == 2
    assert "does not establish that no match exists" in _description(
        "workspace.search"
    )


# --- every claim a description makes must match the code it restates ------


def test_descriptions_restate_the_registered_effect_class_and_risk_tier(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    specs = DeveloperWorkspaceAdapter(workspace).specs()

    for capability_id in DESCRIBED:
        spec = specs[capability_id]
        description = _description(capability_id)
        assert spec.side_effect_guarantee.value in description, capability_id
        assert f"risk tier {spec.risk_tier}" in description, capability_id

    for capability_id in CHAT_CAPABILITY_IDS:
        tier = ACTION_RISK_TIERS[capability_id]
        assert specs[capability_id].risk_tier == tier
        assert f"risk tier {tier}" in _description(capability_id), capability_id

    # Tier 3 is not auto-approvable; the description says so.
    assert "human approval" in _description("workspace.shell")

    # artifact.write has CapabilitySpec risk_tier 1 but is outside the E2
    # allowlist, where the gate denies in every mode. A description that
    # stopped at "tier 1" would promise an auto-pass the gate never gives.
    assert "artifact.write" not in ACTION_RISK_TIERS
    assert "not in the permission gate" in _description("artifact.write")


def test_read_description_matches_the_tool_result_budget_of_the_chat_loop() -> None:
    assert f"{_MAX_TOOL_RESULT_CHARS} characters" in _description("workspace.read")


# --- the descriptions must reach the wire on every transport --------------


def _provider() -> provider_module.OpenAICompatibleProvider:
    return provider_module.OpenAICompatibleProvider(
        base_url="http://127.0.0.1:1/v1",
        model="gpt-test",
        credential=CredentialRef(
            credential_ref_id="credential:tool-description",
            owner_principal_id="user:local",
            tenant_id="tenant:local",
            workspace_id="workspace:local",
            provider_id="openai-compatible",
            resolver_key="AGENT_OS_TOOL_DESCRIPTION_TEST_KEY",
            scopes=("chat",),
            status=CredentialStatus.ACTIVE,
            created_at=datetime(2026, 9, 18, tzinfo=timezone.utc),
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        ),
    )


def _request() -> ProviderRequest:
    return ProviderRequest(
        request_id="req:tool-description",
        task_id="task:tool-description",
        run_id="run:tool-description",
        provider_profile_id="provider-profile:default",
        messages=(
            ProviderMessage(role=ProviderMessageRole.USER, content="search it"),
        ),
        timeout_seconds=30,
        created_at=datetime(2026, 9, 18, tzinfo=timezone.utc),
    )


def test_openai_request_body_carries_each_chat_tool_description() -> None:
    body = _provider()._request_body(
        _request(),
        model_id="gpt-test",
        temperature=0.0,
        allowed_capability_ids=CHAT_CAPABILITY_IDS,
        stream=False,
    )
    tools = cast("list[dict[str, Any]]", body["tools"])
    by_name = {
        cast("str", tool["function"]["name"]): cast(
            "str", tool["function"]["description"]
        )
        for tool in tools
    }
    assert set(by_name) == {
        capability_id.replace(".", "__") for capability_id in CHAT_CAPABILITY_IDS
    }
    for capability_id in CHAT_CAPABILITY_IDS:
        name = capability_id.replace(".", "__")
        assert by_name[name] == _description(capability_id), name
    assert "scan_cap" in by_name["workspace__search"]


def test_anthropic_and_gemini_projections_carry_the_same_description() -> None:
    for projection in (
        provider_module._anthropic_tool,
        provider_module._gemini_tool,
    ):
        tool = projection("workspace.search")
        description = cast("str", tool["description"])
        assert "truncated_reason" in description
        assert "scan_cap" in description
