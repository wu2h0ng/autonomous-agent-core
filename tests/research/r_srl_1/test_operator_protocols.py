from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from tests.research.r_srl_1.operator_protocols import (
    ARM_ID_TO_KEY,
    REQUIRED_PROTOCOL_KEYS,
    get_protocol,
    load_operator_protocols,
    validate_protocols,
)


def test_yaml_loads_and_contains_required_sections() -> None:
    protocols = load_operator_protocols()
    assert isinstance(protocols, dict)
    for key in REQUIRED_PROTOCOL_KEYS:
        assert key in protocols, f"Missing required section: {key}"

    arm_sections = [
        "arm1_baseline_scheduled_setup",
        "arm2_user_driven_driving",
        "arm3_srl_help_response",
    ]
    for section in arm_sections:
        assert isinstance(protocols[section], dict)
        assert "title" in protocols[section]
        assert "role" in protocols[section]

    assert isinstance(protocols["common_preamble"], str)
    assert isinstance(protocols["prohibited_coaching"], list)
    assert len(protocols["prohibited_coaching"]) > 0


def test_validation_passes_for_committed_protocols() -> None:
    protocols = load_operator_protocols()
    validate_protocols(protocols)


def test_validation_rejects_missing_required_keys() -> None:
    protocols = load_operator_protocols()
    for key in REQUIRED_PROTOCOL_KEYS:
        incomplete = {k: v for k, v in protocols.items() if k != key}
        with pytest.raises(ValueError, match=f"Missing required protocol keys:.*{key}"):
            validate_protocols(incomplete)


def test_validation_rejects_prohibited_coaching_phrase() -> None:
    protocols = load_operator_protocols()
    modified = copy.deepcopy(protocols)
    prohibited_phrase = modified["prohibited_coaching"][0]
    modified["common_preamble"] += f"\n\n{prohibited_phrase}"

    with pytest.raises(ValueError, match="Prohibited coaching phrase found"):
        validate_protocols(modified)


def test_validation_rejects_prohibited_coaching_case_insensitive() -> None:
    protocols = load_operator_protocols()
    modified = copy.deepcopy(protocols)
    prohibited_phrase = modified["prohibited_coaching"][0]
    modified["common_preamble"] += f"\n\n{prohibited_phrase.upper()}"

    with pytest.raises(ValueError, match="Prohibited coaching phrase found"):
        validate_protocols(modified)


@pytest.mark.parametrize("arm_id", ["arm1", "arm2", "arm3"])
def test_get_protocol_returns_correct_text(arm_id: str) -> None:
    protocol = get_protocol(arm_id)
    assert isinstance(protocol, dict)
    assert protocol == load_operator_protocols()[ARM_ID_TO_KEY[arm_id]]
    assert "title" in protocol
    assert "role" in protocol


def test_get_protocol_rejects_unknown_arm() -> None:
    with pytest.raises(ValueError, match="Unknown arm_id: 'unknown'.*arm1.*arm2.*arm3"):
        get_protocol("unknown")


def test_load_operator_protocols_accepts_override_path(tmp_path: Path) -> None:
    protocols = load_operator_protocols()
    override = tmp_path / "override.yaml"
    with override.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(protocols, handle)

    loaded = load_operator_protocols(override)
    assert loaded == protocols


def test_validate_protocols_rejects_non_string_prohibited_entry() -> None:
    protocols = load_operator_protocols()
    modified = copy.deepcopy(protocols)
    modified["prohibited_coaching"] = [123]

    with pytest.raises(ValueError, match="Prohibited coaching entry must be a string"):
        validate_protocols(modified)


def test_validate_protocols_rejects_non_list_prohibited_coaching() -> None:
    protocols = load_operator_protocols()
    modified = copy.deepcopy(protocols)
    modified["prohibited_coaching"] = "not a list"

    with pytest.raises(
        ValueError, match="prohibited_coaching must be a list of strings"
    ):
        validate_protocols(modified)
