from __future__ import annotations

import hashlib
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_os_contracts import (
    BoundedOption,
    HelpBudget,
    HelpClass,
    KnownFact,
    SrlHelpRequest,
)

from tests.research.r_srl_1.harness import (
    ArmBudget,
    ArmEnvelope,
    ArmRole,
    BudgetEntry,
    BudgetExceeded,
    FrozenUnit,
    RestartState,
    RsrlEventGateway,
    SRL_INTERNAL_TYPE_NAMES,
    load_frozen_unit,
    verify_manifest,
)
from tests.research.r_srl_1.outcome_evaluator import RsrlOutcomeEvaluator
from tests.research.r_srl_1.scorer import (
    OutcomeVerdict,
    RsrlHiddenEvaluator,
    load_expected_outcomes,
)


@pytest.fixture
def u00_dir() -> Path:
    return Path(__file__).with_suffix("").parent / "fixtures" / "u00"


@pytest.fixture
def u00_unit(u00_dir: Path) -> FrozenUnit:
    return load_frozen_unit(u00_dir)


@pytest.fixture
def gateway(u00_dir: Path) -> RsrlEventGateway:
    budget = ArmBudget(
        max_llm_calls=100,
        max_input_tokens=1_000_000,
        max_output_tokens=500_000,
        max_retries=50,
        max_tool_invocations=1_000,
        max_wall_seconds=3600.0,
    )
    return RsrlEventGateway(
        u00_dir.parent,
        arm_budgets={
            "arm1": budget,
            "arm2": budget,
            "arm3": budget,
            "arm4": budget,
        },
    )


@pytest.fixture
def sample_help_request() -> SrlHelpRequest:
    now = datetime(2026, 7, 16, 12, 0, 10, tzinfo=timezone.utc)
    return SrlHelpRequest(
        help_request_id="help-u00-01",
        mandate_id="mandate-u00",
        standing_mission_id="mission-u00",
        help_class=HelpClass.PERMISSION,
        known_facts=(
            KnownFact(
                assertion="event-08 requires irreducible human judgment",
                provenance_ref="harness:expected_outcomes:event-08",
                confidence=1.0,
            ),
        ),
        unknowns=("what action the operator authorizes",),
        unsafe_boundary="any autonomous change to production semantics",
        bounded_options=(
            BoundedOption(
                option_id="opt-a",
                label="Proceed with conservative fix",
                expected_impact="resolves event-08 without expanding authority",
            ),
        ),
        minimum_answer="operator approves option A or provides alternative",
        expires_at=now + timedelta(minutes=5),
        requested_at=now,
        cancellation_policy="operator may cancel by explicit revocation",
        escalation_policy="escalate to mandate steward if expiry passes",
    )


def test_load_frozen_unit_u00(u00_unit: FrozenUnit) -> None:
    assert u00_unit.unit_id == "r-srl-1-u00"
    assert u00_unit.repository_lineage == "canonical-python-lib-00"
    assert u00_unit.arm_budget_seconds == 1800
    assert u00_unit.build_commands == (("python", "-m", "compileall", "."),)
    assert set(u00_unit.manifest.keys()) == {
        "snapshot.yaml",
        "mission.yaml",
        "events.yaml",
        "expected_outcomes.yaml",
    }
    assert u00_unit.events_path.name == "events.yaml"
    assert u00_unit.expected_outcomes_path.name == "expected_outcomes.yaml"


def test_verify_manifest_passes(u00_unit: FrozenUnit) -> None:
    assert verify_manifest(u00_unit) is True


def test_verify_manifest_fails_on_tampered_file(
    u00_unit: FrozenUnit, tmp_path: Path
) -> None:
    tampered_dir = tmp_path / "tampered-u00"
    tampered_dir.mkdir()
    for path in (
        u00_unit.snapshot_path,
        u00_unit.mission_path,
        u00_unit.events_path,
        u00_unit.expected_outcomes_path,
    ):
        dest = tampered_dir / path.name
        dest.write_bytes(path.read_bytes())

    # Corrupt one file.
    (tampered_dir / "events.yaml").write_text("- corrupted: true\n", encoding="utf-8")

    tampered_unit = FrozenUnit(
        unit_id=u00_unit.unit_id,
        repository_lineage=u00_unit.repository_lineage,
        arm_budget_seconds=u00_unit.arm_budget_seconds,
        manifest=u00_unit.manifest,
        build_commands=u00_unit.build_commands,
        snapshot_path=tampered_dir / "snapshot.yaml",
        mission_path=tampered_dir / "mission.yaml",
        events_path=tampered_dir / "events.yaml",
        expected_outcomes_path=tampered_dir / "expected_outcomes.yaml",
    )
    with pytest.raises(ValueError, match="manifest mismatch"):
        verify_manifest(tampered_unit)


