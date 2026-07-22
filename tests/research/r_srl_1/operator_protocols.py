from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


REQUIRED_PROTOCOL_KEYS: frozenset[str] = frozenset(
    {
        "common_preamble",
        "arm1_baseline_scheduled_setup",
        "arm2_user_driven_driving",
        "arm3_srl_help_response",
        "arm4_persistent_state_ablation",
        "prohibited_coaching",
    }
)

ARM_ID_TO_KEY: dict[str, str] = {
    "arm1": "arm1_baseline_scheduled_setup",
    "arm2": "arm2_user_driven_driving",
    "arm3": "arm3_srl_help_response",
    "arm4": "arm4_persistent_state_ablation",
}


def _protocol_path() -> Path:
    """Return the path to the committed operator-protocol YAML file."""
    return Path(__file__).with_suffix(".yaml")


def load_operator_protocols(path: Path | None = None) -> dict[str, Any]:
    """Parse and return the R-SRL-1 operator protocol document.

    Args:
        path: Optional override for the YAML file path. Defaults to the
            committed ``operator_protocols.yaml`` next to this module.

    Returns:
        The parsed protocol document as a nested dictionary.

    Raises:
        FileNotFoundError: If the protocol file does not exist.
        yaml.YAMLError: If the file is not valid YAML.
    """
    target = path if path is not None else _protocol_path()
    with target.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _iter_instruction_texts(protocols: dict[str, Any]) -> list[str]:
    """Return every operator-facing instruction string in the protocol document.

    The prohibited list itself is excluded from the search because those strings
    are the forbidden patterns, not instructions the operator follows.
    """
    texts: list[str] = []

    def _walk(value: Any) -> None:
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, dict):
            for key, child in value.items():
                if key == "prohibited_coaching":
                    continue
                _walk(child)
        elif isinstance(value, list):
            for child in value:
                _walk(child)

    _walk(protocols)
    return texts


def validate_protocols(protocols: dict[str, Any]) -> None:
    """Validate the operator protocol document.

    Checks that all required sections are present and that no prohibited
    coaching phrase appears in any operator-facing instruction text.

    Args:
        protocols: Parsed operator protocol dictionary.

    Raises:
        ValueError: If a required key is missing or a prohibited coaching
            phrase is found in an instruction.
    """
    missing = REQUIRED_PROTOCOL_KEYS - protocols.keys()
    if missing:
        raise ValueError(f"Missing required protocol keys: {sorted(missing)}")

    raw_prohibited = protocols.get("prohibited_coaching", [])
    if not isinstance(raw_prohibited, list):
        raise ValueError("prohibited_coaching must be a list of strings")
    prohibited = list(raw_prohibited)

    texts = _iter_instruction_texts(protocols)
    for phrase in prohibited:
        if not isinstance(phrase, str):
            raise ValueError(
                f"Prohibited coaching entry must be a string, got {phrase!r}"
            )
        for text in texts:
            if phrase.lower() in text.lower():
                raise ValueError(
                    f"Prohibited coaching phrase found in operator instructions: {phrase!r}"
                )


def get_protocol(arm_id: str) -> dict[str, Any]:
    """Return the operator script for a given experimental arm.

    Args:
        arm_id: One of ``arm1``, ``arm2``, ``arm3`` or ``arm4``.

    Returns:
        The script dictionary for the requested arm.

    Raises:
        ValueError: If ``arm_id`` is not a recognized arm identifier.
    """
    key = ARM_ID_TO_KEY.get(arm_id)
    if key is None:
        raise ValueError(
            f"Unknown arm_id: {arm_id!r}. Expected one of {sorted(ARM_ID_TO_KEY)}"
        )
    protocols = load_operator_protocols()
    validate_protocols(protocols)
    return protocols[key]
