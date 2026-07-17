"""Deterministic tests-only R-STATE launcher using the real execution CLI."""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from experiments.r_state_credit_1.action_grammar import ALL_ACTIONS  # noqa: E402
from experiments.r_state_credit_1.actor_interface import ActorRequest  # noqa: E402
from experiments.r_state_credit_1.execution_bridge import (  # noqa: E402
    ExecutionAdmission,
    canonical_json,
)
from experiments.r_state_credit_1.execution_run_cli import main as real_main  # noqa: E402
from experiments.r_state_credit_1.recast_provider_actor import (  # noqa: E402
    ProviderActor,
    ProviderBinding,
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class DeterministicFakeTransport:
    """Emit unique, closed typed receipts without network or hidden switches."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request: ActorRequest) -> dict[str, object]:
        self.calls += 1
        actor_request_sha256 = _sha256(request.to_canonical_json().encode())
        provider_request = canonical_json(
            {
                "actor_request_sha256": actor_request_sha256,
                "call_index": self.calls,
                "fixture": "R_STATE_DETERMINISTIC_FAKE_V1",
            }
        ).encode()
        raw_output = canonical_json({"action": "CONTINUE", "notes": None}).encode()
        provider_response = canonical_json(
            {
                "call_index": self.calls,
                "raw_output_sha256": _sha256(raw_output),
                "receipt_id": f"r-state-fake-provider-{self.calls:04d}",
            }
        ).encode()
        return {
            "action": "CONTINUE",
            "notes": None,
            "provider_receipt_id": f"r-state-fake-provider-{self.calls:04d}",
            "model_revision": "glm-5-2-260617",
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
            "cost_status": "UNAVAILABLE_NOT_GUESSED",
            "cost_amount_microunits": None,
            "cost_currency": None,
            "actor_request_sha256": actor_request_sha256,
            "provider_request_sha256": _sha256(provider_request),
            "provider_response_sha256": _sha256(provider_response),
            "raw_output_sha256": _sha256(raw_output),
            "latency_ms": 0,
            "timeout_seconds": 120,
        }


def fake_actor_factory(admission: ExecutionAdmission) -> ProviderActor:
    action_digest = _sha256(
        json.dumps(
            [action.value for action in ALL_ACTIONS], separators=(",", ":")
        ).encode()
    )
    binding = admission.provider_binding
    return ProviderActor(
        ProviderBinding(
            provider_id=binding.provider_id,
            model_id=binding.model_id,
            model_revision=binding.model_revision,
            revision_confirmed=True,
            transport="API_ONLY",
            action_grammar_sha256=action_digest,
        ),
        DeterministicFakeTransport(),
    )


def main(argv: Sequence[str] | None = None) -> int:
    return real_main(argv, actor_factory=fake_actor_factory)


if __name__ == "__main__":
    raise SystemExit(main())