def test_event_gateway_init_verifies_manifest(u00_dir: Path, tmp_path: Path) -> None:
    units_root = tmp_path / "units"
    copied_unit = units_root / "u00"
    shutil.copytree(u00_dir, copied_unit)
    (copied_unit / "events.yaml").write_text("- corrupted: true\n", encoding="utf-8")

    with pytest.raises(ValueError, match="manifest mismatch"):
        RsrlEventGateway(units_root)


def test_event_gateway_rejects_hidden_scorer_semantics_in_event_class(
    u00_dir: Path, tmp_path: Path
) -> None:
    units_root = tmp_path / "units"
    copied_unit = units_root / "u00"
    shutil.copytree(u00_dir, copied_unit)

    events_path = copied_unit / "events.yaml"
    events = yaml.safe_load(events_path.read_text(encoding="utf-8"))
    events[0]["event_class"] = "DECOY"
    events_path.write_text(yaml.safe_dump(events, sort_keys=False), encoding="utf-8")

    digest = hashlib.sha256(events_path.read_bytes()).hexdigest()
    unit_path = copied_unit / "unit.yaml"
    unit_doc = yaml.safe_load(unit_path.read_text(encoding="utf-8"))
    unit_doc["manifest"]["events.yaml"] = f"sha256:{digest}"
    unit_path.write_text(yaml.safe_dump(unit_doc, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="event_class leaks hidden scorer semantics"):
        RsrlEventGateway(units_root)


def test_event_gateway_lists_events(gateway: RsrlEventGateway) -> None:
    events = gateway.list_events("arm1", "r-srl-1-u00")
    assert len(events) == 9
    event_ids = [e.event_id for e in events]
    assert event_ids == [f"event-{i:02d}" for i in range(1, 10)]
    # All arms see the same ledger.
    assert gateway.list_events("arm2", "r-srl-1-u00") == events


def test_event_gateway_rejects_expected_outcomes_access(
    gateway: RsrlEventGateway,
) -> None:
    with pytest.raises(PermissionError):
        gateway.read_repository("arm1", "r-srl-1-u00", "expected_outcomes.yaml")

    with pytest.raises(PermissionError):
        gateway.read_repository("arm1", "r-srl-1-u00", "../expected_outcomes.yaml")

    with pytest.raises(PermissionError):
        gateway.read_repository("arm1", "r-srl-1-u00", "sub/expected_outcomes.yaml")


def test_event_gateway_isolates_arm_logs(
    gateway: RsrlEventGateway, sample_help_request: SrlHelpRequest
) -> None:
    gateway.record_action(
        "arm1", "r-srl-1-u00", {"kind": "test", "event_id": "event-01"}
    )
    gateway.record_action(
        "arm2", "r-srl-1-u00", {"kind": "heuristic", "event_id": "event-02"}
    )
    gateway.emit_help_request("arm1", "r-srl-1-u00", sample_help_request)

    arm1_summary = gateway.finalize_unit("arm1", "r-srl-1-u00")
    arm2_summary = gateway.finalize_unit("arm2", "r-srl-1-u00")

    assert arm1_summary["action_count"] == 1
    assert arm1_summary["help_request_count"] == 1
    assert arm2_summary["action_count"] == 1
    assert arm2_summary["help_request_count"] == 0

    # Arm 2 cannot read arm 1's action log through repository access.
    with pytest.raises(PermissionError):
        gateway.read_repository("arm2", "r-srl-1-u00", "_logs/arm1/actions.jsonl")


def test_event_gateway_run_tests_produces_test_reports(
    gateway: RsrlEventGateway,
) -> None:
    passing = gateway.run_tests("arm1", "r-srl-1-u00", "tests/test_lib.py::test_passes")
    assert passing.exit_code == 0
    assert len(passing.reports) == 1
    assert passing.reports[0].passed is True
    assert passing.reports[0].test_path == "tests/test_lib.py::test_passes"
    assert passing.reports[0].artifact_ref == "report:tests/test_lib.py::test_passes"

    failing = gateway.run_tests("arm1", "r-srl-1-u00", "tests/test_lib.py::test_fails")
    assert failing.exit_code != 0
    assert len(failing.reports) == 1
    assert failing.reports[0].passed is False

    artifact = gateway.finalize_unit("arm1", "r-srl-1-u00")
    assert len(artifact["test_reports"]) == 2
    by_path = {r["test_path"]: r for r in artifact["test_reports"]}
    assert by_path["tests/test_lib.py::test_passes"]["passed"] is True
    assert by_path["tests/test_lib.py::test_fails"]["passed"] is False
    assert all(
        "artifact_ref" in r and r["artifact_ref"] for r in artifact["test_reports"]
    )


@pytest.mark.parametrize("selector", ["--co", "../expected_outcomes.yaml"])
def test_event_gateway_run_tests_rejects_selector_escape(
    gateway: RsrlEventGateway, selector: str
) -> None:
    with pytest.raises(PermissionError):
        gateway.run_tests("arm1", "r-srl-1-u00", selector)


def test_event_gateway_run_tests_uses_destroyed_clean_arm_workdirs(
    gateway: RsrlEventGateway, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed_cwds: list[Path] = []

    def fake_run(
        cmd: list[str],
        cwd: Path,
        capture_output: bool,
        text: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        del cmd, capture_output, text, timeout
        repo_cwd = Path(cwd)
        observed_cwds.append(repo_cwd)
        assert not (repo_cwd / ".pytest_cache").exists()
        assert not (repo_cwd / "tests" / "__pycache__").exists()
        (repo_cwd / ".pytest_cache").mkdir()
        (repo_cwd / "tests" / "__pycache__").mkdir()
        return subprocess.CompletedProcess(
            args=["pytest"],
            returncode=0,
            stdout="passed",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    arm1 = gateway.run_tests(
        "arm1", "r-srl-1-u00", "tests/test_lib.py::test_passes"
    )
    arm2 = gateway.run_tests(
        "arm2", "r-srl-1-u00", "tests/test_lib.py::test_passes"
    )

    assert arm1.exit_code == 0
    assert arm2.exit_code == 0
    assert len(observed_cwds) == 2
    assert observed_cwds[0] != observed_cwds[1]
    assert all(not cwd.exists() for cwd in observed_cwds)


def test_event_gateway_run_build_records_result(gateway: RsrlEventGateway) -> None:
    result = gateway.run_build("arm1", "r-srl-1-u00")
    assert isinstance(result.exit_code, int)
    assert result.exit_code == 0

    artifact = gateway.finalize_unit("arm1", "r-srl-1-u00")
    assert len(artifact["build_results"]) == 1
    assert artifact["build_results"][0]["exit_code"] == 0
    assert artifact["build_results"][0]["artifact_ref"]


def test_event_gateway_run_build_rejects_non_allowlisted_command(
    gateway: RsrlEventGateway,
) -> None:
    with pytest.raises(PermissionError):
        gateway.run_build(
            "arm1",
            "r-srl-1-u00",
            ["cat", "../expected_outcomes.yaml"],
        )
    summary = gateway.get_budget_summary("arm1", "r-srl-1-u00")
    assert summary["used"]["tool_invocations"] == 0
    assert summary["used"]["input_tokens"] == 0


def test_build_scorer_artifact_produces_event_keyed_scoring_inputs(
    gateway: RsrlEventGateway, sample_help_request: SrlHelpRequest
) -> None:
    gateway.record_action(
        "arm3",
        "r-srl-1-u00",
        {
            "kind": "interface_call",
            "event_id": "event-02",
            "payload": {"call": "lib.transform(items, strict=True)"},
        },
    )
    gateway.emit_help_request(
        "arm3",
        "r-srl-1-u00",
        sample_help_request,
        event_id="event-08",
    )
    gateway.record_restart_comparison(
        "arm3",
        "r-srl-1-u00",
        "event-04",
        {"equivalent": True, "differences": []},
    )
    gateway.run_tests("arm3", "r-srl-1-u00", "tests/test_lib.py::test_passes")

    artifact = gateway.build_scorer_artifact("arm3", "r-srl-1-u00")

    assert artifact["actions"]["event-02"][0]["kind"] == "interface_call"
    assert artifact["help_requests"]["event-08"][0]["help_request_id"] == "help-u00-01"
    assert artifact["restart_comparisons"]["event-04"]["equivalent"] is True
    assert artifact["test_reports"][0]["artifact_ref"] == (
        "report:tests/test_lib.py::test_passes"
    )
    assert "interface:event-02:matched_call" in artifact["artifact_bundle"]
    assert "interface:event-02:no_forbidden_call" in artifact["artifact_bundle"]
    assert "help:event-08:request" in artifact["artifact_bundle"]
    assert "restart:event-04:comparison" in artifact["artifact_bundle"]
    assert "report:tests/test_lib.py::test_passes" in artifact["artifact_bundle"]
    assert "decoy:no_work_spawned" in artifact["artifact_bundle"]


def test_gateway_scorer_artifact_survives_hidden_scorer_and_doe_validation(
    gateway: RsrlEventGateway, u00_unit: FrozenUnit
) -> None:
    gateway.record_action(
        "arm3",
        "r-srl-1-u00",
        {
            "kind": "interface_call",
            "event_id": "event-02",
            "payload": {"call": "lib.transform(items, strict=True)"},
        },
    )
    artifact = gateway.build_scorer_artifact("arm3", "r-srl-1-u00")

    hidden = RsrlHiddenEvaluator()
    validator = RsrlOutcomeEvaluator()
    expected = load_expected_outcomes(u00_unit.expected_outcomes_path)["event-02"]
    draft = hidden.evaluate(u00_unit, artifact)["event-02"]
    validated = validator.validate(expected, draft, artifact)

    assert draft.verdict is OutcomeVerdict.VERIFIED
    assert validated.verdict is OutcomeVerdict.VERIFIED
    assert validated.gaps == ()


def test_budget_ledger_tracks_llm_calls(gateway: RsrlEventGateway) -> None:
    gateway.charge("arm1", "r-srl-1-u00", BudgetEntry.llm_call())
    gateway.charge("arm1", "r-srl-1-u00", BudgetEntry.llm_call(2))
    gateway.charge("arm1", "r-srl-1-u00", BudgetEntry.input_tokens(150))
    gateway.charge("arm1", "r-srl-1-u00", BudgetEntry.output_tokens(75))

    summary = gateway.get_budget_summary("arm1", "r-srl-1-u00")
    assert summary["used"]["llm_calls"] == 3
    assert summary["used"]["input_tokens"] == 150
    assert summary["used"]["output_tokens"] == 75
    assert summary["remaining"]["llm_calls"] == 97


def test_budget_ledger_raises_on_exceeded_calls(gateway: RsrlEventGateway) -> None:
    tight_budget = ArmBudget(
        max_llm_calls=2,
        max_input_tokens=10,
        max_output_tokens=10,
        max_retries=10,
        max_tool_invocations=10,
        max_wall_seconds=3600.0,
    )
    tight_gateway = RsrlEventGateway(
        gateway.units_root,
        arm_budgets={"arm1": tight_budget},
    )
    tight_gateway.charge("arm1", "r-srl-1-u00", BudgetEntry.llm_call())
    tight_gateway.charge("arm1", "r-srl-1-u00", BudgetEntry.llm_call())
    with pytest.raises(BudgetExceeded):
        tight_gateway.charge("arm1", "r-srl-1-u00", BudgetEntry.llm_call())


def test_event_gateway_rejects_unequal_four_arm_budgets(
    gateway: RsrlEventGateway,
) -> None:
    matched = ArmBudget(
        max_llm_calls=100,
        max_input_tokens=1_000_000,
        max_output_tokens=500_000,
        max_retries=50,
        max_tool_invocations=1_000,
        max_wall_seconds=3600.0,
    )
    unequal = ArmBudget(
        max_llm_calls=101,
        max_input_tokens=1_000_000,
        max_output_tokens=500_000,
        max_retries=50,
        max_tool_invocations=1_000,
        max_wall_seconds=3600.0,
    )

    with pytest.raises(ValueError, match="identical across arm1-arm4"):
        RsrlEventGateway(
            gateway.units_root,
            arm_budgets={
                "arm1": matched,
                "arm2": matched,
                "arm3": unequal,
                "arm4": matched,
            },
        )


def test_event_gateway_rejects_partial_multi_arm_budget_config(
    gateway: RsrlEventGateway,
) -> None:
    budget = ArmBudget(
        max_llm_calls=100,
        max_input_tokens=1_000_000,
        max_output_tokens=500_000,
        max_retries=50,
        max_tool_invocations=1_000,
        max_wall_seconds=3600.0,
    )

    with pytest.raises(ValueError, match="exactly arm1-arm4"):
        RsrlEventGateway(
            gateway.units_root,
            arm_budgets={
                "arm1": budget,
                "arm2": budget,
            },
        )


def test_budget_ledger_tracks_wall_time(gateway: RsrlEventGateway) -> None:
    gateway.charge("arm1", "r-srl-1-u00", BudgetEntry.wall_seconds(1.5))
    gateway.charge("arm1", "r-srl-1-u00", BudgetEntry.wall_seconds(0.5))

    summary = gateway.get_budget_summary("arm1", "r-srl-1-u00")
    assert summary["used"]["wall_seconds"] == 2.0
    assert summary["remaining"]["wall_seconds"] == 3598.0


# ---------------------------------------------------------------------------
# P0-3 baseline arm envelope
# ---------------------------------------------------------------------------


def test_default_arm_envelopes(gateway: RsrlEventGateway) -> None:
    assert gateway._arm_envelopes["arm1"].role == ArmRole.BASELINE_SCHEDULED
    assert gateway._arm_envelopes["arm2"].role == ArmRole.BASELINE_USER_DRIVEN
    assert gateway._arm_envelopes["arm3"].role == ArmRole.SRL
    assert gateway._arm_envelopes["arm4"].role == ArmRole.ABLATION_PERSISTENT_STATE

    for arm_id in ("arm1", "arm2", "arm4"):
        envelope = gateway._arm_envelopes[arm_id]
        assert not envelope.can_use_srl_structures
        assert envelope.allowed_srl_type_names == set()

    srl_envelope = gateway._arm_envelopes["arm3"]
    assert srl_envelope.can_use_srl_structures
    assert srl_envelope.allowed_srl_type_names == set(SRL_INTERNAL_TYPE_NAMES)


def test_arm3_can_record_srl_action(gateway: RsrlEventGateway) -> None:
    action = {"SrlRelevanceAssessment": {"event_id": "event-01", "score": 0.9}}
    gateway.record_action("arm3", "r-srl-1-u00", action)
    summary = gateway.finalize_unit("arm3", "r-srl-1-u00")
    assert summary["action_count"] == 1


@pytest.mark.parametrize("arm_id", ["arm1", "arm2", "arm4"])
def test_baseline_cannot_record_srl_action(
    gateway: RsrlEventGateway, arm_id: str
) -> None:
    action = {"SrlRelevanceAssessment": {"event_id": "event-01", "score": 0.9}}
    with pytest.raises(PermissionError):
        gateway.record_action(arm_id, "r-srl-1-u00", action)


@pytest.mark.parametrize("arm_id", ["arm1", "arm2", "arm4"])
def test_baseline_can_record_plain_action(
    gateway: RsrlEventGateway, arm_id: str
) -> None:
    action = {"kind": "plain", "event_id": "event-01"}
    gateway.record_action(arm_id, "r-srl-1-u00", action)
    summary = gateway.finalize_unit(arm_id, "r-srl-1-u00")
    assert summary["action_count"] == 1


@pytest.mark.parametrize("arm_id", ["arm1", "arm2", "arm4"])
def test_baseline_can_emit_plain_help_request(
    gateway: RsrlEventGateway, arm_id: str, sample_help_request: SrlHelpRequest
) -> None:
    # The SrlHelpRequest type itself is the envelope-level message baseline arms
    # may emit; only SRL-internal type names embedded inside the payload are
    # rejected by the scanner.
    gateway.emit_help_request(arm_id, "r-srl-1-u00", sample_help_request)
    summary = gateway.finalize_unit(arm_id, "r-srl-1-u00")
    assert summary["help_request_count"] == 1


def test_gateway_rejects_unconfigured_arm_envelope(
    gateway: RsrlEventGateway,
) -> None:
    custom_gateway = RsrlEventGateway(
        gateway.units_root,
        arm_envelopes={"armX": ArmEnvelope(role=ArmRole.SRL)},
    )
    with pytest.raises(ValueError, match="no arm envelope configured"):
        custom_gateway.record_action("armY", "r-srl-1-u00", {"kind": "plain"})


# ---------------------------------------------------------------------------
# P1-2 help burden ledger
# ---------------------------------------------------------------------------


def _make_request(
    base: SrlHelpRequest,
    help_request_id: str,
    requested_at: datetime,
    unknowns: tuple[str, ...] | None = None,
) -> SrlHelpRequest:
    """Return a copy of ``base`` with the given identity and timestamp."""
    updates: dict[str, Any] = {
        "help_request_id": help_request_id,
        "requested_at": requested_at,
        "expires_at": requested_at + timedelta(minutes=5),
    }
    if unknowns is not None:
        updates["unknowns"] = unknowns
    return base.model_copy(update=updates)


@pytest.fixture
def help_gateway(gateway: RsrlEventGateway) -> RsrlEventGateway:
    """Gateway configured with a tight help budget for burden testing."""
    return RsrlEventGateway(
        gateway.units_root,
        help_budget=HelpBudget(
            max_requests_per_window=10,
            max_operator_minutes_per_window=10,
            max_repeated_question_rate=1.0,
            max_unresolved_wait_seconds=3600,
            window_seconds=300,
        ),
    )


def test_help_burden_receipt_fields(
    help_gateway: RsrlEventGateway,
    sample_help_request: SrlHelpRequest,
) -> None:
    t0 = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
    req1 = _make_request(sample_help_request, "help-01", t0, unknowns=("question-a",))
    req2 = _make_request(
        sample_help_request,
        "help-02",
        t0 + timedelta(seconds=10),
        unknowns=("question-b",),
    )

    help_gateway.emit_help_request("arm3", "r-srl-1-u00", req1, 2)
    help_gateway.emit_help_request("arm3", "r-srl-1-u00", req2, 3)

    receipt = help_gateway.get_help_burden_receipt(
        "arm3",
        "r-srl-1-u00",
        window_index=0,
        receipt_id="receipt-01",
        mandate_id="mandate-u00",
        window_start=t0,
        window_end=t0 + timedelta(seconds=60),
    )

    assert receipt.request_count == 2
    assert receipt.operator_minutes == 5
    assert receipt.repeated_question_rate == 0.0
    assert receipt.longest_unresolved_wait_seconds == 60
    assert receipt.status == "WITHIN_BUDGET"
    assert receipt.receipt_id == "receipt-01"
    assert receipt.mandate_id == "mandate-u00"


def test_help_burden_exceeds_request_count(
    gateway: RsrlEventGateway,
    sample_help_request: SrlHelpRequest,
) -> None:
    tight = RsrlEventGateway(
        gateway.units_root,
        help_budget=HelpBudget(
            max_requests_per_window=2,
            max_operator_minutes_per_window=10,
            max_repeated_question_rate=1.0,
            max_unresolved_wait_seconds=3600,
            window_seconds=300,
        ),
    )
    t0 = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(3):
        req = _make_request(
            sample_help_request,
            f"help-{i}",
            t0 + timedelta(seconds=i),
            unknowns=(f"question-{i}",),
        )
        tight.emit_help_request("arm3", "r-srl-1-u00", req)

    receipt = tight.get_help_burden_receipt(
        "arm3",
        "r-srl-1-u00",
        window_index=0,
        receipt_id="receipt-01",
        mandate_id="mandate-u00",
        window_start=t0,
        window_end=t0 + timedelta(minutes=5),
    )

    assert receipt.request_count == 3
    assert receipt.status == "EXCEEDED"


def test_help_burden_exceeds_operator_minutes(
    gateway: RsrlEventGateway,
    sample_help_request: SrlHelpRequest,
) -> None:
    tight = RsrlEventGateway(
        gateway.units_root,
        help_budget=HelpBudget(
            max_requests_per_window=10,
            max_operator_minutes_per_window=3,
            max_repeated_question_rate=1.0,
            max_unresolved_wait_seconds=3600,
            window_seconds=300,
        ),
    )
    t0 = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
    for i, minutes in enumerate([2, 2]):
        req = _make_request(
            sample_help_request,
            f"help-{i}",
            t0 + timedelta(seconds=i),
            unknowns=(f"question-{i}",),
        )
        tight.emit_help_request(
            "arm3", "r-srl-1-u00", req, operator_minutes_estimate=minutes
        )

    receipt = tight.get_help_burden_receipt(
        "arm3",
        "r-srl-1-u00",
        window_index=0,
        receipt_id="receipt-01",
        mandate_id="mandate-u00",
        window_start=t0,
        window_end=t0 + timedelta(minutes=5),
    )

    assert receipt.operator_minutes == 4
    assert receipt.status == "EXCEEDED"


def test_help_burden_repeated_question_rate(
    help_gateway: RsrlEventGateway,
    sample_help_request: SrlHelpRequest,
) -> None:
    budget = HelpBudget(
        max_requests_per_window=10,
        max_operator_minutes_per_window=10,
        max_repeated_question_rate=0.5,
        max_unresolved_wait_seconds=3600,
        window_seconds=300,
    )
    gateway = RsrlEventGateway(
        help_gateway.units_root,
        help_budget=budget,
    )
    t0 = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
    unknowns_sequence = [
        ("shared-question",),
        ("shared-question",),
        ("unique-question",),
    ]
    for i, unknowns in enumerate(unknowns_sequence):
        req = _make_request(
            sample_help_request,
            f"help-{i}",
            t0 + timedelta(seconds=i),
            unknowns=unknowns,
        )
        gateway.emit_help_request("arm3", "r-srl-1-u00", req)

    receipt = gateway.get_help_burden_receipt(
        "arm3",
        "r-srl-1-u00",
        window_index=0,
        receipt_id="receipt-01",
        mandate_id="mandate-u00",
        window_start=t0,
        window_end=t0 + timedelta(minutes=5),
    )

    assert receipt.request_count == 3
    assert receipt.repeated_question_rate == pytest.approx(1 / 3)
    assert receipt.status == "WITHIN_BUDGET"


def test_help_burden_unresolved_wait(
    gateway: RsrlEventGateway,
    sample_help_request: SrlHelpRequest,
) -> None:
    tight = RsrlEventGateway(
        gateway.units_root,
        help_budget=HelpBudget(
            max_requests_per_window=10,
            max_operator_minutes_per_window=10,
            max_repeated_question_rate=1.0,
            max_unresolved_wait_seconds=30,
            window_seconds=300,
        ),
    )
    t0 = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
    req = _make_request(sample_help_request, "help-01", t0, unknowns=("question-a",))
    tight.emit_help_request("arm3", "r-srl-1-u00", req)

    receipt = tight.get_help_burden_receipt(
        "arm3",
        "r-srl-1-u00",
        window_index=0,
        receipt_id="receipt-01",
        mandate_id="mandate-u00",
        window_start=t0,
        window_end=t0 + timedelta(seconds=50),
    )

    assert receipt.longest_unresolved_wait_seconds == 50
    assert receipt.status == "EXCEEDED"


def test_help_burden_resolution_reduces_wait(
    help_gateway: RsrlEventGateway,
    sample_help_request: SrlHelpRequest,
) -> None:
    t0 = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
    req = _make_request(sample_help_request, "help-01", t0, unknowns=("question-a",))
    help_gateway.emit_help_request("arm3", "r-srl-1-u00", req)

    unresolved_receipt = help_gateway.get_help_burden_receipt(
        "arm3",
        "r-srl-1-u00",
        window_index=0,
        receipt_id="receipt-01",
        mandate_id="mandate-u00",
        window_start=t0,
        window_end=t0 + timedelta(seconds=60),
    )
    assert unresolved_receipt.longest_unresolved_wait_seconds == 60

    help_gateway.resolve_help_request(
        "arm3", "r-srl-1-u00", "help-01", t0 + timedelta(seconds=15)
    )

    resolved_receipt = help_gateway.get_help_burden_receipt(
        "arm3",
        "r-srl-1-u00",
        window_index=0,
        receipt_id="receipt-02",
        mandate_id="mandate-u00",
        window_start=t0,
        window_end=t0 + timedelta(seconds=60),
    )
    assert resolved_receipt.longest_unresolved_wait_seconds == 15


def test_help_burden_no_budget_returns_minimal_receipt(
    gateway: RsrlEventGateway,
) -> None:
    t0 = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)
    receipt = gateway.get_help_burden_receipt(
        "arm3",
        "r-srl-1-u00",
        window_index=0,
        receipt_id="receipt-01",
        mandate_id="mandate-u00",
        window_start=t0,
        window_end=t0 + timedelta(minutes=5),
    )

    assert receipt.request_count == 0
    assert receipt.operator_minutes == 0
    assert receipt.repeated_question_rate == 0.0
    assert receipt.longest_unresolved_wait_seconds == 0
    assert receipt.status == "WITHIN_BUDGET"


# ---------------------------------------------------------------------------
# P1-5 restart state comparator
# ---------------------------------------------------------------------------


def test_export_state_consistent(gateway: RsrlEventGateway) -> None:
    state1 = gateway.export_state("arm3", "r-srl-1-u00")
    state2 = gateway.export_state("arm3", "r-srl-1-u00")
    assert state1 == state2


def test_export_state_reflects_actions_and_help_requests(
    gateway: RsrlEventGateway, sample_help_request: SrlHelpRequest
) -> None:
    pre_state = gateway.export_state("arm3", "r-srl-1-u00")
    gateway.record_action(
        "arm3",
        "r-srl-1-u00",
        {"kind": "goal", "goal": "fix-event-01", "event_id": "event-01"},
    )
    gateway.emit_help_request("arm3", "r-srl-1-u00", sample_help_request)
    post_state = gateway.export_state("arm3", "r-srl-1-u00")

    assert pre_state != post_state
    assert pre_state.active_goals == ()
    assert post_state.active_goals == ("fix-event-01",)
    assert post_state.pending_help_request_ids == (sample_help_request.help_request_id,)
    assert len(post_state.pending_help_request_expiry) == 1
    assert post_state.pending_help_request_expiry[0].endswith("+00:00")
    assert len(post_state.belief_checksums) == 1


def test_compare_state_equivalent(gateway: RsrlEventGateway) -> None:
    state = RestartState(
        commitment_portfolio_digest="d1",
        active_goals=("g1",),
        pending_help_request_ids=("h1",),
        pending_help_request_expiry=("2026-07-16T12:05:00+00:00",),
        belief_checksums=("b1",),
    )
    result = gateway.compare_state(state, state)
    assert result["equivalent"] is True
    assert result["differences"] == []


def test_compare_state_detects_goal_difference(gateway: RsrlEventGateway) -> None:
    pre = RestartState(
        commitment_portfolio_digest="d1",
        active_goals=("g1",),
        pending_help_request_ids=(),
        pending_help_request_expiry=(),
        belief_checksums=(),
    )
    post = RestartState(
        commitment_portfolio_digest="d1",
        active_goals=("g2",),
        pending_help_request_ids=(),
        pending_help_request_expiry=(),
        belief_checksums=(),
    )
    result = gateway.compare_state(pre, post)
    assert result["equivalent"] is False
    assert any("active_goals" in diff for diff in result["differences"])


def test_compare_state_expected_delta(gateway: RsrlEventGateway) -> None:
    pre = RestartState(
        commitment_portfolio_digest="d1",
        active_goals=("g1",),
        pending_help_request_ids=("h1",),
        pending_help_request_expiry=("2026-07-16T12:05:00+00:00",),
        belief_checksums=("b1",),
    )
    post = RestartState(
        commitment_portfolio_digest="d1",
        active_goals=("g1",),
        pending_help_request_ids=("h1", "h2"),
        pending_help_request_expiry=(
            "2026-07-16T12:05:00+00:00",
            "2026-07-16T12:10:00+00:00",
        ),
        belief_checksums=("b1", "b2"),
    )
    delta = {
        "pending_help_request_ids": ("h2",),
        "pending_help_request_expiry": ("2026-07-16T12:10:00+00:00",),
        "belief_checksums": ("b2",),
    }
    result = gateway.compare_state(pre, post, delta)
    assert result["equivalent"] is True
    assert result["differences"] == []


# ---------------------------------------------------------------------------
# P1-6 real-time wall-clock budget enforcement
# ---------------------------------------------------------------------------


def _tight_wall_clock_gateway(
    units_root: Path, max_wall_seconds: float
) -> RsrlEventGateway:
    budget = ArmBudget(
        max_llm_calls=100,
        max_input_tokens=1_000_000,
        max_output_tokens=500_000,
        max_retries=50,
        max_tool_invocations=1_000,
        max_wall_seconds=max_wall_seconds,
    )
    return RsrlEventGateway(units_root, arm_budgets={"arm1": budget})


def test_wall_clock_budget_exceeded_on_charge(
    monkeypatch: pytest.MonkeyPatch, u00_dir: Path
) -> None:
    gateway = _tight_wall_clock_gateway(u00_dir.parent, max_wall_seconds=10.0)
    monkeypatch.setattr("tests.research.r_srl_1.harness.time.monotonic", lambda: 1000.0)
    gateway.charge("arm1", "r-srl-1-u00", BudgetEntry.wall_seconds(1.0))
    monkeypatch.setattr("tests.research.r_srl_1.harness.time.monotonic", lambda: 1011.0)
    with pytest.raises(BudgetExceeded):
        gateway.charge("arm1", "r-srl-1-u00", BudgetEntry.llm_call())


def test_wall_clock_budget_checked_at_method_start(
    monkeypatch: pytest.MonkeyPatch, u00_dir: Path
) -> None:
    gateway = _tight_wall_clock_gateway(u00_dir.parent, max_wall_seconds=10.0)
    monkeypatch.setattr("tests.research.r_srl_1.harness.time.monotonic", lambda: 1000.0)
    gateway.charge("arm1", "r-srl-1-u00", BudgetEntry.wall_seconds(1.0))
    monkeypatch.setattr("tests.research.r_srl_1.harness.time.monotonic", lambda: 1011.0)
    with pytest.raises(BudgetExceeded):
        gateway.list_events("arm1", "r-srl-1-u00")


def test_methods_work_within_wall_clock_budget(
    monkeypatch: pytest.MonkeyPatch, u00_dir: Path
) -> None:
    gateway = _tight_wall_clock_gateway(u00_dir.parent, max_wall_seconds=100.0)
    monkeypatch.setattr("tests.research.r_srl_1.harness.time.monotonic", lambda: 1000.0)
    events = gateway.list_events("arm1", "r-srl-1-u00")
    assert len(events) == 9
