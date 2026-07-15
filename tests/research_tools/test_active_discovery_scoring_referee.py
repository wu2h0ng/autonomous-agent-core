from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

from research_tools.active_discovery.scoring_contracts import (
    BehaviorTrace,
    ChallengeCatalogue,
    ChallengePrediction,
    ChallengeSequence,
    ChallengeStep,
    DiscoveryScoreBundle,
    OutcomeAtom,
    StatefulTestAssertion,
    StatefulTestCase,
    StatefulTestIR,
    StatefulTestStep,
    TraceProbability,
)
from research_tools.active_discovery.scoring_referee import (
    BundleByteStore,
    RefereeProtocolError,
    ScoringHalted,
    ScoringReferee,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


class _NeverHalted:
    def halted(self, episode_id: str) -> bool:
        return False


class _AlwaysHalted:
    def halted(self, episode_id: str) -> bool:
        return True


def _catalogue() -> ChallengeCatalogue:
    traces = tuple(
        sorted(
            (
                BehaviorTrace(
                    atoms=(
                        OutcomeAtom.create(
                            status_code=0,
                            stdout=label,
                            stderr="",
                            output={"value": label},
                            state_relation="SAME",
                        ),
                    )
                )
                for label in ("a", "b")
            ),
            key=lambda item: item.canonical_bytes,
        )
    )
    return ChallengeCatalogue.create(
        instance_public_digest="1" * 64,
        sequences=(
            ChallengeSequence.create(
                reset_slot="clean",
                steps=(ChallengeStep.create(operation_id="op", payload={"x": 1}),),
                traces=traces,
            ),
        ),
        probe_sequence_digests=(),
    )


def _chain(arm_id: str, catalogue: ChallengeCatalogue) -> tuple[DiscoveryScoreBundle, ...]:
    sequence = catalogue.sequences[0]
    probabilities = tuple(
        TraceProbability(trace.trace_digest, 500_000) for trace in sequence.traces
    )
    assertion = StatefulTestAssertion.create(
        source="STATUS_CODE", operator="EQ", expected=0
    )
    test_ir = StatefulTestIR(
        tests=(
            StatefulTestCase.create(
                test_id="test-1",
                reset_slot="test-reset",
                steps=(
                    StatefulTestStep.create(
                        operation_id="op",
                        payload={"held-out": 1},
                        assertions=(assertion,),
                    ),
                ),
                provenance_refs=("public-descriptor",),
            ),
        )
    )
    bundles: list[DiscoveryScoreBundle] = []
    parent: str | None = None
    for prefix in range(5):
        bundle = DiscoveryScoreBundle.create(
            experiment_id="R-ACTIVE-DISCOVERY-1",
            instance_public_digest=catalogue.instance_public_digest,
            arm_id=arm_id,
            actor_binding_digest="2" * 64,
            prefix_index=prefix,
            parent_bundle_digest=parent,
            predictions=(
                ChallengePrediction(
                    challenge_digest=sequence.challenge_digest,
                    probabilities=probabilities,
                    predicted_trace_digest=sequence.traces[0].trace_digest,
                ),
            ),
            test_ir=test_ir,
            transcript_prefix_digest=format(prefix + 3, "x") * 64,
            consumed_units=prefix,
            budget_receipt_digest=format(prefix + 8, "x") * 64,
            catalogue=catalogue,
        )
        bundles.append(bundle)
        parent = bundle.bundle_digest
    return tuple(bundles)


def test_actor_channel_can_only_seal_and_adjudicator_scores_after_global_close() -> None:
    catalogue = _catalogue()
    store = BundleByteStore()
    referee = ScoringReferee(
        episode_id="scoring-episode",
        expected_arm_ids=("A", "B"),
        halt_authority=_NeverHalted(),
        bundle_store=store,
    )
    for arm_id in ("A", "B"):
        channel = referee.actor_channel(arm_id)
        assert not hasattr(channel, "score")
        assert not hasattr(channel, "materialize")
        for bundle in _chain(arm_id, catalogue):
            channel.submit(bundle=bundle, catalogue=catalogue)

    with pytest.raises(RefereeProtocolError, match="global close"):
        referee.adjudicator_channel(authority_id="adjudicator-01")

    close = referee.close_actor_channels()
    adjudicator = referee.adjudicator_channel(authority_id="adjudicator-01")
    calls: list[str] = []
    batch = adjudicator.score_all(
        catalogues={"A": catalogue, "B": catalogue},
        evaluator=lambda bundle: calls.append(bundle.bundle_digest) or bundle.prefix_index,
    )

    assert close.bundle_count == 10
    assert store.stored_bundle_count == 10
    assert len(batch.scored_bundles) == len(calls) == 10
    assert {item.score_value for item in batch.scored_bundles} == {0, 1, 2, 3, 4}
    with pytest.raises(RefereeProtocolError, match="one-shot"):
        adjudicator.score_all(
            catalogues={"A": catalogue, "B": catalogue}, evaluator=lambda bundle: 0
        )


def test_content_addressed_store_reparses_exact_bundle_bytes_and_rejects_prefix_rewrite() -> None:
    catalogue = _catalogue()
    store = BundleByteStore()
    referee = ScoringReferee(
        episode_id="scoring-episode",
        expected_arm_ids=("A",),
        halt_authority=_NeverHalted(),
        bundle_store=store,
    )
    channel = referee.actor_channel("A")
    first = _chain("A", catalogue)[0]
    receipt = channel.submit(bundle=first, catalogue=catalogue)
    assert receipt.bundle_digest == first.bundle_digest

    with pytest.raises(RefereeProtocolError, match="next prefix"):
        channel.submit(bundle=first, catalogue=catalogue)
    assert store.stored_bundle_count == 1


def test_halt_prevents_bundle_or_score_access_and_returns_no_partial_batch() -> None:
    catalogue = _catalogue()
    store = BundleByteStore()
    referee = ScoringReferee(
        episode_id="halted",
        expected_arm_ids=("A",),
        halt_authority=_AlwaysHalted(),
        bundle_store=store,
    )
    with pytest.raises(ScoringHalted, match="halt"):
        referee.actor_channel("A").submit(
            bundle=_chain("A", catalogue)[0], catalogue=catalogue
        )
    assert store.stored_bundle_count == 0


def test_evaluator_failure_locks_one_shot_path_against_metric_dependent_retry() -> None:
    catalogue = _catalogue()
    referee = ScoringReferee(
        episode_id="scoring-episode",
        expected_arm_ids=("A",),
        halt_authority=_NeverHalted(),
        bundle_store=BundleByteStore(),
    )
    channel = referee.actor_channel("A")
    for bundle in _chain("A", catalogue):
        channel.submit(bundle=bundle, catalogue=catalogue)
    referee.close_actor_channels()
    adjudicator = referee.adjudicator_channel(authority_id="adjudicator-01")

    with pytest.raises(RuntimeError, match="trap"):
        adjudicator.score_all(
            catalogues={"A": catalogue},
            evaluator=lambda bundle: (_ for _ in ()).throw(RuntimeError("trap")),
        )
    with pytest.raises(RefereeProtocolError, match="one-shot"):
        adjudicator.score_all(
            catalogues={"A": catalogue}, evaluator=lambda bundle: 0
        )


def test_sidecar_does_not_import_private_donor_state_and_locks_donor_hashes() -> None:
    source_path = REPO_ROOT / "research_tools/active_discovery/scoring_referee.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "referee" not in imported_modules
    assert "arm_runner" not in imported_modules

    expected = {
        "research_tools/active_discovery/referee.py": "7f25d14b94f399626ff1681e8b73d82fb48804c41f282af3d10f46414b4fe925",
        "research_tools/active_discovery/arm_runner.py": "af1bbb940cd047406b699a84de8b1f2932b318d949a045aa11c233470ebea016",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((REPO_ROOT / relative).read_bytes()).hexdigest() == digest
