from __future__ import annotations

import hashlib

import pytest

from experiments.r_state_credit_1.action_grammar import ALL_ACTIONS
from experiments.r_state_credit_1.actor_interface import ActorRequest
from tests.support import r_state_fake_execution_launcher as launcher
from tests.test_r_state_credit_1_unix_authority_client import _admission


def test_fake_actor_emits_2240_unique_typed_unknown_cost_receipts() -> None:
    actor = launcher.fake_actor_factory(_admission("6" * 64))
    receipt_ids: set[str] = set()
    provider_request_digests: set[str] = set()

    for index in range(1, 2241):
        request = ActorRequest(
            representation=f"state-{index}",
            valid_actions=ALL_ACTIONS,
            session_label=f"session-{index}",
        )
        receipt = actor.act(request).receipt
        assert (
            receipt.actor_request_sha256
            == hashlib.sha256(request.to_canonical_json().encode()).hexdigest()
        )
        assert receipt.input_tokens + receipt.output_tokens == receipt.total_tokens
        assert receipt.cost_status.value == "UNAVAILABLE_NOT_GUESSED"
        assert receipt.cost_amount_microunits is None
        assert receipt.cost_currency is None
        receipt_ids.add(receipt.provider_receipt_id)
        provider_request_digests.add(receipt.provider_request_sha256)

    assert len(receipt_ids) == 2240
    assert len(provider_request_digests) == 2240


def test_launcher_delegates_original_argv_to_real_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_main(argv: object, *, actor_factory: object) -> int:
        captured.update(argv=argv, actor_factory=actor_factory)
        return 17

    monkeypatch.setattr(launcher, "real_main", fake_main)
    argv = ["--admission", "admission.json"]

    assert launcher.main(argv) == 17
    assert captured == {"argv": argv, "actor_factory": launcher.fake_actor_factory}
