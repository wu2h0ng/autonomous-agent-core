"""MCP precondition: what the capability-horizon measurement pins.

These tests are about the *instrument and the surface*, never about model
capability. They assert three things that a later MCP decision would rest on:

- the corpus's own reference solutions demand nothing outside the surface the
  chat loop exposes (so the frozen corpus cannot show narrowness as a cause of
  failure today);
- an off-surface proposal is denied attributably by the loop and leaves no
  effect, while the same plan against an on-surface capability completes;
- the frozen projection records **no** tool call and **no** denial for that
  turn, which is why "the tool surface was too narrow" is not a number this
  eval currently produces.

If someone widens `CHAT_CAPABILITY_IDS`, or teaches the projection to count a
policy denial as a tool call, these tests fail — that is the point: the
precondition evidence must not silently become stale.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_os_core.agent_loop import CHAT_CAPABILITY_IDS

from product_evals.terminal_agent_eval.capability_horizon import (
    OFF_SURFACE_REGISTERED_PROBE,
    OFF_SURFACE_UNREGISTERED_PROBE,
    PROBE_TASK_ID,
    REFERENCE_PROBE,
    HorizonMeasurement,
    TaskObservation,
    measure_capability_horizon,
)

DENY_OUT_OF_ALLOWLIST = "out_of_allowlist"


@pytest.fixture(scope="module")
def suite_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("capability-horizon")


@pytest.fixture(scope="module")
def measurement(suite_dir: Path) -> HorizonMeasurement:
    return measure_capability_horizon(suite_dir, out_dir=suite_dir / "out")


def _observations(measurement: HorizonMeasurement, probe: str) -> list[TaskObservation]:
    return [item for item in measurement.observations if item.probe == probe]


def test_surface_and_dispatchable_sets_are_read_from_the_product(
    measurement: HorizonMeasurement,
) -> None:
    assert measurement.surface == tuple(CHAT_CAPABILITY_IDS)
    # Re-based 7 -> 8 on the child-agent frame-gates branch: ``agent.spawn`` was added to
    # CHAT_CAPABILITY_IDS (it is advertised only when AGENT_OS_CHILD_AGENTS is on; an
    # unadvertised proposal still fails closed as out_of_allowlist). The count is a tripwire,
    # so a legitimate widening is recorded here rather than left stale.
    assert len(measurement.surface) == 8
    # A registered, dispatchable capability that chat turns may not propose:
    # this is the gap the probes measure against.
    assert OFF_SURFACE_REGISTERED_PROBE in measurement.dispatchable
    assert OFF_SURFACE_REGISTERED_PROBE in measurement.registered_but_not_exposed
    assert "workspace.apply_patch" in measurement.surface
    assert "workspace.apply_patch" in measurement.dispatchable
    # The probe id is a name, never a capability: nothing MCP-shaped is registered.
    assert OFF_SURFACE_UNREGISTERED_PROBE not in measurement.dispatchable


def test_frozen_corpus_demand_is_closed_inside_the_chat_surface(
    measurement: HorizonMeasurement,
) -> None:
    """The finding: 0 of the frozen tasks need anything outside the surface."""
    assert measurement.reference_matches_frozen_expectation is True, (
        "the measurement's own bootstrap no longer reproduces the frozen "
        "reference arm; its probe results cannot be trusted: "
        f"{measurement.reference_calibration_violations}"
    )
    assert measurement.corpus_task_count == 6
    assert measurement.corpus_tasks_demanding_off_surface == 0

    reference = _observations(measurement, REFERENCE_PROBE)
    assert len(reference) == 6
    for observation in reference:
        assert observation.proposed_capability_ids, (
            f"{observation.task_id}: the reference solution proposed nothing"
        )
        assert observation.off_surface_proposals == ()
        assert all(
            capability_id in measurement.surface
            for capability_id in observation.proposed_capability_ids
        )
        assert observation.completed is True
        assert observation.policy_denials == ()


def test_on_surface_control_lands_its_effect(measurement: HorizonMeasurement) -> None:
    """The control the off-surface probes are contrasted with."""
    control = _observations(measurement, "surface-control")
    assert len(control) == 1
    assert control[0].task_id == PROBE_TASK_ID
    assert control[0].completed is True
    assert control[0].tool_calls == 1
    assert control[0].stop_reason == "completed"
    assert control[0].workspace_paths_changed == ("answer.txt",)


@pytest.mark.parametrize(
    "probe",
    [
        f"off-surface-registered:{OFF_SURFACE_REGISTERED_PROBE}",
        f"off-surface-unregistered:{OFF_SURFACE_UNREGISTERED_PROBE}",
    ],
)
def test_off_surface_proposal_is_denied_and_leaves_no_effect(
    measurement: HorizonMeasurement, probe: str
) -> None:
    observations = _observations(measurement, probe)
    assert len(observations) == 1
    observation = observations[0]
    capability_id = probe.rsplit(":", 1)[1]

    # Attributable: the denial names the capability and its basis.
    assert observation.policy_denials == ((capability_id, DENY_OUT_OF_ALLOWLIST),)
    assert observation.stop_reason == "unauthorized_proposal"
    # No effect: the same plan against an on-surface capability completes the
    # task, so the surface — not the plan — is what failed it.
    assert observation.completed is False
    assert observation.workspace_paths_changed == ()


def test_frozen_projection_cannot_attribute_a_horizon_denial(
    measurement: HorizonMeasurement,
) -> None:
    """The measurement gap the evidence note names.

    A turn that proposed a capability outside the surface is recorded on the
    durable stream, yet the frozen projection shows `tool_calls = 0` (it counts
    ACTION_PROPOSED) and `denials = 0` (it counts rejected APPROVAL_RECORDED).
    "The agent failed because a capability was absent" is therefore
    indistinguishable in the report from "the agent proposed nothing".
    """
    for probe in (
        f"off-surface-registered:{OFF_SURFACE_REGISTERED_PROBE}",
        f"off-surface-unregistered:{OFF_SURFACE_UNREGISTERED_PROBE}",
    ):
        observation = _observations(measurement, probe)[0]
        assert observation.proposed_capability_ids == ()
        assert observation.tool_calls == 0
        assert observation.denials == 0
        assert observation.policy_denials, (
            "the denial must still exist on the durable stream, or the "
            "instrument would be blind rather than merely unprojected"
        )


def test_measurement_writes_its_artifacts(
    suite_dir: Path, measurement: HorizonMeasurement
) -> None:
    out = suite_dir / "out"
    payload = json.loads((out / "capability-horizon.json").read_text("utf-8"))
    assert payload["suite"] == measurement.suite
    assert payload["corpus_tasks_demanding_off_surface"] == 0
    rendered = (out / "capability-horizon.md").read_text("utf-8")
    assert "0 demanding a capability outside the surface" in rendered
    assert "not a capability result" in rendered
