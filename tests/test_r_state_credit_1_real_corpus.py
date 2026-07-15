"""Deterministic reversible repository corpus tests for R-STATE-CREDIT-1."""

from __future__ import annotations

import json
from pathlib import Path

from experiments.r_state_credit_1.contracts import ArmId, ScenarioFamily
from experiments.r_state_credit_1.real_corpus import (
    COMMITTED_CORPUS_ROOT,
    apply_repository_mutation,
    generate_corpus,
    load_public_batch,
    load_public_cases,
    materialize_repository,
    repository_digest,
    rollback_repository,
    verify_corpus,
)
from experiments.r_state_credit_1.run_contracts import (
    CheckpointId,
    HELD_OUT_SEEDS,
)


TOOL_SCHEMA_SHA256 = "a" * 64


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_corpus_generation_is_byte_deterministic_and_manifest_verified(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_receipt = generate_corpus(first)
    second_receipt = generate_corpus(second)

    assert first_receipt == second_receipt
    assert _tree_bytes(first) == _tree_bytes(second)
    assert verify_corpus(first) == first_receipt
    assert first_receipt.public_episode_count == 140
    assert first_receipt.public_checkpoint_count == 560
    assert first_receipt.public_case_file_count == 7


def test_public_files_have_exact_coverage_and_no_referee_truth(tmp_path: Path) -> None:
    corpus_root = tmp_path / "corpus"
    generate_corpus(corpus_root)

    cases = load_public_cases(corpus_root)
    assert len(cases) == len(ScenarioFamily) * len(HELD_OUT_SEEDS)
    assert {(case["family"], case["seed"]) for case in cases} == {
        (family.value, seed) for family in ScenarioFamily for seed in HELD_OUT_SEEDS
    }
    public_bytes = b"".join(
        path.read_bytes() for path in sorted((corpus_root / "public").glob("*.jsonl"))
    )
    for forbidden in (
        b"loss_by_action",
        b"expected_action",
        b"oracle_label",
        b"hidden_entity_key",
        b"sealed/referee",
    ):
        assert forbidden not in public_bytes
    for case in cases:
        assert len(case["checkpoints"]) == len(CheckpointId)
        assert {checkpoint["checkpoint_id"] for checkpoint in case["checkpoints"]} == {
            checkpoint.value for checkpoint in CheckpointId
        }
        assert all(
            set(checkpoint["representations"]) == {arm.value for arm in ArmId}
            for checkpoint in case["checkpoints"]
        )


def test_public_loader_builds_exact_typed_rfinal_batch(tmp_path: Path) -> None:
    corpus_root = tmp_path / "corpus"
    generate_corpus(corpus_root)

    batch = load_public_batch(
        corpus_root,
        run_id="tests-only-real-corpus",
        tool_schema_sha256=TOOL_SCHEMA_SHA256,
    )

    assert len(batch.cases) == 560
    assert all(len(case.actor_requests) == len(ArmId) for case in batch.cases)
    for case in batch.cases:
        assert {request.observable_digest for request in case.actor_requests} == {
            case.actor_requests[0].observable_digest
        }
        assert all(
            request.tool_schema_sha256 == TOOL_SCHEMA_SHA256
            and request.run_id == batch.run_id
            for request in case.actor_requests
        )


def test_each_family_materializes_mutates_and_rolls_back_exact_bytes(
    tmp_path: Path,
) -> None:
    corpus_root = tmp_path / "corpus"
    generate_corpus(corpus_root)
    cases = load_public_cases(corpus_root)

    for family in ScenarioFamily:
        case = next(item for item in cases if item["family"] == family.value)
        repository = tmp_path / "repositories" / family.value
        initial_digest = materialize_repository(case, repository)
        assert initial_digest == case["repository"]["initial_tree_sha256"]
        mutated_digest = apply_repository_mutation(case, repository)
        assert mutated_digest == case["repository"]["mutated_tree_sha256"]
        assert mutated_digest != initial_digest
        rolled_back_digest = rollback_repository(case, repository)
        assert rolled_back_digest == initial_digest
        assert repository_digest(repository) == initial_digest


def test_committed_corpus_is_exact_generator_output(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    generate_corpus(generated)

    assert verify_corpus(COMMITTED_CORPUS_ROOT).public_episode_count == 140
    assert _tree_bytes(COMMITTED_CORPUS_ROOT) == _tree_bytes(generated)
    manifest = json.loads(
        (COMMITTED_CORPUS_ROOT / "public-case-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["case_files"]
