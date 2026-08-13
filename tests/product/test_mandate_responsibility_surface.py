from __future__ import annotations

import re
from pathlib import Path


INDEX_PATH = Path("apps/api_server/index.html")


def _index() -> str:
    return INDEX_PATH.read_text(encoding="utf-8")


def _responsibility_panel(page: str) -> str:
    match = re.search(
        r'<section[^>]+id="responsibility-panel"[\s\S]*?</section>',
        page,
    )
    assert match is not None
    return match.group(0)


def _responsibility_script(page: str) -> str:
    match = re.search(
        r"// Responsibility view start[\s\S]*?// Responsibility view end",
        page,
    )
    assert match is not None
    return match.group(0)


def test_surface_contains_complete_read_only_responsibility_inventory() -> None:
    page = _index()
    panel = _responsibility_panel(page)

    for required in (
        'data-testid="mandate-responsibility-panel"',
        'id="responsibility-mandate-select"',
        'id="responsibility-refresh"',
        'id="responsibility-status"',
        'id="responsibility-banner"',
        'id="responsibility-global-gaps"',
        'id="responsibility-desired-outcomes"',
        'id="responsibility-rows"',
        'id="responsibility-next-observation"',
        'id="responsibility-last-digest"',
        "Desired outcomes",
        "Global gaps",
        "Linked responsibilities",
        "Next observation",
        "Last successful digest",
        "Refresh",
    ):
        assert required in panel


def test_surface_renders_rows_reasons_banners_and_all_load_states() -> None:
    script = _responsibility_script(_index())

    for required in (
        "view.desired_outcomes",
        "view.items",
        "view.global_gaps",
        "item.attention_reasons",
        "item.link.task_id",
        "item.commitment",
        "item.expected_outcome",
        "item.current_outcome",
        "view.active_perception?.next_observation_at",
        "view.view_digest",
        "PARTIAL_UNKNOWN",
        "REVOKED",
        "Loading responsibility view",
        "No Mandates available",
        "No responsibilities linked",
        "Unable to load responsibility view",
    ):
        assert required in script


def test_surface_fetches_only_mandate_list_and_selected_read_projection() -> None:
    script = _responsibility_script(_index())

    assert "call('/v1/mandates')" in script
    assert "encodeURIComponent(mandateId)" in script
    assert "'/responsibility-view'" in script
    assert "task-links" not in script
    assert "'POST'" not in script
    assert "'PUT'" not in script
    assert "'PATCH'" not in script
    assert "'DELETE'" not in script


def test_responsibility_panel_has_no_mutating_or_authority_controls() -> None:
    panel = _responsibility_panel(_index()).lower()

    assert panel.count("<button") == 1
    for forbidden in (
        "link task",
        "revoke",
        "activate",
        "execute",
        "approve",
        "edit",
    ):
        assert forbidden not in panel


def test_selection_and_load_failure_clear_all_prior_mandate_truth() -> None:
    script = _responsibility_script(_index())
    clear = re.search(
        r"function clearResponsibilityTruth\(\) \{([\s\S]*?)\n    \}",
        script,
    )
    error = re.search(
        r"function renderResponsibilityError\(error\) \{([\s\S]*?)\n    \}",
        script,
    )
    refresh = re.search(
        r"async function refreshResponsibility\(\) \{([\s\S]*?)\n    \}",
        script,
    )
    assert clear is not None
    assert error is not None
    assert refresh is not None
    for required in (
        "responsibility-desired-outcomes",
        "responsibility-global-gaps",
        "responsibility-next-observation",
        "responsibility-last-digest",
        "responsibility-rows",
        "responsibilityState.lastDigest = null",
    ):
        assert required in clear.group(1)
    assert "clearResponsibilityTruth()" in error.group(1)
    assert refresh.group(1).index("clearResponsibilityTruth()") < refresh.group(
        1
    ).index("await call(")


def test_existing_task_workspace_surface_remains_reachable() -> None:
    page = _index()

    for required in (
        'id="task-list"',
        'id="prepare"',
        'id="run"',
        'id="review"',
        'data-tab="overview"',
        'data-tab="events"',
        'data-tab="evidence"',
        'data-tab="workflow"',
        "async function refreshTasks()",
        "async function prepareTask()",
        "async function runTask()",
        "async function reviewAction(disposition)",
        "function renderTask(task)",
        "'/v1/tasks'",
    ):
        assert required in page
