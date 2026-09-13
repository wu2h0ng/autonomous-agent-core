"""WORKING-SET-COGNITIVE-INPUT-0 — controlled context-selection discriminator.

PRE-BUILD measurement only: it does NOT implement the cognitive-ordering
capability. It measures whether *ordering within an already-authorized set*
can cause missed critical evidence, separated from a token-budget effect.

Arms:
  A0 scope_only       — current policy (candidate-id ascending)
  A1 oracle_relevance — upper bound: oracle task-relevance order (withheld truth)
  A2 matched_full     — all authorized candidates at a matched larger budget
                        (isolates ordering from availability/budget)

Honest boundary: this is a deterministic controlled model (E2-style), NOT
product-path evidence and NOT parity/autonomy evidence. The spec is frozen;
arms are mechanical. Product impact requires the Mandate/SRL path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

Policy = Literal["scope_only", "oracle_relevance", "matched_full"]


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    tokens: int
    relevance_rank: int
    critical: bool


@dataclass(frozen=True)
class Task:
    task_id: str
    stratum: str
    candidates: tuple[Candidate, ...]


def assemble(candidates: tuple[Candidate, ...], policy: Policy, budget_tokens: int) -> tuple[str, ...]:
    if policy == "oracle_relevance":
        ordered = sorted(candidates, key=lambda c: (c.relevance_rank, c.candidate_id))
    else:  # scope_only and matched_full both use the current id-ascending order
        ordered = sorted(candidates, key=lambda c: c.candidate_id)
    selected: list[str] = []
    used = 0
    for candidate in ordered:
        if used + candidate.tokens <= budget_tokens:
            selected.append(candidate.candidate_id)
            used += candidate.tokens
    return tuple(selected)


def missed_critical(task: Task, selected_ids: tuple[str, ...]) -> bool:
    critical = [c for c in task.candidates if c.critical]
    if not critical:
        return False
    return not any(c.candidate_id in selected_ids for c in critical)


def generate_corpus(spec: Mapping[str, Any]) -> tuple[Task, ...]:
    per_task = int(spec["candidates_per_task"])
    tokens = int(spec["candidate_tokens"])
    tasks: list[Task] = []
    for stratum, params in (("positive", spec["positive"]), ("negative", spec["negative"])):
        critical_rank = int(params["critical_id_rank"])
        for index in range(int(params["tasks"])):
            candidates: list[Candidate] = []
            for position in range(per_task):
                is_critical = position == critical_rank
                candidates.append(
                    Candidate(
                        candidate_id=f"c{position:02d}",
                        tokens=tokens,
                        relevance_rank=0 if is_critical else position + 1,
                        critical=is_critical,
                    )
                )
            tasks.append(Task(task_id=f"{stratum}-{index:02d}", stratum=stratum, candidates=tuple(candidates)))
    return tuple(tasks)


def _rate(tasks: tuple[Task, ...], policy: Policy, budget: int) -> float:
    if not tasks:
        return 0.0
    misses = sum(1 for task in tasks if missed_critical(task, assemble(task.candidates, policy, budget)))
    return misses / len(tasks)


def run_arms(spec: Mapping[str, Any]) -> dict[str, Any]:
    corpus = generate_corpus(spec)
    budget = int(spec["token_budget"])
    matched = int(spec["matched_budget"])
    result: dict[str, Any] = {"arms": {}, "strata": {}}
    for stratum in ("positive", "negative"):
        tasks = tuple(task for task in corpus if task.stratum == stratum)
        rates = {
            "A0_scope_only": _rate(tasks, "scope_only", budget),
            "A1_oracle_relevance": _rate(tasks, "oracle_relevance", budget),
            "A2_matched_full": _rate(tasks, "matched_full", matched),
        }
        result["strata"][stratum] = rates
    pos = result["strata"]["positive"]
    neg = result["strata"]["negative"]
    result["arms"] = {"A0": "scope_only", "A1": "oracle_relevance", "A2": "matched_full"}
    result["gate"] = {
        "positive_improvement_A0_minus_A1": pos["A0_scope_only"] - pos["A1_oracle_relevance"],
        "negative_regression_A0_minus_A1": neg["A0_scope_only"] - neg["A1_oracle_relevance"],
        "A2_budget_only_positive": pos["A2_matched_full"],
    }
    result["passed"] = (
        pos["A0_scope_only"] - pos["A1_oracle_relevance"] >= float(spec["gate_min_positive_delta"])
        and neg["A0_scope_only"] - neg["A1_oracle_relevance"] <= float(spec["gate_max_negative_regression"])
        and pos["A2_matched_full"] <= float(spec["gate_max_A2_miss"])
    )
    return result


def spec_digest(spec: Mapping[str, Any]) -> str:
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_spec(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text("utf-8"))


def record_run(
    spec_path: str | Path,
    out_path: str | Path,
    *,
    status: str = "INVALID",
    note: str = (
        "controlled discriminator; result is INVALID as evidence until an "
        "independently-authored held-out corpus is frozen and adjudicated"
    ),
) -> dict[str, Any]:
    """Run the arms and record a fully-provenanced result artifact.

    `status` defaults to INVALID: this harness only demonstrates a mechanism in
    a controlled model; it is not product evidence and its corpus is
    author-authored, so `passed=true` must never be read as a finding.
    """
    spec = load_spec(spec_path)
    result = run_arms(spec)
    result["spec_digest"] = spec_digest(spec)
    result["spec_path"] = str(spec_path)
    result["status"] = status
    result["note"] = note
    Path(out_path).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", "utf-8")
    return result
