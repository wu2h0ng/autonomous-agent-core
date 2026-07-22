"""Materialize frozen fixture F2 (prereg §10) into the T2 workspace.

Appends test_selfdev_records_reject_duplicate_evidence_refs verbatim to
tests/product/test_agent_os_self_development.py. Fails loudly if the anchor
test file is missing or the fixture is already applied.
"""

from pathlib import Path
import sys

MARKER = "test_selfdev_records_reject_duplicate_evidence_refs"
FIXTURE = '''

def test_selfdev_records_reject_duplicate_evidence_refs() -> None:
    spec = SelfDevelopmentTaskSpec(
        mandate_id="META-SHADOW-MANDATE-0",
        repository_id="autonomous-agent-core",
        repository_head="0123456789abcdef",
        isolated_workspace="/tmp/agent-os-selfdev",
        isolated_branch="codex/selfdev-dup-evidence",
        target_path=AGENT_OS_TARGET,
        verifier_commands=("python -m pytest",),
        expected_outcome_id="expected:selfdev-dup-evidence",
        rollback_strategy="compensate_task",
        operator_intervention_count=1,
        hcw_minutes=2.0,
        baseline_assignment_id="baseline:selfdev-dup-evidence",
    )
    with pytest.raises(SelfDevelopmentValidationError) as run_exc:
        build_self_development_run_record(
            spec,
            operator_intervention_count=1,
            hcw_minutes=1.0,
            outcome_status="VERIFIED",
            evidence_refs=("dup:ref", "distinct:ref", "dup:ref"),
        )
    assert run_exc.value.code == INVALID_SELFDEV_TARGET
    assert "EVIDENCE_REF_DUPLICATE" in run_exc.value.detail

    with pytest.raises(SelfDevelopmentValidationError) as base_exc:
        build_self_development_baseline_record(
            baseline_assignment_id="baseline:selfdev-dup-evidence",
            repository_id="autonomous-agent-core",
            target_path=AGENT_OS_TARGET,
            operator_intervention_count=1,
            hcw_minutes=1.0,
            outcome_status="VERIFIED",
            evidence_refs=("dup:ref", "dup:ref"),
        )
    assert base_exc.value.code == INVALID_SELFDEV_TARGET
    assert "EVIDENCE_REF_DUPLICATE" in base_exc.value.detail
'''


def main() -> None:
    target = Path("tests/product/test_agent_os_self_development.py")
    if not target.is_file():
        raise SystemExit(f"anchor file missing: {target}")
    text = target.read_text(encoding="utf-8")
    if MARKER in text:
        raise SystemExit("fixture already applied")
    target.write_text(text.rstrip("\n") + "\n" + FIXTURE, encoding="utf-8")
    print(f"fixture F2 appended to {target}")


if __name__ == "__main__":
    sys.exit(main())
