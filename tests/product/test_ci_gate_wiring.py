"""Drift guard for the CI gates declared in ``.github/workflows/ci.yml``.

Why this exists: the governed product suite and the cli-ts suite are only
enforced while the workflow keeps running them. Deleting the step, replacing its
command with a no-op, or neutralising it (``continue-on-error: true``,
``|| true``, ``--if-present``) leaves every other CI check green while the gate
quietly disappears.

Judgements are made on the *parsed* step objects and on their comment-stripped
``run`` blocks -- never on the raw file text. ci.yml documents each decision in
comments, and those comments mention ``pytest``, ``tests/product`` and
``unittest discover``; a full-text grep would keep passing after the real
command was deleted.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"

PRODUCT_GATE = "governed product gate"
CLI_TS_GATE = "cli-ts gate"

# A gate stops gating when its command can no longer fail. Each entry is
# (human label, regex over the comment-stripped run block).
SOFTENING_PATTERNS: tuple[tuple[str, str], ...] = (
    ("a `|| true`-style fallback", r"\|\|\s*(?:true|:|echo)(?=\s|$)"),
    ("a `; true`-style fallback", r";\s*true(?=\s|$)"),
    ("npm's `--if-present` (missing script becomes a no-op)", r"--if-present\b"),
    ("`--passWithNoTests` (zero collected tests passes)", r"--passWithNoTests\b"),
    ("`set +e` (defeats the runner's fail-fast shell)", r"\bset\s+\+e\b"),
)


@dataclass(frozen=True)
class Step:
    """One parsed CI step, with its run block reduced to what actually runs."""

    job_id: str
    job: Mapping[str, Any]
    index: int
    step: Mapping[str, Any]
    command: str

    @property
    def label(self) -> str:
        name = self.step.get("name") or f"step #{self.index + 1}"
        return f"job `{self.job_id}` / step `{name}`"

    @property
    def working_directory(self) -> str:
        return str(self.step.get("working-directory") or "")

    @property
    def summary(self) -> str:
        first = next((line for line in self.command.splitlines() if line.strip()), "")
        return f"{self.label}: {first.strip() or '<step has no run block>'}"


def _effective_command(run: str) -> str:
    """Drop shell comments so documentation is never mistaken for a command."""
    lines: list[str] = []
    for line in run.splitlines():
        if line.lstrip().startswith("#"):
            continue
        lines.append(line.split(" #", 1)[0])
    return "\n".join(lines)


def _all_steps() -> list[Step]:
    assert WORKFLOW_PATH.is_file(), (
        f"{WORKFLOW_PATH} is missing, so the CI gates it declares cannot be "
        "checked. Restore the repo-root workflow (it is where both gates live)."
    )
    document = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(document, Mapping), f"{WORKFLOW_PATH} did not parse as a mapping."
    jobs = document.get("jobs")
    assert isinstance(jobs, Mapping) and jobs, (
        f"{WORKFLOW_PATH} declares no jobs -- every gate it used to run is gone."
    )
    steps: list[Step] = []
    for job_id, job in jobs.items():
        if not isinstance(job, Mapping):
            continue
        for index, step in enumerate(job.get("steps") or ()):
            if not isinstance(step, Mapping):
                continue
            run = step.get("run")
            steps.append(
                Step(
                    job_id=str(job_id),
                    job=job,
                    index=index,
                    step=step,
                    command=_effective_command(run) if isinstance(run, str) else "",
                )
            )
    return steps


def _describe(steps: Sequence[Step]) -> str:
    return " | ".join(step.summary for step in steps)


def _runs_product_suite(step: Step) -> bool:
    """A real pytest invocation scoped to the governed suite at tests/product."""
    return bool(re.search(r"\bpytest\b", step.command)) and bool(
        re.search(r"tests/product\b", step.command)
    )


def _is_cli_ts_scoped(step: Step) -> bool:
    return (
        step.job_id == "cli-ts"
        or "apps/cli-ts" in step.command
        or "apps/cli-ts" in step.working_directory
    )


def _runs_cli_ts_tests(step: Step) -> bool:
    """The apps/cli-ts suite: scripts.test, or an equivalent direct test run."""
    if not _is_cli_ts_scoped(step):
        return False
    return bool(
        re.search(r"\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?test\b", step.command)
        or re.search(r"\bnode\b[^\n]*\s--test\b", step.command)
        or re.search(r"\bvitest\b", step.command)
    )


def _runs_cli_ts_typecheck(step: Step) -> bool:
    if not _is_cli_ts_scoped(step):
        return False
    return bool(
        re.search(r"\bnpm\s+run\s+typecheck\b", step.command)
        or re.search(r"\btsc\b[^\n]*(?:--noEmit|-p\b)", step.command)
    )


def _runs_unittest_discover(step: Step) -> bool:
    return "unittest discover" in step.command


def _softening_reasons(step: Step) -> list[str]:
    reasons: list[str] = []
    for scope, container in (("step", step.step), ("job", step.job)):
        value = container.get("continue-on-error")
        if value is not None and str(value).strip().lower() not in {"", "0", "false"}:
            reasons.append(f"{scope} sets continue-on-error: {value!r}")
        condition = container.get("if")
        if condition is not None and str(condition).strip().lower() in {"false", "0"}:
            reasons.append(f"{scope} is guarded by `if: {condition}` (never runs)")
    for label, pattern in SOFTENING_PATTERNS:
        if re.search(pattern, step.command):
            reasons.append(f"run block contains {label}")
    return reasons


def _assert_gate_runs(
    steps: list[Step], gate: str, predicate: Any, expected: str
) -> None:
    matches = [step for step in steps if predicate(step)]
    assert matches, (
        f"CI gate MISSING: the {gate} is not wired in {WORKFLOW_PATH}. Expected "
        f"{expected}. Steps actually parsed: {_describe(steps)}"
    )


def test_ci_workflow_still_declares_the_governed_product_gate() -> None:
    steps = _all_steps()
    _assert_gate_runs(
        steps,
        PRODUCT_GATE,
        _runs_product_suite,
        "a step whose run block invokes pytest against tests/product "
        "(`PYTHONPATH=src:packages/contracts/src:packages/os_core/src "
        "python -m pytest tests/product -q`). Without it the governed product "
        "suite -- surface contracts, situated, SRL working set, SSE end-frame "
        "regression -- never runs in CI (`unittest discover` cannot collect it)",
    )


def test_ci_workflow_still_declares_the_cli_ts_gate() -> None:
    steps = _all_steps()
    _assert_gate_runs(
        steps,
        CLI_TS_GATE,
        _runs_cli_ts_tests,
        "a job/step for apps/cli-ts running its test suite (`npm test` in "
        "apps/cli-ts, i.e. apps/cli-ts/package.json scripts.test). No Python "
        "job in this workflow executes the TypeScript suite",
    )


def test_ci_workflow_still_typechecks_the_cli_ts_suite() -> None:
    steps = _all_steps()
    _assert_gate_runs(
        steps,
        f"{CLI_TS_GATE} (typecheck)",
        _runs_cli_ts_typecheck,
        "a step in the apps/cli-ts scope running `npm run typecheck` "
        "(apps/cli-ts/package.json scripts.typecheck = `tsc -p tsconfig.json "
        "--noEmit`), or an equivalent `tsc --noEmit`/`-p` invocation",
    )


def test_ci_gate_steps_are_not_softened() -> None:
    steps = _all_steps()
    gated = [
        step
        for step in steps
        if _runs_product_suite(step)
        or _runs_cli_ts_tests(step)
        or _runs_cli_ts_typecheck(step)
    ]
    assert gated, (
        f"CI gate MISSING: no gate step at all was found in {WORKFLOW_PATH} "
        f"(neither {PRODUCT_GATE} nor {CLI_TS_GATE}). Steps actually parsed: "
        f"{_describe(steps)}"
    )
    problems = [
        f"{step.label}: {'; '.join(reasons)}"
        for step in gated
        if (reasons := _softening_reasons(step))
    ]
    assert not problems, (
        "CI gate SOFTENED: the gate only counts while its failure can fail the "
        f"build. {WORKFLOW_PATH} neutralises: {' || '.join(problems)}"
    )


def test_ci_workflow_still_runs_the_deterministic_unittest_discover_step() -> None:
    steps = _all_steps()
    _assert_gate_runs(
        steps,
        "deterministic unittest step",
        _runs_unittest_discover,
        "the `Tests (deterministic)` step running "
        '`python -m unittest discover -s tests -p "test_*.py"`',
    )
