from __future__ import annotations

import ast
import inspect
from dataclasses import replace
from pathlib import Path

import pytest

from research_tools.nonoracle_discovery.contracts import (
    DirectedAncestryHypothesis,
    DiscoveryContractError,
    InterventionDataset,
)
from research_tools.nonoracle_discovery.mechanism import StabilityCalibration, discover
from research_tools.nonoracle_discovery.qualification import confounded_indirect_fixture


CALIBRATION = StabilityCalibration(
    permutation_offsets=(1, 3, 5),
    minimum_effect_micros=500_000,
)


def _semantic(values: tuple[DirectedAncestryHypothesis, ...]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (item.source, item.target, item.signed_effect_micros, item.stability_micros)
        for item in values
    )


def _rename_dataset(dataset: InterventionDataset, mapping: dict[str, str]) -> InterventionDataset:
    return InterventionDataset.create(
        tuple(mapping[item] for item in dataset.variable_ids),
        dataset.control_rows,
        {condition.condition_id: condition.rows for condition in dataset.conditions},
        {condition.condition_id: mapping[condition.target] for condition in dataset.conditions},
    )


def _rename_semantic(
    values: tuple[DirectedAncestryHypothesis, ...], mapping: dict[str, str]
) -> tuple[tuple[object, ...], ...]:
    renamed = tuple(
        replace(item, source=mapping[item.source], target=mapping[item.target])
        for item in values
    )
    return _semantic(renamed)


def test_hidden_gold_mutation_has_no_input_channel_to_mechanism() -> None:
    dataset = confounded_indirect_fixture().dataset
    first_hidden_gold = {("v0", "v2")}
    second_hidden_gold = {("v1", "v2")}

    first = discover(dataset, CALIBRATION)
    first_hidden_gold.clear()
    first_hidden_gold.update(second_hidden_gold)
    second = discover(dataset, CALIBRATION)

    assert first == second
    assert tuple(inspect.signature(discover).parameters) == ("dataset", "calibration")


def test_variable_rename_is_semantically_equivariant() -> None:
    dataset = confounded_indirect_fixture().dataset
    mapping = {"v0": "q2", "v1": "q0", "v2": "q1"}

    original = discover(dataset, CALIBRATION)
    renamed = discover(_rename_dataset(dataset, mapping), CALIBRATION)

    assert _rename_semantic(original, mapping) == _semantic(renamed)


def test_missing_duplicate_or_contradictory_intervention_metadata_fails_closed() -> None:
    dataset = confounded_indirect_fixture().dataset
    rows = {condition.condition_id: condition.rows for condition in dataset.conditions}
    bindings = {condition.condition_id: condition.target for condition in dataset.conditions}
    with pytest.raises(DiscoveryContractError, match="binding"):
        InterventionDataset.create(dataset.variable_ids, dataset.control_rows, rows, {})
    with pytest.raises(DiscoveryContractError, match="unique target"):
        InterventionDataset.create(
            dataset.variable_ids,
            dataset.control_rows,
            {**rows, "duplicate-target": dataset.conditions[0].rows},
            {**bindings, "duplicate-target": dataset.conditions[0].target},
        )
    raw = dataset.to_mapping()
    raw["conditions"][0]["target"] = "absent"  # type: ignore[index]
    with pytest.raises(DiscoveryContractError, match="target"):
        InterventionDataset.from_mapping(raw)


def test_public_source_has_no_real_truth_or_scorer_import() -> None:
    package = Path(__file__).resolve().parents[2] / "research_tools/nonoracle_discovery"
    prohibited_names = {
        "GROUND_TRUTH",
        "ancestors",
        "sachs_task",
        "scoring_referee",
        "hidden_scoring",
    }
    prohibited_literals = {"Raf", "Mek", "Plcg", "PIP2", "PIP3", "Erk", "Akt", "PKA", "PKC", "P38", "Jnk"}
    for path in package.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert not prohibited_names.intersection(source.split())
        assert not any(name in source for name in prohibited_literals)
        assert not any(any(token in imported for token in prohibited_names) for imported in imports)


def test_public_evidence_change_changes_mechanism_output() -> None:
    dataset = confounded_indirect_fixture().dataset
    rows = {condition.condition_id: condition.rows for condition in dataset.conditions}
    bindings = {condition.condition_id: condition.target for condition in dataset.conditions}
    rows["condition-v0"] = dataset.control_rows
    changed = InterventionDataset.create(
        dataset.variable_ids,
        dataset.control_rows,
        rows,
        bindings,
    )

    assert discover(dataset, CALIBRATION) != discover(changed, CALIBRATION)


def test_output_cannot_carry_opaque_predictor_or_codec_state() -> None:
    fields = set(DirectedAncestryHypothesis.__dataclass_fields__)
    assert fields == {
        "source",
        "target",
        "signed_effect_micros",
        "stability_micros",
        "evidence_digest",
    }
    assert not fields.intersection({"weights", "embedding", "codec", "payload", "prediction"})
