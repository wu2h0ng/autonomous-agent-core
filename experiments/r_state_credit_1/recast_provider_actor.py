"""Provider-only actor seam for the R-STATE runnable successor.

This module is deliberately separate from the qualification ``StubActor`` and
the rejected four-action ``ProbeAction`` path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol, cast

from experiments.r_state_credit_1.action_grammar import ALL_ACTIONS, ActorAction
from experiments.r_state_credit_1.actor_interface import ActorRequest, ActorResponse


class ProviderNotReady(RuntimeError):
    """The provider binding cannot enter a result-bearing path."""


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(value: str, label: str) -> None:
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class ProviderBinding:
    provider_id: str
    model_id: str
    model_revision: str
    revision_confirmed: bool
    transport: str
    action_grammar_sha256: str

    def __post_init__(self) -> None:
        for name in ("provider_id", "model_id", "model_revision"):
            if (
                not isinstance(getattr(self, name), str)
                or not getattr(self, name).strip()
            ):
                raise ValueError(f"{name} must be non-empty text")
        if self.transport != "API_ONLY":
            raise ProviderNotReady("provider transport must be API_ONLY")
        _sha256(self.action_grammar_sha256, "action_grammar_sha256")


@dataclass(frozen=True, slots=True)
class ProviderReceipt:
    provider_receipt_id: str
    provider_id: str
    model_id: str
    model_revision: str
    request_sha256: str
    response_sha256: str
    input_tokens: int
    output_tokens: int
    cost_microusd: int


@dataclass(frozen=True, slots=True)
class ProviderActorResponse:
    response: ActorResponse
    receipt: ProviderReceipt


class ProviderTransport(Protocol):
    def complete(self, request: ActorRequest) -> dict[str, object]: ...


class ProviderActor:
    """Require a concrete immutable provider revision and typed receipt."""

    def __init__(self, binding: ProviderBinding, transport: ProviderTransport) -> None:
        if "stub" in binding.provider_id.casefold():
            raise ProviderNotReady("Stub providers are forbidden in result path")
        if not binding.revision_confirmed:
            raise ProviderNotReady("confirmed immutable model revision is required")
        if binding.model_revision.casefold() in {"latest", "current", "default"}:
            raise ProviderNotReady("model alias is forbidden as a revision")
        expected = _digest(
            json.dumps([a.value for a in ALL_ACTIONS], separators=(",", ":")).encode()
        )
        if binding.action_grammar_sha256 != expected:
            raise ProviderNotReady("six-action grammar digest drift")
        self.binding = binding
        self._transport = transport

    def act(self, request: ActorRequest) -> ProviderActorResponse:
        if request.valid_actions != ALL_ACTIONS:
            raise ProviderNotReady("six-action grammar is mandatory")
        raw = self._transport.complete(request)
        required = {
            "action",
            "notes",
            "provider_receipt_id",
            "model_revision",
            "input_tokens",
            "output_tokens",
            "cost_microusd",
        }
        if set(raw) != required:
            raise ProviderNotReady("provider response schema drift")
        if raw["model_revision"] != self.binding.model_revision:
            raise ProviderNotReady("provider receipt revision drift")
        try:
            action = ActorAction(raw["action"])
        except (TypeError, ValueError) as exc:
            raise ProviderNotReady(
                "provider action is outside six-action grammar"
            ) from exc
        notes = raw["notes"]
        if notes is not None and not isinstance(notes, str):
            raise ProviderNotReady("provider notes schema drift")
        response = ActorResponse(action=action, notes=notes)
        response_bytes = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
        input_tokens, output_tokens, cost_microusd = (
            raw["input_tokens"],
            raw["output_tokens"],
            raw["cost_microusd"],
        )
        if any(
            not isinstance(v, int) or isinstance(v, bool) or v < 0
            for v in (input_tokens, output_tokens, cost_microusd)
        ):
            raise ProviderNotReady("provider usage/cost schema drift")
        input_token_count = cast(int, input_tokens)
        output_token_count = cast(int, output_tokens)
        receipt_id = raw["provider_receipt_id"]
        if not isinstance(receipt_id, str) or not receipt_id:
            raise ProviderNotReady("provider receipt id is missing")
        return ProviderActorResponse(
            response=response,
            receipt=ProviderReceipt(
                provider_receipt_id=receipt_id,
                provider_id=self.binding.provider_id,
                model_id=self.binding.model_id,
                model_revision=self.binding.model_revision,
                request_sha256=_digest(request.to_canonical_json().encode()),
                response_sha256=_digest(response_bytes),
                input_tokens=input_token_count,
                output_tokens=output_token_count,
                cost_microusd=cast(int, cost_microusd),
            ),
        )
