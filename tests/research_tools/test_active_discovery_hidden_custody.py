from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from research_tools.active_discovery.hidden_corpus_contracts import (
    CustodyAction,
    CustodyBindingManifest,
    CustodyBlockedError,
    assert_action_ready,
    load_custody_design_manifest,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DESIGN_MANIFEST_PATH = (
    REPO_ROOT / "research_tools/active_discovery/hidden_custody_design_manifest.json"
)


def _bound() -> CustodyBindingManifest:
    return CustodyBindingManifest(
        binding_status="BOUND_VALIDATION_FIXTURE",
        q_score_custodian_id="custodian-q-01",
        p_power_custodian_id="custodian-p-01",
        e_score_custodian_id="custodian-e-01",
        runner_operator_id="runner-operator-01",
        c7_authority_id="c7-authority-01",
        independent_adjudicator_id="adjudicator-01",
        human_protocol_operator_id="human-operator-01",
    )


def test_tracked_design_manifest_has_literal_nulls_and_no_run_authority() -> None:
    raw = json.loads(DESIGN_MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest = load_custody_design_manifest(DESIGN_MANIFEST_PATH)

    assert raw == manifest.to_mapping()
    assert manifest.binding_status == "UNBOUND_DESIGN_ONLY"
    assert all(
        value is None
        for key, value in raw.items()
        if key != "binding_status"
    )
    assert not hasattr(manifest, "run")
    assert not hasattr(manifest, "freeze")


@pytest.mark.parametrize("action", tuple(CustodyAction))
def test_every_pre_binding_sensitive_action_fails_closed(action: CustodyAction) -> None:
    manifest = load_custody_design_manifest(DESIGN_MANIFEST_PATH)

    with pytest.raises(CustodyBlockedError, match="BLOCKED_UNBOUND"):
        assert_action_ready(
            manifest=manifest,
            action=action,
            independent_review_receipt=None,
            scorer_implementer_id="scorer-implementer-01",
            actor_principal_ids=("actor-01",),
        )


@pytest.mark.parametrize("placeholder", ("TBD", "fake-custodian", "test-user", "unknown"))
def test_placeholder_inferred_and_fake_ids_are_not_bindings(placeholder: str) -> None:
    manifest = replace(_bound(), e_score_custodian_id=placeholder)
    with pytest.raises(CustodyBlockedError, match="BLOCKED_UNBOUND"):
        assert_action_ready(
            manifest=manifest,
            action=CustodyAction.HIDDEN_GENERATION,
            independent_review_receipt="a" * 64,
            scorer_implementer_id="scorer-implementer-01",
            actor_principal_ids=("actor-01",),
        )


def test_p_e_and_sovereign_role_collapse_fail_closed() -> None:
    bound = _bound()
    for collapsed in (
        replace(bound, p_power_custodian_id=bound.e_score_custodian_id),
        replace(bound, runner_operator_id=bound.e_score_custodian_id),
        replace(bound, c7_authority_id=bound.e_score_custodian_id),
        replace(bound, independent_adjudicator_id=bound.e_score_custodian_id),
        replace(bound, human_protocol_operator_id=bound.e_score_custodian_id),
    ):
        with pytest.raises(CustodyBlockedError, match="BLOCKED_UNBOUND"):
            assert_action_ready(
                manifest=collapsed,
                action=CustodyAction.COMMITMENT,
                independent_review_receipt="a" * 64,
                scorer_implementer_id="scorer-implementer-01",
                actor_principal_ids=("actor-01",),
            )

    for external_id in ("scorer-implementer-01", "actor-01"):
        with pytest.raises(CustodyBlockedError, match="BLOCKED_UNBOUND"):
            assert_action_ready(
                manifest=replace(bound, e_score_custodian_id=external_id),
                action=CustodyAction.COMMITMENT,
                independent_review_receipt="a" * 64,
                scorer_implementer_id="scorer-implementer-01",
                actor_principal_ids=("actor-01",),
            )


def test_fully_separated_validation_fixture_only_emits_validation_receipt() -> None:
    receipt = assert_action_ready(
        manifest=_bound(),
        action=CustodyAction.COMMITMENT,
        independent_review_receipt="a" * 64,
        scorer_implementer_id="scorer-implementer-01",
        actor_principal_ids=("actor-01",),
    )

    assert receipt.disposition == "BINDINGS_VALIDATED_NOT_RUN_AUTHORITY"
    assert receipt.action is CustodyAction.COMMITMENT
    assert receipt.validation_digest != "0" * 64
    assert not hasattr(receipt, "execute")
