"""Provider-only actor seam for the R-STATE runnable successor.

This module is deliberately separate from the qualification ``StubActor`` and
the rejected four-action ``ProbeAction`` path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, cast

from experiments.r_state_credit_1.action_grammar import ALL_ACTIONS, ActorAction
from experiments.r_state_credit_1.actor_interface import ActorRequest, ActorResponse


class ProviderNotReady(RuntimeError):
    """The provider binding cannot enter a result-bearing path."""


class ProviderCostStatus(str, Enum):
    PROVIDER_REPORTED = "PROVIDER_REPORTED"
    UNAVAILABLE_NOT_GUESSED = "UNAVAILABLE_NOT_GUESSED"


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
    actor_request_sha256: str
    provider_request_sha256: str
    provider_response_sha256: str
    raw_output_sha256: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_status: ProviderCostStatus
    cost_amount_microunits: int | None
    cost_currency: str | None
    latency_ms: int
    timeout_seconds: float


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
            "total_tokens",
            "cost_status",
            "cost_amount_microunits",
            "cost_currency",
            "actor_request_sha256",
            "provider_request_sha256",
            "provider_response_sha256",
            "raw_output_sha256",
            "latency_ms",
            "timeout_seconds",
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
        input_tokens, output_tokens, total_tokens = (
            raw["input_tokens"],
            raw["output_tokens"],
            raw["total_tokens"],
        )
        if any(
            not isinstance(v, int) or isinstance(v, bool) or v < 0
            for v in (input_tokens, output_tokens, total_tokens)
        ):
            raise ProviderNotReady("provider usage schema drift")
        input_token_count = cast(int, input_tokens)
        output_token_count = cast(int, output_tokens)
        total_token_count = cast(int, total_tokens)
        if total_token_count != input_token_count + output_token_count:
            raise ProviderNotReady("provider total token usage drift")
        try:
            cost_status = ProviderCostStatus(raw["cost_status"])
        except (TypeError, ValueError) as exc:
            raise ProviderNotReady("provider cost status drift") from exc
        cost_amount = raw["cost_amount_microunits"]
        cost_currency = raw["cost_currency"]
        if cost_status is ProviderCostStatus.UNAVAILABLE_NOT_GUESSED:
            if cost_amount is not None or cost_currency is not None:
                raise ProviderNotReady("unknown provider cost must remain null")
        elif (
            not isinstance(cost_amount, int)
            or isinstance(cost_amount, bool)
            or cost_amount < 0
            or not isinstance(cost_currency, str)
            or not cost_currency
        ):
            raise ProviderNotReady("reported provider cost schema drift")
        digests = {
            name: raw[name]
            for name in (
                "actor_request_sha256",
                "provider_request_sha256",
                "provider_response_sha256",
                "raw_output_sha256",
            )
        }
        for name, digest in digests.items():
            if not isinstance(digest, str):
                raise ProviderNotReady(f"{name} must be text")
            try:
                _sha256(digest, name)
            except ValueError as exc:
                raise ProviderNotReady(f"{name} drift") from exc
        if digests["actor_request_sha256"] != _digest(
            request.to_canonical_json().encode()
        ):
            raise ProviderNotReady("actor request digest drift")
        latency_ms = raw["latency_ms"]
        timeout_seconds = raw["timeout_seconds"]
        if (
            not isinstance(latency_ms, int)
            or isinstance(latency_ms, bool)
            or latency_ms < 0
            or not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or timeout_seconds <= 0
        ):
            raise ProviderNotReady("provider latency/timeout schema drift")
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
                actor_request_sha256=cast(str, digests["actor_request_sha256"]),
                provider_request_sha256=cast(str, digests["provider_request_sha256"]),
                provider_response_sha256=cast(str, digests["provider_response_sha256"]),
                raw_output_sha256=cast(str, digests["raw_output_sha256"]),
                input_tokens=input_token_count,
                output_tokens=output_token_count,
                total_tokens=total_token_count,
                cost_status=cost_status,
                cost_amount_microunits=cast(int | None, cost_amount),
                cost_currency=cast(str | None, cost_currency),
                latency_ms=cast(int, latency_ms),
                timeout_seconds=float(timeout_seconds),
            ),
        )
