from __future__ import annotations

import json

import pytest

from research_tools.active_discovery.cli import DevelopmentSpecError, main


def _write_spec(path, **extra: object) -> None:
    payload = {
        "schema_version": "active-discovery-dev/v1",
        "mode": "NOT_EVIDENCE",
        "family_seed": 17,
        "budget_limit": 2,
        **extra,
    }
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def test_qualify_dev_is_explicitly_not_evidence(tmp_path, capsys) -> None:
    spec_path = tmp_path / "dev-spec.json"
    _write_spec(spec_path)

    assert main(["qualify-dev", "--spec", str(spec_path)]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "NOT_EVIDENCE"
    assert payload["qualification_only"] is True
    assert payload["replay_match"] is True
    for forbidden in ("verdict", "calibration", "baseline", "research_score"):
        assert forbidden not in payload


def test_validate_spec_supports_only_closed_not_evidence_specs(
    tmp_path, capsys
) -> None:
    spec_path = tmp_path / "dev-spec.json"
    _write_spec(spec_path)

    assert main(["validate-spec", "--spec", str(spec_path)]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "VALID"
    assert payload["mode"] == "NOT_EVIDENCE"

    _write_spec(spec_path, verdict="MET")
    with pytest.raises(DevelopmentSpecError, match="unknown fields"):
        main(["validate-spec", "--spec", str(spec_path)])
