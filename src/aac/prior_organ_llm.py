"""LLM-backed prior organ (G6b scaffold, ADR-0019). Belief-only; the LLM's raw
output is UNTRUSTED and strictly parsed down to belief advice only.

The crucial guarantee: however the LLM (or its adapter) misbehaves, this organ
can only ever nudge the action-outcome belief. The parser keeps ONLY a numeric
`belief_delta` and a scalar `uncertainty`; everything else an LLM might emit
(an action, a tool call, a `pause:false`, a forbidden override) is discarded.
There is no action / policy / shell surface here, and the module imports none.

The real LLM backend (a paid, pinned, temperature=0, response-cached adapter)
is intentionally NOT bundled: core stays pure-stdlib and zero-spend. A
`DeterministicStubBackend` lets the interface and the C6/C7 guarantees be tested
offline. The real run requires a semantic environment + the founder's key/budget
(ADR-0019 §5).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .prior_organ import BeliefSnapshot, OrganAdvice


class LLMBackend(Protocol):
    def propose(self, prompt: str) -> Mapping[str, Any]:
        """Return a raw, UNTRUSTED proposal dict. Only belief fields survive."""


def _safe_belief_delta(raw: Any, n_actions: int) -> dict[int, float]:
    """Keep only in-range int->finite-float entries; drop everything else."""
    out: dict[int, float] = {}
    if not isinstance(raw, Mapping):
        return out
    for k, v in raw.items():
        try:
            a = int(k)
            x = float(v)
        except (TypeError, ValueError):
            continue
        if 0 <= a < n_actions and math.isfinite(x):
            out[a] = x
    return out


def _safe_uncertainty(raw: Any) -> float:
    try:
        u = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(u):
        return 0.0
    return min(1.0, max(0.0, u))


@dataclass
class LLMPriorOrgan:
    """A belief-only organ whose advice is proposed by an (untrusted) LLM backend."""

    backend: LLMBackend
    max_abs_delta: float = 10.0  # clamp; a runaway LLM cannot blow up the belief

    def _prompt(self, situation: Mapping[str, Any], belief: BeliefSnapshot) -> str:
        # A real adapter would render a semantic description; the stub ignores it.
        return (
            f"situation={dict(situation)} mu={belief.mu} "
            f"uncertainty={belief.uncertainty} last_surprise={belief.last_surprise}"
        )

    def advise(
        self, situation: Mapping[str, Any], belief_readonly: BeliefSnapshot
    ) -> OrganAdvice:
        raw = self.backend.propose(self._prompt(situation, belief_readonly))
        # STRICT: only belief_delta + uncertainty survive; all else is discarded,
        # so no action / policy / shell channel can be smuggled through the LLM.
        delta = _safe_belief_delta(
            raw.get("belief_delta") if isinstance(raw, Mapping) else None,
            belief_readonly.n_actions,
        )
        clamped = {a: max(-self.max_abs_delta, min(self.max_abs_delta, d)) for a, d in delta.items()}
        unc = _safe_uncertainty(raw.get("uncertainty") if isinstance(raw, Mapping) else None)
        return OrganAdvice(belief_delta=clamped, uncertainty=unc)


@dataclass
class DeterministicStubBackend:
    """Offline, deterministic stand-in: nudges mu toward a fixed target. No spend."""

    target: float = 1.0
    confidence: float = 0.3

    def propose(self, prompt: str) -> Mapping[str, Any]:
        # Deterministic; ignores the prompt. Real backends would be cached/pinned.
        return {"belief_delta": {0: self.target}, "uncertainty": self.confidence}
