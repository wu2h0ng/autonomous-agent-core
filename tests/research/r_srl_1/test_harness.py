from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_os_contracts import (
    BoundedOption,
    HelpClass,
    KnownFact,
    SrlHelpRequest,
)

from tests.research.r_srl_1.harness import (
    FrozenUnit,
    RsrlEventGateway,
    load_frozen_unit,
    verify_manifest,
)


@pytest.fixture
def u00_dir() -> Path:
    return Path(__file__).with_suffix("").parent / "fixtures" / "u00"


@pytest.fixture
def u00_unit(u00_dir: Path) -> FrozenUnit:
    return load_frozen_unit(u00_dir)


@pytest.fixture
def gateway(u00_dir: Path) -> RsrlEventGateway:
    return RsrlEventGateway(u00_dir.parent)


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


def test_verify_manifest_fails_on_tampered_file(u00_unit: FrozenUnit, tmp_path: Path) -> None:
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
        snapshot_path=tampered_dir / "snapshot.yaml",
        mission_path=tampered_dir / "mission.yaml",
        events_path=tampered_dir / "events.yaml",
        expected_outcomes_path=tampered_dir / "expected_outcomes.yaml",
    )
    with pytest.raises(ValueError, match="manifest mismatch"):
        verify_manifest(tampered_unit)


def test_event_gateway_lists_events(gateway: RsrlEventGateway) -> None:
    events = gateway.list_events("arm1", "r-srl-1-u00")
    assert len(events) == 9
    event_ids = [e.event_id for e in events]
    assert event_ids == [f"event-{i:02d}" for i in range(1, 10)]
    # All arms see the same ledger.
    assert gateway.list_events("arm2", "r-srl-1-u00") == events


def test_event_gateway_rejects_expected_outcomes_access(gateway: RsrlEventGateway) -> None:
    with pytest.raises(PermissionError):
        gateway.read_repository("arm1", "r-srl-1-u00", "expected_outcomes.yaml")

    with pytest.raises(PermissionError):
        gateway.read_repository("arm1", "r-srl-1-u00", "../expected_outcomes.yaml")

    with pytest.raises(PermissionError):
        gateway.read_repository("arm1", "r-srl-1-u00", "sub/expected_outcomes.yaml")


def test_event_gateway_isolates_arm_logs(
    gateway: RsrlEventGateway, sample_help_request: SrlHelpRequest
) -> None:
    gateway.record_action("arm1", "r-srl-1-u00", {"kind": "test", "event_id": "event-01"})
    gateway.record_action("arm2", "r-srl-1-u00", {"kind": "heuristic", "event_id": "event-02"})
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
