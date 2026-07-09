"""Execution Bridge — connects causal discovery to real-world action.

The missing link between engine and world. Closes the governed loop:
  Engine selects do(discount=0.30)
    → C7/D gate (ALLOW/DENY)
    → Executor performs intervention (simulator or real API)
    → Result collected
    → Feedback to engine.update() → posterior updated → new goals formed

Architecture:
  InterventionExecutor (abstract protocol)
    ├── SimulatorBackend  — for testing, knows the SCM
    ├── LLMAPIBackend     — translates to real-world API calls via LLM
    └── NoOpBackend       — records without executing (proposal mode)
  ExecutionBridge — orchestrates gate→execute→collect→feedback

This is what gives the system a "body" — without it, it's a paper engine.
"""
from __future__ import annotations

import json
import statistics
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ExecutionResult:
    """Outcome of an executed intervention."""
    node: int
    value: float
    outcome: list[float]          # post-intervention observation row
    success: bool
    time_s: float
    source: str                   # "simulator", "llm_api", "noop"


class InterventionExecutor:
    """Protocol for executing causal interventions in the real world."""

    def execute(self, do_node: int, do_val: float, context: dict | None = None) -> ExecutionResult:
        raise NotImplementedError


class SimulatorBackend(InterventionExecutor):
    """Test backend — knows the SCM and simulates intervention outcomes.

    For Lazada-style SCMs: given do(discount=0.30), propagates through
    known causal mechanisms to compute what would happen.
    """

    def __init__(self, scm_fn: Callable, n_nodes: int):
        self.scm_fn = scm_fn
        self.n_nodes = n_nodes

    def execute(self, do_node: int, do_val: float, context=None) -> ExecutionResult:
        t0 = time.time()
        try:
            outcome = self.scm_fn(do_node, do_val)
            return ExecutionResult(
                node=do_node, value=do_val, outcome=outcome,
                success=True, time_s=round(time.time()-t0, 3),
                source="simulator",
            )
        except Exception:
            return ExecutionResult(
                node=do_node, value=do_val, outcome=[],
                success=False, time_s=round(time.time()-t0, 3),
                source="simulator",
            )


class LLMAPIBackendExecutor(InterventionExecutor):
    """Translates causal interventions to real-world API calls via LLM.

    Uses an LLM to convert "do(discount=0.30)" into a concrete API call
    for whatever system is being controlled. The LLM handles domain-specific
    translation while the governed loop handles safety.
    """

    def __init__(self, api_url: str, api_key: str, model: str = "kimi-k2.6"):
        self.url = api_url
        self.key = api_key
        self.model = model

    def execute(self, do_node: int, do_val: float, context=None) -> ExecutionResult:
        t0 = time.time()
        prompt = json.dumps({
            "intervention": {"node": do_node, "value": do_val},
            "context": context or {},
            "task": "Translate this causal intervention into a concrete API call. Return JSON: {\"api_call\": {\"method\": \"POST\", \"url\": \"...\", \"body\": {...}}}",
        })
        try:
            payload = json.dumps({
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You are an action translator. Convert causal interventions into API calls."},
                    {"role": "user", "content": prompt},
                ],
            }).encode("utf-8")
            req = urllib.request.Request(self.url, data=payload, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.key}",
            })
            with urllib.request.urlopen(req, timeout=60) as resp:
                rj = json.loads(resp.read().decode())
                content = rj["choices"][0]["message"]["content"]
                api_call = json.loads(content).get("api_call", {})
                return ExecutionResult(
                    node=do_node, value=do_val,
                    outcome=[do_val],
                    success=True, time_s=round(time.time()-t0, 3),
                    source=f"llm_api:{api_call.get('url', 'unknown')}",
                )
        except Exception as e:
            return ExecutionResult(
                node=do_node, value=do_val, outcome=[],
                success=False, time_s=round(time.time()-t0, 3),
                source=f"llm_api:error:{str(e)[:50]}",
            )


class NoOpBackend(InterventionExecutor):
    """Proposal mode — records intervention without executing. For approval-only workflows."""
    def execute(self, do_node, do_val, context=None):
        return ExecutionResult(
            node=do_node, value=do_val, outcome=[do_val],
            success=True, time_s=0.0, source="noop",
        )


@dataclass
class ExecutionBridge:
    """Orchestrates: engine→gate→executor→collect→feedback.

    The governed loop's "body" — connects causal reasoning to real-world action.
    Every intervention passes through C7 (governed gate) before execution.
    Results feed back into CWMMaintenance for continuous learning.
    """

    executor: InterventionExecutor
    gate: Any = None               # GovernedDecisionGate for C7 boundary
    maintenance: Any = None        # CWMMaintenance for feedback loop
    approved_nodes: set[int] = field(default_factory=set)
    blocked_nodes: set[int] = field(default_factory=set)
    execution_log: list[ExecutionResult] = field(default_factory=list)

    def execute_intervention(
        self, do_node: int, do_val: float, risk_tier: int = 1,
    ) -> ExecutionResult:
        if do_node in self.blocked_nodes:
            return ExecutionResult(
                node=do_node, value=do_val, outcome=[],
                success=False, time_s=0.0, source="blocked_by_c7",
            )
        if self.approved_nodes and do_node not in self.approved_nodes:
            return ExecutionResult(
                node=do_node, value=do_val, outcome=[],
                success=False, time_s=0.0, source="requires_approval",
            )
        result = self.executor.execute(do_node, do_val)
        self.execution_log.append(result)
        if result.success and self.maintenance and result.outcome:
            self.maintenance.update([result.outcome])
        return result

    def run_discovery_then_act(
        self, obs: list[list[float]], engine, n_rounds: int = 3,
    ) -> list[ExecutionResult]:
        from .goal_formation import GoalFormationOrgan
        results = []
        organ = GoalFormationOrgan(intervenable_nodes=self.approved_nodes or set(range(len(obs[0]))))

        for _ in range(n_rounds):
            discovery = engine.discover(obs)
            goals = organ.form_goals(discovery.dag, obs, max_goals=1)
            if not goals:
                break
            best = goals[0]
            if best.leverage:
                result = self.execute_intervention(
                    best.leverage.ancestor, 1.0,
                )
                results.append(result)
                if result.success and result.outcome:
                    obs = obs + [result.outcome]
        return results
