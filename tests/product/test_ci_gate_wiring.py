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

The same rule applies one level down, to the product gate's own self-check: its
``--collect-only`` floor and the run it guards are only worth anything while they
name the SAME target, the floor literal is high enough to notice a narrowed suite,
and the below-the-floor branch actually exits non-zero. A gate can be "present"
and still toothless in any of those ways, so each is asserted separately below.

Both jobs are also bounded in time. GitHub's default job cap is 360 minutes, so a
job that declares no ``timeout-minutes`` turns a hung step into six hours of runner
time; the bound is asserted per job, not once for the file.

A third gate lives in the same job -- the terminal coding eval step, which is the
only thing that runs ``tests/product_eval/`` -- and it used to be judged by nothing
here. ``_runs_product_suite`` matches ``tests/product\\b``, which does NOT match
``tests/product_eval`` (``_`` is a word character, so there is no boundary), so the
eval step was in none of the lists below and in no named assertion. Measured at
3fb0ff46 (2026-09-18): this file reported 19 passed with that step present, 19
passed after deleting the whole step, and 19 passed after turning it into
``continue-on-error: true`` with an ``echo`` body. The step has its own predicate
and named assertion below, and the assertion is pinned to the eval modules that
exist on disk, so narrowing it to one of them is red too.

Wiring the step is not the whole claim, which is why two more layers are judged
here. The cli-ts step runs ``npm run test:ci``, and that indirection used to be
unguarded in both directions: the step could name a silent script that does
nothing (``echo``, ``true``), and the cli-ts job's 20-minute bound could be exceeded by
the very deadlines meant to enforce it (34 files x 180 s = 102 minutes, with
``TEST_FILE_TIMEOUT_MS`` checked by nothing). So ``scripts["test:ci"]`` is parsed
and executed here -- through the same argv ci.yml runs, with a ``--list`` probe
that reports the file list and the deadlines the script will really use -- and
asserted against the workflow, against the files on disk, and against the job's
own wall clock. Finally, the product gate's own breadth can shrink without
failing it: skipped tests are still *collected*, so neither the floor nor the
file-set gate notices them, and the run was ``-q`` with no ``-rs``, so the skip
reasons never reached the log. The skip count and its bound are asserted below.

The same four questions are asked of the newest gate in the cli-ts job, the TUI
frame checks (``npm run check:frames:ci`` -> ``scripts/pty-ci.mjs`` -> one bounded
process per ``scripts/pty_*.py``), because that gate has one more failure mode
than the others: it runs a SUBSET of the checks on disk by design (the ones that
can fail), so "is it wired", "is the script it names real", "does the subset cover
what it says" and "does its budget fit the job" are four different questions, and
each is asserted separately below -- including the invariant that a check is only
allowed to be a CI gate while it can actually exit non-zero.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"

PRODUCT_GATE = "governed product gate"
CLI_TS_GATE = "cli-ts gate"
TERMINAL_CODING_EVAL_GATE = "terminal coding eval gate"

# The terminal line's coding corpus is graded by the pytest modules under this root, and
# this step is the only CI dependency tests/product_eval/ has: `grep -n product_eval
# .github/workflows/ci.yml` matches the step itself and nothing else, because $PRODUCT_ARGS is
# `tests/product` and `unittest discover -s tests` cannot collect these modules either. So while
# nothing asserted the step, the whole corpus could stop running in CI with every check green.
TERMINAL_CODING_EVAL_ROOT = "tests/product_eval"
TERMINAL_CODING_EVAL_MODULE = re.compile(r"test_terminal_coding_eval[A-Za-z0-9_]*\.py")

# A gate stops gating when its command can no longer fail. Each entry is
# (human label, regex over the comment-stripped run block).
#
# `exit 0` in any position is the loudest form of it: the step reports success no
# matter what the gate just did, so a step that failed at 4 of 2642 tests looks
# exactly like a full pass. It arrives as a bare line, as `|| exit 0`, or as
# `; exit 0`, so all three statement positions are matched. `exit ${?}` is the
# quiet form: the step's status is re-derived from whatever command ran last
# instead of from the gate, which is what a "tail after the gate" needs to pass.
_STATEMENT_START = r"(?:^|[;&|]|\bthen\b|\belse\b|\bdo\b)\s*"
SOFTENING_PATTERNS: tuple[tuple[str, str], ...] = (
    ("a `|| true`-style fallback", r"\|\|\s*(?:true|:|echo)(?=\s|$)"),
    ("a `; true`-style fallback", r";\s*true(?=\s|$)"),
    ("npm's `--if-present` (missing script becomes a no-op)", r"--if-present\b"),
    ("`--passWithNoTests` (zero collected tests passes)", r"--passWithNoTests\b"),
    ("`set +e` (defeats the runner's fail-fast shell)", r"\bset\s+\+e\b"),
    (
        "an `exit 0` (bare, `|| exit 0` or `; exit 0`) that ends the step green",
        _STATEMENT_START + r"exit\s+0(?=\s|;|$)",
    ),
    (
        "an `exit ${?}` tail (the step's verdict is re-derived from whatever ran last)",
        _STATEMENT_START + r"exit\s+\"?\$\{?\??\}?\"?(?=\s|;|$)",
    ),
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


def _runs_terminal_coding_eval(step: Step) -> bool:
    """A real pytest invocation scoped to the terminal coding eval modules.

    A predicate of its own rather than a widened ``_runs_product_suite``: the two
    suites are different corpora, carried by different steps, and ``tests/product``
    is also named by the governed gate's shell variables and error messages.
    """
    return bool(re.search(r"\bpytest\b", step.command)) and bool(
        re.search(r"tests/product_eval\b", step.command)
    )


def _terminal_coding_eval_modules_on_disk() -> list[str]:
    """Every ``test_terminal_coding_eval*.py`` module under tests/product_eval.

    The root is pinned as a literal instead of being read out of the workflow: a
    narrowed step must not also shrink the expectation it is judged against.
    """
    root = REPO_ROOT / TERMINAL_CODING_EVAL_ROOT
    assert root.is_dir(), (
        f"CI GATE MISSING: {root} does not exist, so the terminal coding eval has no corpus "
        f"modules to run and the comparison below would be vacuous."
    )
    return sorted(
        f"{TERMINAL_CODING_EVAL_ROOT}/{path.name}"
        for path in root.iterdir()
        if path.is_file() and TERMINAL_CODING_EVAL_MODULE.fullmatch(path.name)
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


def _runs_cli_ts_install_smoke(step: Step) -> bool:
    """The install -> build -> pack -> start -> answer check for the built CLI."""
    if not _is_cli_ts_scoped(step):
        return False
    return bool(re.search(r"\binstall_smoke\.sh\b", step.command))


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
        # MULTILINE so `^` matches the start of a line inside the run block, which is
        # where a bare `exit 0` and its neighbours live.
        if re.search(pattern, step.command, re.MULTILINE):
            reasons.append(f"run block contains {label}")
    return reasons


# --- the governed product step's own three-hop self-check -------------------------------
# That step validates itself in three hops: (1) `pytest <targets> -q --collect-only` must
# yield at least FLOOR_MINIMUM items, (2) every `test_*.py` module sitting on disk under the
# governed root must appear in that collection, and (3) the SAME targets must actually run.
# The floor is worth nothing while hops (1) and (3) can drift apart: a run line narrowed on
# its own (one literal path, an added `-k`/`--ignore`/`--deselect`) leaves the collection at
# full size, so the floor passes and the step stays green while most of the governed suite
# never executes. Measured on this tree (2026-09-18, the guards below included, in a clean
# copy of the tree): `python -m pytest tests/product -q --collect-only` collected 2642
# items, `pytest tests/product/test_wave2_renderer_conformance.py -q` ran 4 of them, and
# both exited 0. The counts are dated because the suite grows; FLOOR_MINIMUM is a round
# bound and must not be re-tightened to a measured total.
#
# The floor is also only a MAGNITUDE gate, which is what hop (2) exists to fix: the whole
# suite is 2646 items and the largest single module collects 148, so a subset of a dozen or
# so big modules -- or an `--ignore` added to BOTH invocations, which the floor measures
# along with the run -- clears 2500 and stays green while a third of the suite stops
# running. Comparing the SET of collected files against the set on disk sees all of those,
# and sees modules deleted from disk in small numbers, which the floor only notices after
# roughly 146 items are gone.
FLOOR_MINIMUM = 2000

# The root whose `test_*.py` modules the product gate must collect IN FULL, and the file
# pattern that says which modules those are (`test_*.py` already excludes this directory's
# helpers: conftest.py, mandate_observation_support.py, _situated_epoch.py, _steward_app.py).
GOVERNED_ROOT = "tests/product"
GOVERNED_FILE_PATTERN = "test_*.py"

# The disk listing the gate builds its expectation from: a `find <root> ... -name '<pattern>'`
# whose output is collected into a file (`> "$SOMETHING"`). Judged on position, so the gate
# can be rewritten around it, but not silently pointed somewhere else.
_DISK_LISTING = re.compile(
    r"\bfind\s+(?P<root>[\w./-]+)\b[^\n]*?-name\s+['\"]?(?P<pattern>[^'\"\s]+)['\"]?"
    r"[^\n]*?>\s*\"?\$\{?(?P<out>[A-Za-z_]\w*)\}?\"?"
)
# The collected side: the `::`-split first field of pytest's item lines, written to a file.
# `-F'::' ... print $1` distinguishes it from the floor's item COUNT over the same log.
_COLLECTED_LISTING = re.compile(
    r">\s*\"?\$\{?(?P<out>[A-Za-z_]\w*)\}?\"?\s*$"
)
# The set difference and the branch that fails the step on it.
_SET_DIFFERENCE = re.compile(
    r"^\s*(?P<var>[A-Za-z_]\w*)=\"?\$\(\s*comm\s+-23\s+\"?\$\{?(?P<left>\w+)\}?\"?"
    r"\s+\"?\$\{?(?P<right>\w+)\}?\"?\s*\)\"?",
    re.MULTILINE,
)
# The explicit exemption list: one literal path at a time, never a pattern. The entry form is
# the form of the DISK LISTING above (`find tests/product ...` prints `tests/product/x.py`) and
# not a bare basename: both sides of the comparison hold paths and the filter is a whole-line
# match, so `test_x.py` can never match `tests/product/test_x.py` -- the list then exempts
# nothing, silently, and the pressure is to weaken the comparison instead. Asserting the form
# here is what keeps a second "exemption that cannot take effect" out of the file.
_ALLOWLIST = re.compile(r"^\s*ALLOWED_UNCOLLECTED=(?P<value>.*)$", re.MULTILINE)
_ALLOWED_ENTRY = re.compile(rf"{re.escape(GOVERNED_ROOT)}/[A-Za-z0-9_.-]+\.py")

# The governed run's skip accounting: `-rs` puts every skip's REASON in the log, and the count
# is read out of a machine-readable report rather than pytest's summary line.
SKIP_REPORT_FLAG = re.compile(r"(?:^|\s)-r[a-z]*s[a-z]*\b")
JUNIT_XML = re.compile(r"--junitxml=\"?\$\{?(?P<out>[A-Za-z_]\w*)\}?\"?")
MAX_SKIPS_ALLOWED = 20


@dataclass(frozen=True)
class PytestInvocation:
    """One pytest command line in a run block, with the targets it was scoped to."""

    line: str
    targets: tuple[str, ...]

    @property
    def collects_only(self) -> bool:
        return "--collect-only" in self.line

    @property
    def shape(self) -> str:
        """The command with everything that cannot change WHAT runs normalised away.

        ``--collect-only``, pytest's skip report (``-rs``/``-ra``) and the JUnit report
        (``--junitxml=...``) are reporting-only: they change what the log and the report file
        contain, never which tests execute. They are stripped so the running line and the
        measuring line can be compared on the words that DO decide what runs.
        """
        text = re.sub(r"^\s*if\s+!\s*", "", self.line)
        text = re.sub(r";\s*then\s*$", "", text)
        text = re.sub(r"\s*>\s*\S+\s*$", "", text)
        text = re.sub(r"--junitxml(?:=|\s+)\S+", " ", text)
        text = re.sub(r"(?<=\s)-r[a-z]*\b", " ", text)
        text = re.sub(r"--collect-only\b", " ", text)
        return " ".join(text.split())


# A real pytest invocation, judged by POSITION: a command word at the start of a statement
# (optionally `if !`-guarded and preceded by env assignments such as PYTHONPATH=...), never the
# word `pytest` inside an error message -- `echo "::error::... pytest exit $status"` is a line
# about a run, not a run.
_PYTEST_COMMAND = re.compile(
    r"(?:^|[;&|]|\bthen\b)\s*(?:if\s+!\s*)?(?:[A-Za-z_]\w*=[^\s]*\s+)*(?:python3?\s+-m\s+)?pytest\b(.*)$"
)


def _joined_command_lines(command: str) -> str:
    """Join shell line continuations, so one command split across lines is one line.

    ``ci.yml`` writes a long pytest invocation as ``... \\`` + an indented
    continuation. Judging such a command line by line reads its first target and
    then the backslash as the second one, which is why the terminal coding eval
    step's targets are only readable here.
    """
    joined: list[str] = []
    pending = ""
    for line in command.splitlines():
        stripped = line.rstrip()
        if stripped.endswith("\\"):
            pending += stripped[:-1] + " "
            continue
        joined.append(pending + line)
        pending = ""
    if pending:
        joined.append(pending)
    return "\n".join(joined)


def _pytest_invocations(command: str) -> list[PytestInvocation]:
    """Every pytest line in a run block, with the positional (target) words it names."""
    invocations: list[PytestInvocation] = []
    for line in _joined_command_lines(command).splitlines():
        match = _PYTEST_COMMAND.search(line)
        if match is None:
            continue
        targets: list[str] = []
        for token in match.group(1).split():
            if token.startswith("-") or token.startswith(">"):
                break
            targets.append(token.strip("\"'").rstrip(";"))
        invocations.append(PytestInvocation(line=line, targets=tuple(targets)))
    return invocations


def _collect_guarded_step() -> Step:
    """The step that measures the governed suite before running it."""
    steps = _all_steps()
    matches = [
        step
        for step in steps
        if _runs_product_suite(step) and "--collect-only" in step.command
    ]
    assert len(matches) == 1, (
        f"CI FLOOR MISSING: expected exactly one step taking a pytest --collect-only "
        f"measurement of the governed suite (pytest against tests/product) in "
        f"{WORKFLOW_PATH}, found {len(matches)}. Without it nothing checks that the "
        f"product gate still collects a whole suite, so a step narrowed to a handful of "
        f"tests stays green. Product-scoped steps actually parsed: "
        f"{_describe([step for step in steps if _runs_product_suite(step)]) or '<none>'}"
    )
    return matches[0]


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


def test_ci_workflow_still_runs_the_cli_ts_install_smoke() -> None:
    steps = _all_steps()
    _assert_gate_runs(
        steps,
        f"{CLI_TS_GATE} (install smoke)",
        _runs_cli_ts_install_smoke,
        "a step in the apps/cli-ts scope running `bash scripts/install_smoke.sh`, "
        "the install -> build -> pack -> start -> answer check in "
        "apps/cli-ts/scripts/install_smoke.sh. Without it the terminal line is "
        "built and unit-tested in CI but never actually started and answered",
    )


def test_ci_workflow_still_declares_the_terminal_coding_eval_gate() -> None:
    """The eval step is the only CI dependency tests/product_eval/ has, and must run all of it.

    ``tests/product_eval`` is not covered by $PRODUCT_ARGS, so this step is what
    carries the terminal line's coding corpus into CI. It is asserted here for
    the same reason the two gates above are: a step that is deleted, emptied or
    silently given ``continue-on-error`` takes the corpus with it and nothing
    else in the repo goes red. The targets are judged against the modules on
    disk (not a literal list) so that dropping one of them -- or adding a module
    the step forgets -- is red as well.
    """
    steps = _all_steps()
    _assert_gate_runs(
        steps,
        TERMINAL_CODING_EVAL_GATE,
        _runs_terminal_coding_eval,
        "a step whose run block invokes pytest against tests/product_eval "
        "(`PYTHONPATH=src:packages/contracts/src:packages/os_core/src python -m pytest "
        "tests/product_eval/test_terminal_coding_eval.py "
        "tests/product_eval/test_terminal_coding_eval_live.py -q`). Without it the "
        "TERMINAL-CODING-EVAL-1 corpus stops running in CI: the step above is scoped to "
        "tests/product and `unittest discover` cannot collect these modules",
    )
    step = next(step for step in steps if _runs_terminal_coding_eval(step))
    on_disk = _terminal_coding_eval_modules_on_disk()
    assert on_disk, (
        f"CI GATE VACUOUS: no `test_terminal_coding_eval*.py` module is on disk under "
        f"{TERMINAL_CODING_EVAL_ROOT}, so there is nothing for {step.label} to run and the "
        f"comparison below would compare two empty sets."
    )
    targets = sorted(
        {target for invocation in _pytest_invocations(step.command) for target in invocation.targets}
    )
    assert targets == on_disk, (
        f"CI EVAL TARGET MISMATCH: {step.label} would run {targets} where the modules on disk "
        f"under {TERMINAL_CODING_EVAL_ROOT} are {on_disk}. The step must name every "
        f"`test_terminal_coding_eval*.py` module that exists -- a step narrowed to one of them "
        f"runs the corpus's own tests while the other file stops being executed by anything, "
        f"and a new module left out of the step is a file that exists, is registered in no "
        f"target, and never runs."
    )


def test_ci_gate_steps_are_not_softened() -> None:
    steps = _all_steps()
    gated = [
        step
        for step in steps
        if _runs_product_suite(step)
        or _runs_terminal_coding_eval(step)
        or _runs_cli_ts_tests(step)
        or _runs_cli_ts_typecheck(step)
        or _runs_cli_ts_install_smoke(step)
        or _runs_cli_ts_frame_checks(step)
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


def test_ci_product_gate_measures_and_runs_the_same_target() -> None:
    """The collect-only floor must measure exactly what the step then runs."""
    step = _collect_guarded_step()
    invocations = _pytest_invocations(step.command)
    measuring = [inv for inv in invocations if inv.collects_only]
    running = [inv for inv in invocations if not inv.collects_only]
    assert len(measuring) == 1 and running, (
        f"{step.label} must invoke pytest twice -- once with --collect-only (the floor "
        f"measurement) and once for real -- found {len(measuring)} measuring and "
        f"{len(running)} running. pytest lines seen: "
        f"{[inv.line.strip() for inv in invocations]}"
    )
    measured, executed = measuring[0], running[-1]
    assert measured.targets and executed.targets, (
        f"CI TARGET UNREADABLE: could not read the target of the measuring line "
        f"({measured.line.strip()!r}) or of the running line ({executed.line.strip()!r}) "
        f"in {step.label}."
    )
    assert measured.targets == executed.targets, (
        f"CI TARGET MISMATCH: {step.label} measures {list(measured.targets)} but runs "
        f"{list(executed.targets)}. Both invocations must name the same targets -- in "
        f"practice one shared shell variable such as $PRODUCT_ARGS -- because the floor "
        f"below can only notice a narrowed gate while it measures the same thing that "
        f"runs. With the collecting line left on the full suite and only the running line "
        f"narrowed, the collection stays at 2642 items, the floor passes, and the step "
        f"exits 0 while 4 of those 2642 tests executed. Measuring: "
        f"`{measured.line.strip()}` / running: `{executed.line.strip()}`"
    )
    for target in measured.targets:
        assert re.fullmatch(r"\$\{?[A-Za-z_]\w*\}?", target), (
            f"CI TARGET NOT SHARED: {step.label} names its target {target!r} literally, "
            f"so the target is written down more than once and the two copies can drift "
            f'apart. Carry it in one shell variable (e.g. PRODUCT_ARGS="tests/product") '
            f"and let both invocations read that variable: then narrowing the gate narrows "
            f"the collected count too, and the floor catches it."
        )
    assert measured.shape == executed.shape, (
        f"CI RUN NARROWED: {step.label} measures `{measured.shape}` but runs "
        f"`{executed.shape}`. Once the redirection, the `if !`, the `; then` and "
        f"`--collect-only` are normalised away, the two must be the same command: any "
        f"extra or missing word on the running line (`-k`, `--ignore`, `--deselect`, a "
        f"file instead of the suite) narrows what executes while the collected count "
        f"stays full, which is exactly the green-but-tiny step this gate exists to "
        f"reject."
    )


def test_ci_product_gate_keeps_a_collection_floor_that_bites() -> None:
    """The floor must be present, bounded above 2000, and actually exit non-zero."""
    step = _collect_guarded_step()
    command = step.command

    measured = next(
        inv.line for inv in _pytest_invocations(command) if inv.collects_only
    )
    log = re.search(r">\s*\"?\$\{?([A-Za-z_]\w*)\}?\"?", measured)
    assert log, (
        f"CI FLOOR VACUOUS: the measuring line of {step.label} does not write pytest's "
        f'item lines anywhere (`... > "$LOG"`), so there is nothing to count and the '
        f"floor cannot be compared against. Measuring line: `{measured.strip()}`"
    )
    log_var = log.group(1)

    counter = next(
        (
            line
            for line in command.splitlines()
            if re.match(r"\s*[A-Za-z_]\w*=", line)
            and "awk" in line
            and f"${log_var}" in line
        ),
        None,
    )
    assert counter is not None, (
        f"CI FLOOR VACUOUS: nothing in {step.label} counts the item lines of "
        f"${log_var}, so the collected total the floor is supposed to compare against is "
        f"never computed and the floor is only decorative. Expected a line like "
        f"`COLLECTED=\"$(awk '/::/ {{ items++ }} END {{ print items + 0 }}' "
        f'"${log_var}")"`.'
    )
    counted_var = re.match(r"\s*([A-Za-z_]\w*)=", counter).group(1)

    guard = re.search(
        r"\bif\s+\[\s*\"?\$\{?"
        + re.escape(counted_var)
        + r"\}?\"?\s+-l[et]\s+(\d+)\s*\]\s*;\s*then\b"
        + r"(?P<body>(?:\n[ \t]+[^\n]*)*)",
        command,
    )
    assert guard is not None, (
        f"CI FLOOR MISSING: {step.label} counts items into ${counted_var} but never "
        f"guards the run with them -- there is no "
        f'`if [ "${counted_var}" -lt <floor> ]; then ... exit 1` between the count and '
        f"the real run. That comparison IS the protection against a narrowed gate: "
        f"without it, a step collecting 4 items out of 2642 exits 0 exactly like a full "
        f"one. (The `exit 1` in the collect-only failure branch does not count as this "
        f"guard: it only fires when the collection is COMPLETELY empty, which pytest "
        f"signals with its own exit code 5.) The judged criterion is: the variable the "
        f"count is assigned to must be compared to a literal floor with `-lt`/`-le` and "
        f"the failing branch must exit non-zero."
    )
    floor = int(guard.group(1))
    assert floor >= FLOOR_MINIMUM, (
        f"CI FLOOR TOO LOW: {step.label} fails only below {floor} collected items, and "
        f"this guard requires at least {FLOOR_MINIMUM}. A low floor cannot notice a "
        f"narrowed gate -- measured on this tree, tests/product collects 2642 items and "
        f"even the largest single file collects 148 -- so a floor of {floor} would let a "
        f"step that runs a handful of tests pass. Raise the literal in the `-lt` "
        f"comparison; do not lower this threshold."
    )
    assert re.search(r"^\s*exit\s+(?!0\b)\S+", guard.group("body"), re.MULTILINE), (
        f"CI FLOOR DOES NOT BITE: the below-the-floor branch of {step.label} does not "
        f"exit non-zero, so hitting the floor leaves the step green -- the floor is then "
        f"informational only. Branch judged: {guard.group('body').strip()!r}"
    )


def test_ci_product_gate_collects_every_module_on_disk() -> None:
    """The floor counts items; this asserts the gate also compares file SETS.

    The two are not substitutes. `pytest <targets>` exits 0 on a subset of any size, and
    the floor only fails below FLOOR_MINIMUM items, so a target narrowed to a dozen large
    modules -- or an `--ignore` added to BOTH invocations, which the floor measures along
    with the run -- still clears 2500 and exits 0 with a large part of the governed suite
    silently not running. Comparing the collected file set against the files on disk
    under the governed root is what makes that red.
    """
    step = _collect_guarded_step()
    command = step.command
    pytest_lines = [inv.line.strip() for inv in _pytest_invocations(command)]

    measured = next(
        inv.line for inv in _pytest_invocations(command) if inv.collects_only
    )
    log = re.search(r">\s*\"?\$\{?([A-Za-z_]\w*)\}?\"?", measured)
    assert log, (
        f"CI FILE-SET GATE VACUOUS: the measuring line of {step.label} does not write "
        f"pytest's item lines anywhere (`... > \"$LOG\"`), so there is no collection to "
        f"read the collected file set out of. Measuring line: `{measured.strip()}`"
    )
    log_var = log.group(1)

    listing = _DISK_LISTING.search(command)
    assert listing is not None, (
        f"CI FILE-SET GATE MISSING: {step.label} compares no file set -- there is no "
        f"`find {GOVERNED_ROOT} ... -name '{GOVERNED_FILE_PATTERN}' ... > \"$LIST\"` "
        f"building the set of modules the collection is supposed to cover, so nothing "
        f"notices a module that is on disk and not in the collection. The item floor "
        f"cannot notice it either: it is a MAGNITUDE gate, and the whole suite is 2646 "
        f"items while the largest single module collects 148, so a subset of a dozen or "
        f"so big modules still clears 2500 and exits 0. pytest lines seen: {pytest_lines}"
    )
    root = listing.group("root").strip("/")
    assert root.strip("./") == GOVERNED_ROOT, (
        f"CI FILE-SET GATE MISROOTED: {step.label} lists modules under {listing.group('root')!r}, "
        f"not the governed root {GOVERNED_ROOT!r}. The expectation must be pinned to the "
        f"directory the product gate is defined to cover -- reading it from the same "
        f"variable the pytest target comes from would let a narrowed target shrink the "
        f"disk list along with it and keep the diff empty, which is the whole hole this "
        f"comparison closes."
    )
    assert listing.group("pattern") == GOVERNED_FILE_PATTERN, (
        f"CI FILE-SET GATE MISFILTERED: {step.label} expects "
        f"{listing.group('pattern')!r} to be collected, not {GOVERNED_FILE_PATTERN!r}. The "
        f"pattern decides which modules must appear in the collection: a narrow one (a "
        f"single file name, or a glob that happens to match almost nothing) exempts the "
        f"rest of the directory from the check, and a broad one (`*.py`) demands that "
        f"conftest.py and the underscore-prefixed helpers be collected as tests."
    )
    expected_var = listing.group("out")

    collected = next(
        (
            match
            for line in command.splitlines()
            if "awk" in line
            and "-F'::'" in line
            and "$1" in line
            and f"${log_var}" in line
            and (match := _COLLECTED_LISTING.search(line)) is not None
        ),
        None,
    )
    assert collected is not None, (
        f"CI FILE-SET GATE VACUOUS: nothing in {step.label} reads the collected file set "
        f"out of ${log_var}, so only one side of the comparison exists. Expected a line "
        f"like `awk -F'::' '/::/ {{ print $1 }}' \"${log_var}\" | sed 's|^\\./||' | sort -u "
        f'> "$COLLECTED_LIST"`, i.e. the node id of every collected item split at `::` and '
        f"its file part kept. pytest lines seen: {pytest_lines}"
    )
    collected_var = collected.group("out")

    difference = _SET_DIFFERENCE.search(command)
    assert difference is not None, (
        f"CI FILE-SET GATE VACUOUS: {step.label} builds a disk list and a collected list "
        f"but never subtracts one from the other -- there is no "
        f"`MISSING=\"$(comm -23 \"${expected_var}\" \"${collected_var}\")\"` (or "
        f"equivalent) turning the two into the set that is on disk and not collected. "
        f"Both lists on their own are inert."
    )
    assert {difference.group("left"), difference.group("right")} == {
        expected_var,
        collected_var,
    }, (
        f"CI FILE-SET GATE DISCONNECTED: {step.label} subtracts "
        f"${difference.group('left')} from ${difference.group('right')}, but the sets it "
        f"built are ${expected_var} (disk) and ${collected_var} (collection). A "
        f"comparison between a list and something else (an empty temp file, the other "
        f"end's leftovers) always comes out empty and passes."
    )
    missing_var = difference.group("var")

    guard = re.search(
        r"if\s+\[\s+-n\s+\"?\$\{?"
        + re.escape(missing_var)
        + r"\}?\"?\s*\]\s*;\s*then\b"
        + r"(?P<body>(?:\n[ \t]+[^\n]*)*)",
        command,
    )
    assert guard is not None, (
        f"CI FILE-SET GATE DOES NOT BITE: {step.label} computes the missing-module set "
        f"into ${missing_var} but never tests it -- there is no "
        f'`if [ -n "${missing_var}" ]; then ... exit 1` (or `if [ -z ... ]` with the '
        f"branches swapped) between the comparison and the real run. Without it the diff "
        f"is printed for nobody and the step stays green with modules missing from the "
        f"collection."
    )
    assert re.search(r"^\s*exit\s+(?!0\b)\S+", guard.group("body"), re.MULTILINE), (
        f"CI FILE-SET GATE DOES NOT BITE: the missing-module branch of {step.label} does "
        f"not exit non-zero, so a disk/collection mismatch leaves the step green and the "
        f"comparison is informational only. Branch judged: {guard.group('body').strip()!r}"
    )

    allowlist = _ALLOWLIST.search(command)
    assert allowlist is not None, (
        f"CI FILE-SET GATE HAS NO EXEMPTION MECHANISM: {step.label} declares no "
        f"`ALLOWED_UNCOLLECTED=` list. A module that legitimately cannot collect items in "
        f"this environment would then make the step fail with no recorded way to say so, "
        f"and the pressure would be to weaken the comparison itself. The exemption has to "
        f"be an explicit, per-file, commented list -- never a glob and never a blanket "
        f"wildcard."
    )
    literal = re.fullmatch(r"(?P<quote>['\"])(?P<inner>[^'\"]*)(?P=quote)", allowlist.group("value").strip())
    assert literal, (
        f"CI FILE-SET GATE EXEMPTION INDIRECT: {step.label} sets ALLOWED_UNCOLLECTED to "
        f"{allowlist.group('value').strip()!r}, which is not a literal list. An exemption "
        f"list that is computed, expanded from a variable or built by a command is one "
        f"more place where a wildcard can hide; write the paths out."
    )
    entries = literal.group("inner").split()
    for entry in entries:
        assert not re.search(r"[*?\[\]{}]", entry), (
            f"CI FILE-SET GATE EXEMPTION TOO BROAD: {step.label} exempts {entry!r} via "
            f"ALLOWED_UNCOLLECTED, but an entry must be one literal path. A glob entry "
            f"(`*`, `test_*`) reads as 'every module is exempt' and is the wildcard this "
            f"list is explicitly not allowed to hold. Exempt one module at a time, each "
            f"with its reason in the comment above the list. Entries judged: {entries}"
        )
        assert _ALLOWED_ENTRY.fullmatch(entry), (
            f"CI FILE-SET GATE EXEMPTION INERT: {step.label} exempts {entry!r} via "
            f"ALLOWED_UNCOLLECTED, but an entry must be spelled the way the DISK LISTING "
            f"spells the file -- `{GOVERNED_ROOT}/<name>.py`. Both sides of this comparison "
            f"hold paths and the filter is a whole-line match against the disk listing, so "
            f"a bare basename (`{entry}`) matches nothing, exempts nothing and leaves the "
            f"step failing with a list that looks like it should work: that is exactly how "
            f"this exemption mechanism was broken before (no entry could ever take effect), "
            f"and the only way out of it was to weaken the comparison. Write the path as "
            f"`{GOVERNED_ROOT}/{entry.strip('/')}` (a live entry is also checked by the step "
            f"itself, which fails on an entry that matches nothing on disk). "
            f"Entries judged: {entries}"
        )
    assert re.search(r"for\s+\w+\s+in\s+\$\{?ALLOWED_UNCOLLECTED\}?", command), (
        f"CI FILE-SET GATE EXEMPTION UNUSED: {step.label} declares ALLOWED_UNCOLLECTED but "
        f"never iterates over it, so the list (and any entry in it) is decoration: the "
        f"comparison still demands every module on disk. Either use it to filter the "
        f"expectation, or delete it and the claim that exemptions are possible."
    )
    # The rejection has to read the value as ONE WORD, and the word has to be quoted. A
    # per-entry test inside `for allowed in $ALLOWED_UNCOLLECTED` cannot work: the unquoted
    # expansion globs `*` into the working directory's file names before any entry test runs,
    # so the wildcard is swallowed and the step accepts a list it is supposed to reject.
    # `case` neither field-splits nor globs its word, which is why the quoted form is the one
    # that bites.
    rejection = re.search(
        r"case\s+(?P<word>\"\$\{?ALLOWED_UNCOLLECTED\}?\"|'\$\{?ALLOWED_UNCOLLECTED\}?')"
        r"\s+in(?P<body>.*?)\besac\b",
        command,
        re.DOTALL,
    )
    where = (
        "A `case` on an UNQUOTED $ALLOWED_UNCOLLECTED was found instead, and one on a "
        "per-entry variable is worse still: the shell globs the unquoted value before any "
        "test sees it."
        if re.search(r"case\s+\$\{?ALLOWED_UNCOLLECTED\}?\s+in", command)
        else "No `case` over ALLOWED_UNCOLLECTED was found at all."
    )
    assert rejection is not None and re.search(
        r"^\s*exit\s+(?!0\b)\S+", rejection.group("body"), re.MULTILINE
    ), (
        f"CI FILE-SET GATE EXEMPTION UNGUARDED: {step.label} does not reject a non-literal "
        f"ALLOWED_UNCOLLECTED value before using it, so the step itself accepts a wildcard "
        f"exemption. {where} The check must be a `case` over the quoted "
        f'"$ALLOWED_UNCOLLECTED" whose matching branch exits non-zero, placed BEFORE the '
        f"loop that consumes the list -- `grep -x -F` makes a wildcard entry inert when "
        f"filtering, but the list is read by a human as the record of what is exempt, and "
        f'"*" there reads as "everything is exempt".'
    )
    loop = re.search(r"for\s+\w+\s+in\s+\$\{?ALLOWED_UNCOLLECTED\}?", command)
    assert loop is not None, (
        f"CI FILE-SET GATE EXEMPTION UNUSED: {step.label} has no loop over "
        f"ALLOWED_UNCOLLECTED."
    )
    assert rejection.start() < loop.start(), (
        f"CI FILE-SET GATE EXEMPTION UNGUARDED: {step.label} consumes ALLOWED_UNCOLLECTED "
        f"in its `for` loop before the `case` that rejects a wildcard value, so the list is "
        f"already filtered into the expectation by the time the rejection would fire. The "
        f"guard must come first."
    )
    # A well-formed entry can still be inert: the loop used to filter only when the entry
    # matched, so an entry written in the wrong shape did nothing at all, silently. The loop
    # body must therefore FAIL on an entry that matches nothing in the disk listing, which is
    # what turns "the exemption did not take effect" into a red step instead of a mystery.
    loop_body = re.search(
        r"for\s+\w+\s+in\s+\$\{?ALLOWED_UNCOLLECTED\}?[^\n]*\n(?P<body>(?:[ \t]+[^\n]*\n?)*)",
        command,
    )
    assert loop_body is not None, (
        f"CI FILE-SET GATE EXEMPTION UNREADABLE: could not read the body of the "
        f"ALLOWED_UNCOLLECTED loop in {step.label}."
    )
    body = loop_body.group("body")
    assert re.search(rf"grep\s+-q\s+-x\s+-F[^\n]*\$allowed[^\n]*\$\{{?{re.escape(expected_var)}\}}?", body), (
        f"CI FILE-SET GATE EXEMPTION INERT: the loop over ALLOWED_UNCOLLECTED in "
        f"{step.label} does not test each entry against the disk listing ${expected_var} "
        f"before using it, so an entry that matches nothing (the wrong path form, a "
        f"deleted module) is indistinguishable from a working exemption: the step keeps "
        f"failing and the list keeps claiming the module is excused. Loop body judged: "
        f"{body.strip()!r}"
    )
    assert re.search(r"^\s*exit\s+(?!0\b)\S+", body, re.MULTILINE), (
        f"CI FILE-SET GATE EXEMPTION INERT: the loop over ALLOWED_UNCOLLECTED in "
        f"{step.label} never exits non-zero, so an entry that matches no module on disk "
        f"is accepted without effect. A dead exemption is the failure this list already "
        f"had once -- it could not take effect and the only way to pass was to weaken the "
        f"comparison -- so the step must reject an entry that matches nothing. Loop body "
        f"judged: {body.strip()!r}"
    )


def _guarded_branch(command: str, needs: Sequence[str]) -> str | None:
    """The body of the first `if` whose condition line mentions every string in `needs`.

    Used where the assertion's point is "this comparison exists, and the branch it guards
    actually fails the step": the condition is judged by the variables it reads, not by the
    exact wording of the test operator.
    """
    for match in re.finditer(
        r"^[ \t]*if\b[^\n]*;\s*then\b[^\n]*\n(?P<body>(?:[ \t]+[^\n]*\n?)*)",
        command,
        re.MULTILINE,
    ):
        if all(token in match.group(0) for token in needs):
            return match.group("body")
    return None


def test_ci_product_gate_bounds_and_reports_skips() -> None:
    """A skipped test is still COLLECTED, so neither gate above can see one appear.

    The floor counts items and the file-set gate counts modules; a module whose tests all
    skip passes both while running nothing at all. Until this was fixed the run was `-q`
    with no `-rs`, so even the summary count was the only trace and the reasons were nowhere,
    and nothing bounded the number: the suite could lose test after test to skips with every
    wiring assertion above still green.
    """
    step = _collect_guarded_step()
    command = step.command
    running = [inv for inv in _pytest_invocations(command) if not inv.collects_only]
    assert running, (
        f"CI SKIP GATE VACUOUS: {step.label} has no running pytest line to check for skip "
        f"reporting. pytest lines seen: "
        f"{[inv.line.strip() for inv in _pytest_invocations(command)]}"
    )
    run_line = running[-1].line

    assert SKIP_REPORT_FLAG.search(run_line), (
        f"CI SKIP REASONS UNREPORTED: the run line of {step.label} does not ask pytest for "
        f"the skipped tests (`-rs`), so the log shows a count at best and never the REASON -- "
        f"which is what a reader needs to tell `this platform cannot run it` from `this test "
        f"was quietly turned off`. Running line: `{run_line.strip()}`"
    )

    xml = JUNIT_XML.search(run_line)
    assert xml is not None, (
        f"CI SKIP COUNT UNREADABLE: the run line of {step.label} writes no machine-readable "
        f"result (`--junitxml=\"$FILE\"`), so the skip count would have to be parsed out of "
        f"pytest's summary line -- whose wording is a pytest-version detail, the same reason "
        f"the item count is taken from the per-item lines. Running line: `{run_line.strip()}`"
    )
    xml_var = xml.group("out")
    liveness = _guarded_branch(command, (xml_var, "testsuite"))
    assert liveness is not None and re.search(r"exit\s+(?!0\b)\S+", liveness), (
        f"CI SKIP COUNT VACUOUS: {step.label} counts skips out of ${xml_var} without first "
        f"failing on a missing or empty report, so a dropped report makes the count read 0 "
        f"and the bound below decorative. Expected an `if [ ! -s \"${xml_var}\" ] || ! grep "
        f"-q '<testsuite' \"${xml_var}\"; then ... exit 1; fi` before the count."
    )

    counter = next(
        (
            line
            for line in command.splitlines()
            if re.match(r"\s*[A-Za-z_]\w*=", line)
            and "awk" in line
            and "<skipped" in line
            and f"${xml_var}" in line
        ),
        None,
    )
    assert counter is not None, (
        f"CI SKIP COUNT MISSING: nothing in {step.label} counts the `<skipped` entries of "
        f"${xml_var}, so no skip total is ever computed and the bound is only decorative. "
        f"Expected a line like `SKIPPED=\"$(awk '/<skipped/ {{ skipped++ }} END {{ print "
        f"skipped + 0 }}' \"${xml_var}\")\"`."
    )
    counted_var = re.match(r"\s*([A-Za-z_]\w*)=", counter).group(1)

    bounded = re.search(
        r"\bif\s+\[\s*\"?\$\{?"
        + re.escape(counted_var)
        + r"\}?\"?\s+-(?P<op>gt|ge|lt|le)\s+(?P<bound>\d+)\s*\]\s*;\s*then\b"
        + r"(?P<body>(?:\n[ \t]+[^\n]*)*)",
        command,
    )
    assert bounded is not None, (
        f"CI SKIP BOUND MISSING: {step.label} counts skips into ${counted_var} but never "
        f"compares them with a literal bound -- there is no `if [ \"${counted_var}\" -gt "
        f"<max> ]; then ... exit 1` between the count and the end of the step. That "
        f"comparison is the protection: without it the count is printed for nobody and the "
        f"suite can hollow out to skips with this step green, because both gates above count "
        f"items and a skipped test is still collected."
    )
    assert bounded.group("op") in {"gt", "ge"}, (
        f"CI SKIP BOUND INVERTED: {step.label} uses `-{bounded.group('op')}` on "
        f"${counted_var}, which does not bound the skip count from above. A skip bound is "
        f"only a bound as `-gt`/`-ge` against a maximum."
    )
    assert re.search(r"exit\s+(?!0\b)\S+", bounded.group("body")), (
        f"CI SKIP BOUND DOES NOT BITE: the above-the-bound branch of {step.label} does not "
        f"exit non-zero, so more skips than allowed leaves the step green. Branch judged: "
        f"{bounded.group('body').strip()!r}"
    )
    bound = int(bounded.group("bound"))
    assert bound <= MAX_SKIPS_ALLOWED, (
        f"CI SKIP BOUND TOO HIGH: {step.label} tolerates {bound} skipped tests, above the "
        f"{MAX_SKIPS_ALLOWED} this guard allows. Measured on this tree (2026-09-18): 1 "
        f"skipped on macOS and 7 on the Linux runner, so a bound near either number is a "
        f"real bound while a bound in the hundreds is a formality. Lower the literal in the "
        f"comparison; do not raise this threshold."
    )

    captured = re.search(r"^\s*(?P<var>[A-Za-z_]\w*)=\$\?\s*$", command, re.MULTILINE)
    assert captured is not None, (
        f"CI RUN STATUS LOST: {step.label} no longer captures pytest's exit status right "
        f"after the run (`STATUS=$?`). The run line stopped being the last command in the "
        f"step when the skip accounting was added, so without the capture the step's verdict "
        f"comes from whatever ran last -- a failing suite would then exit 0. Expected a "
        f"`<VAR>=$?` on its own line directly after the run."
    )
    status_var = captured.group("var")
    assert re.search(
        r"\bexit\s+\"?\$\{?" + re.escape(status_var) + r"\}?\"?", command
    ), (
        f"CI RUN STATUS IGNORED: {step.label} captures pytest's exit status into "
        f"${status_var} but never exits with it, so a failing suite is only as red as "
        f"whatever the step does afterwards. Exit with `${status_var}` (non-zero) when it "
        f"is non-zero."
    )


def _job(job_id: str) -> Mapping[str, Any]:
    jobs = {step.job_id: step.job for step in _all_steps()}
    assert job_id in jobs, (
        f"CI gate MISSING: no `{job_id}` job in {WORKFLOW_PATH}, so nothing it is "
        f"supposed to gate runs at all. Jobs declared: {sorted(jobs)}"
    )
    return jobs[job_id]


def _assert_job_timeout(job_id: str, maximum: int, why: str) -> int:
    """A gate job with no timeout can hang until GitHub's 360-minute default."""
    timeout = _job(job_id).get("timeout-minutes")
    assert timeout is not None, (
        f"CI JOB UNBOUNDED: the `{job_id}` job declares no `timeout-minutes`, so GitHub's "
        f"default of 360 minutes applies. {why} Give the job a wall-clock bound."
    )
    assert re.fullmatch(r"\d+", str(timeout).strip()), (
        f"CI JOB TIMEOUT UNREADABLE: the `{job_id}` job declares "
        f"`timeout-minutes: {timeout!r}`, which is not a whole number of minutes."
    )
    minutes = int(str(timeout).strip())
    assert 0 < minutes <= maximum, (
        f"CI JOB TIMEOUT TOO LARGE: the `{job_id}` job allows {minutes} minutes per run. "
        f"{why} Keep it at {maximum} minutes or less."
    )
    return minutes


def test_ci_cli_ts_job_bounds_its_wall_clock() -> None:
    """A gate job with no timeout can hang until GitHub's 360-minute default."""
    _assert_job_timeout(
        "cli-ts",
        30,
        "It is the only job that installs a node + bun toolchain and then runs steps that "
        "can hang -- render tests that spawn Bun, and an install smoke that spawns a "
        "hermetic daemon -- so one blocked child turns a red gate into six hours of runner "
        "time. A healthy run is far inside this bound (the node:test suite is 205 cases in "
        "about two seconds; the build/pack/start hops dominate), so the timeout is a hang "
        "detector, not a performance gate.",
    )


def test_ci_test_job_bounds_its_wall_clock() -> None:
    """The Python job is the other one that can hang, and it had no bound either."""
    _assert_job_timeout(
        "test",
        30,
        "It installs the pinned dependency set and the project itself, then runs the "
        "governed product suite -- and a `pip install` stalled on the network or a test "
        "blocked on a socket turns a 4-minute job into six hours of runner time with no "
        "attributable failure. Measured healthy cost on this tree (2026-09-18): the product "
        "suite is 2646 items in about 3.5 minutes; the deterministic unittest step and the "
        "installs are the rest.",
    )


# --- the cli-ts gate's own entry point ---------------------------------------------------------
# The cli-ts step runs `npm run test:ci`, one hop more than the product gate has:
# ci.yml -> package.json scripts["test:ci"] -> scripts/test-ci.mjs. Every assertion above stops
# at the workflow, so that hop used to be unguarded in BOTH directions.
#
# Downward: `test:ci` could be `echo ci tests skipped` -- CI would then run zero tests and exit
# 0 while all ten wiring assertions above passed, because nothing in the repo read the script's
# CONTENT, and any other name in package.json could be swapped in for it.
#
# Upward: what the script itself collects and how long it allows. Its file list was a
# single-level `readdirSync`, so a test file added under `test/<subdir>/` and registered in
# scripts.test was run by `npm test` (an explicit list), accepted by test/test-list-guard.test.ts
# (a recursive scan) and never executed by CI; and 34 files x a 180 s per-file deadline is 102
# minutes of permitted wall clock inside a job bounded at 20, so hung files still ended as an
# anonymous cancellation and TEST_FILE_TIMEOUT_MS was checked by nothing at all. The bound that
# fixes the second one is the suite budget in the entry point (every file gets
# `min(per_file, budget left)`, unseen files are failures), asserted against the job below --
# NOT a smaller per-file deadline, which a healthy file can trip under load.
#
# The entry point is therefore parsed out of package.json and EXECUTED here (its `--list` mode
# resolves the plan and exits without running the suite), and the answers are judged against the
# files on disk, against the workflow, and against the job's own bound.
CLI_TS_ROOT = REPO_ROOT / "apps" / "cli-ts"
CLI_TS_PACKAGE = CLI_TS_ROOT / "package.json"
CLI_TS_TEST_DIR = CLI_TS_ROOT / "test"
CLI_TS_ENTRY = re.compile(r"(?:^|\s)(test/[A-Za-z0-9._/-]+\.test\.tsx?)(?=\s|$)")
CLI_TS_SCRIPT_FILE = re.compile(r"^[\w./-]+\.(?:mjs|cjs|js|ts|tsx|sh)$")
# Commands that cannot fail and cannot run anything: a `test:ci` built out of these is the
# "ci tests skipped" hole in its purest form.
SILENT_VERBS = frozenset({"echo", "true", ":", "printf", "exit", "sleep"})
# The ceiling this guard puts on the entry point's own deadlines, and the room the cli-ts job
# must keep for its install / typecheck / install-smoke steps on top of the suite's budget.
MAX_CLI_TS_PER_FILE_MS = 300_000
CLI_TS_JOB_RESERVE_MS = 300_000
_NODE = shutil.which("node")


def _cli_ts_scripts() -> Mapping[str, Any]:
    assert CLI_TS_PACKAGE.is_file(), (
        f"CLI-TS GATE MISSING: {CLI_TS_PACKAGE} is missing, so the npm script the cli-ts job "
        f"runs cannot be checked and the suite it is supposed to gate has no entry point to "
        f"judge."
    )
    manifest = json.loads(CLI_TS_PACKAGE.read_text(encoding="utf-8"))
    scripts = manifest.get("scripts")
    assert isinstance(scripts, Mapping) and scripts, (
        f"CLI-TS GATE MISSING: {CLI_TS_PACKAGE} declares no `scripts`, so `npm run test:ci` "
        f"in the cli-ts job resolves to nothing and npm would fail (or, with --if-present, "
        f"silently succeed) instead of running the suite."
    )
    return scripts


def _cli_ts_entry_argv() -> list[str]:
    """The argv `npm run test:ci` resolves to, read out of package.json."""
    command = _cli_ts_scripts().get("test:ci")
    assert isinstance(command, str) and command.strip(), (
        f"CLI-TS GATE HOLLOW: {CLI_TS_PACKAGE} has no non-empty `scripts.test:ci`. It is the "
        f"script the cli-ts job runs, so without it the job runs nothing -- and the ten "
        f"wiring assertions above all still pass, because they only know the workflow "
        f"invokes the name."
    )
    return shlex.split(command)


def _cli_ts_files_on_disk() -> list[str]:
    """Every *.test.ts(x) under apps/cli-ts/test, at any depth, as `test/<rel>`.

    Recursive on purpose: this is the criterion test/test-list-guard.test.ts uses for
    `scripts.test`, and the whole point of the assertions below is that the entry point CI runs
    agrees with it at every depth.
    """
    return sorted(
        f"test/{path.relative_to(CLI_TS_TEST_DIR).as_posix()}"
        for path in CLI_TS_TEST_DIR.rglob("*")
        if path.is_file() and re.search(r"\.test\.tsx?$", path.name)
    )


def _cli_ts_entry_plan(env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run the entry point in its `--list` mode: the real plan, without running the suite."""
    return subprocess.run(
        [*_cli_ts_entry_argv(), "--list"],
        cwd=CLI_TS_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, **(env or {})},
    )


def test_cli_ts_gate_runs_the_test_ci_entry_point() -> None:
    """ci.yml must invoke the entry point judged below -- not another script by another name."""
    steps = [step for step in _all_steps() if _runs_cli_ts_tests(step)]
    assert steps, (
        f"CI gate MISSING: the {CLI_TS_GATE} is not wired in {WORKFLOW_PATH}. Steps actually "
        f"parsed: {_describe(_all_steps())}"
    )
    invoked = {
        match.group("name")
        for step in steps
        for match in re.finditer(r"\bnpm\s+run\s+(?P<name>[A-Za-z0-9:_-]+)", step.command)
    }
    assert "test:ci" in invoked, (
        f"CLI-TS GATE UNPINNED: the cli-ts suite is run in {WORKFLOW_PATH} by "
        f"{[step.summary for step in steps]}, which invokes "
        f"{sorted(invoked) or ['<no `npm run <script>` at all>']} instead of `npm run "
        f"test:ci`. The script NAME is the join between this workflow and the entry point the "
        f"assertions below judge (its collection, its deadlines, its disk cross-check); while "
        f"ci.yml may name any other script, swapping it for one that does nothing -- and "
        f"adding that name to package.json -- leaves every wiring assertion above green. Run "
        f"`npm run test:ci`."
    )


def test_cli_ts_test_ci_entry_point_is_not_a_noop() -> None:
    """The script ci.yml runs must be a real one: it can fail, and it runs a file on disk.

    Nothing else in the repo reads this value. A `test:ci` of `echo ci tests skipped` gives
    CI a green cli-ts job that ran zero tests, and the workflow-side assertions cannot see the
    difference because they judge the workflow, not the script.
    """
    command = _cli_ts_scripts().get("test:ci")
    assert isinstance(command, str) and command.strip(), (
        f"CLI-TS GATE HOLLOW: {CLI_TS_PACKAGE} has no non-empty `scripts.test:ci`."
    )
    verbs = [
        words[0].strip("\"'")
        for statement in re.split(r"[;&|\n]+", command)
        if (words := statement.strip().split())
    ]
    assert verbs, (
        f"CLI-TS GATE HOLLOW: `test:ci` is {command!r}, which has no command in it at all."
    )
    assert any(verb not in SILENT_VERBS for verb in verbs), (
        f"CLI-TS GATE SILENT: `test:ci` is {command!r}, built only out of "
        f"{sorted(set(verbs))} -- commands that report success without running a test. CI "
        f"would then finish the cli-ts job green having executed nothing, which is the exact "
        f"failure this gate exists to prevent. Point it at a real runner."
    )
    referenced = [token for token in shlex.split(command) if CLI_TS_SCRIPT_FILE.fullmatch(token)]
    assert referenced, (
        f"CLI-TS GATE UNREADABLE: `test:ci` is {command!r}, which names no script file in "
        f"{CLI_TS_ROOT.name}/. The gate's decisions -- which files are collected, how long each "
        f"may take, whether the collection matches the files on disk -- are made by a script in "
        f"this package (scripts/test-ci.mjs), and this guard drives that script to check them. "
        f"An entry point that is not a file here cannot be judged, so it is rejected rather "
        f"than trusted."
    )
    for relative in referenced:
        assert (CLI_TS_ROOT / relative).is_file(), (
            f"CLI-TS GATE DANGLING: `test:ci` is {command!r}, but "
            f"{CLI_TS_ROOT / relative} does not exist, so the script CI runs is a path that "
            f"resolves to nothing (npm exits 1, and the suite never runs)."
        )


@pytest.mark.skipif(
    _NODE is None,
    reason="needs node to execute the cli-ts entry point; the cli-ts job runs the same script",
)
def test_cli_ts_entry_point_collects_every_test_file_on_disk() -> None:
    """The files CI executes must be the files on disk -- at every depth, both directions.

    A single-level `readdirSync` failed this silently: `test/<subdir>/x.test.ts` was on disk,
    registered in scripts.test, run by `npm test` and accepted by test/test-list-guard.test.ts
    (which scans recursively), while `npm run test:ci` -- the command CI actually runs -- never
    executed it. Judging the entry point's own answer against a recursive scan is what makes
    that red instead of a green CI that skipped a file.
    """
    result = _cli_ts_entry_plan()
    assert result.returncode == 0, (
        f"CLI-TS ENTRY POINT FAILED: `{_cli_ts_entry_argv()!r} --list` exited "
        f"{result.returncode}. stdout: {result.stdout[-2000:]!r} stderr: "
        f"{result.stderr[-2000:]!r}"
    )
    plan = json.loads(result.stdout)
    listed = list(plan["files"])
    on_disk = _cli_ts_files_on_disk()
    registered = list(CLI_TS_ENTRY.findall(str(_cli_ts_scripts().get("test", ""))))

    assert on_disk, (
        f"CLI-TS DISK SCAN BROKEN: no *.test.ts(x) found under {CLI_TS_TEST_DIR}, so the "
        f"comparison below would be vacuous."
    )
    not_run = sorted(set(on_disk) - set(listed))
    not_on_disk = sorted(set(listed) - set(on_disk))
    assert not not_run and not not_on_disk, (
        f"CLI-TS FILE SET MISMATCH: the entry point CI runs would execute {len(listed)} "
        f"files, but {len(on_disk)} *.test.ts(x) exist under {CLI_TS_TEST_DIR}. On disk and "
        f"not run: {not_run} | run but not on disk: {not_on_disk}. A file in the first list is "
        f"a test that no CI run executes -- the collection must descend into every "
        f"subdirectory, exactly as test/test-list-guard.test.ts does when it pins "
        f"scripts.test."
    )
    assert listed == registered, (
        f"CLI-TS ENTRY POINT DIVERGES from scripts.test: the entry point would run "
        f"{len(listed)} files where apps/cli-ts/package.json scripts.test names "
        f"{len(registered)}. Only in scripts.test: {sorted(set(registered) - set(listed))} | "
        f"only in the entry point: {sorted(set(listed) - set(registered))}. Running a "
        f"different list than `npm test` does is how a file ends up executed locally and "
        f"skipped by CI (or the reverse); the two must be the same list."
    )
    assert len(listed) == len(set(listed)), (
        f"CLI-TS ENTRY POINT REPEATS FILES: {len(listed)} entries, {len(set(listed))} distinct."
    )
    assert sorted(registered) == on_disk, (
        f"CLI-TS FILE SET MISMATCH: apps/cli-ts/package.json scripts.test names "
        f"{len(registered)} files, but {len(on_disk)} *.test.ts(x) exist under "
        f"{CLI_TS_TEST_DIR}. Not registered (npm test would never run them): "
        f"{sorted(set(on_disk) - set(registered))} | registered but missing on disk: "
        f"{sorted(set(registered) - set(on_disk))}."
    )
    for relative in listed:
        assert (CLI_TS_ROOT / relative).is_file(), (
            f"CLI-TS FILE SET DANGLING: the entry point would run {relative!r}, which is not "
            f"a file under {CLI_TS_ROOT}."
        )


@pytest.mark.skipif(
    _NODE is None,
    reason="needs node to execute the cli-ts entry point; the cli-ts job runs the same script",
)
def test_cli_ts_entry_point_bounds_every_deadline_inside_the_job() -> None:
    """The step's wall clock must be bounded by the suite budget, inside the job's bound.

    A per-file deadline is what turns a hang into an attributable failure, and it is also what
    decides how long a hang is PERMITTED to last: 34 files x 180 s is 102 minutes of permitted
    wall clock inside a job bounded at 20, so seven hung files still ended as the anonymous
    cancellation the deadlines were meant to replace. The bound that fixes it is the suite
    budget -- every file gets `min(per_file, budget left)` and the unseen files are reported as
    failures -- so what has to stay under the job's bound is the WORST CASE the entry point
    reports, with room left for the job's other steps (install, typecheck, install smoke).

    The withdrawn alternative is asserted against below too: deriving per_file as
    `budget / file count` (21 s for 34 files) makes a healthy `test/controller.test.ts` fail as
    a hang under load, measured on this tree (2026-09-18) at load average 8.
    """
    job_minutes = _assert_job_timeout(
        "cli-ts",
        30,
        "It runs the cli-ts suite through per-file deadlines, so this job's bound is the "
        "wall clock those deadlines have to fit inside.",
    )
    job_ms = job_minutes * 60_000
    result = _cli_ts_entry_plan()
    assert result.returncode == 0, (
        f"CLI-TS ENTRY POINT FAILED: `{_cli_ts_entry_argv()!r} --list` exited "
        f"{result.returncode}. stdout: {result.stdout[-2000:]!r} stderr: "
        f"{result.stderr[-2000:]!r}"
    )
    plan = json.loads(result.stdout)
    file_count = int(plan["fileCount"])
    per_file = int(plan["perFileTimeoutMs"])
    budget = int(plan["suiteBudgetMs"])
    worst_case = int(plan["worstCaseSuiteMs"])

    assert file_count == len(list(plan["files"])) > 0, (
        f"CLI-TS PLAN INCONSISTENT: the entry point reports fileCount={file_count} for "
        f"{len(list(plan['files']))} files."
    )
    assert 0 < per_file <= MAX_CLI_TS_PER_FILE_MS, (
        f"CLI-TS PER-FILE DEADLINE UNBOUNDED: the entry point would give each test file "
        f"{per_file} ms, above the {MAX_CLI_TS_PER_FILE_MS} ms this guard allows. Every file "
        f"that hangs is given that long, so the deadline is a bound on how long a broken run "
        f"may take before the suite budget stops it."
    )
    assert per_file <= budget, (
        f"CLI-TS PER-FILE DEADLINE OUTLIVES THE SUITE: the entry point would let one file run "
        f"for {per_file} ms inside a {budget} ms suite budget. A per-file deadline longer than "
        f"the budget means a single hanging file consumes the whole suite's allowance, so no "
        f"other file's failure can be attributed."
    )
    assert worst_case == min(file_count * per_file, budget), (
        f"CLI-TS PLAN INCONSISTENT: the entry point reports a worst case of {worst_case} ms for "
        f"{file_count} files x {per_file} ms inside a {budget} ms budget. The worst case is "
        f"what this guard compares against the job, so it must be the product of the two, "
        f"capped by the budget the run actually enforces."
    )
    assert worst_case <= budget, (
        f"CLI-TS DEADLINES OUTGROW THE SUITE: the entry point's worst case is {worst_case} ms, "
        f"above the {budget} ms suite budget it claims to enforce. The per-file deadline must be "
        f"clamped by the budget still unspent, or a suite of hung files runs for hours while "
        f"reporting each hang as a timeout -- and the files it never reached are lost."
    )
    assert worst_case < job_ms, (
        f"CLI-TS DEADLINES OUTGROW THE JOB: the entry point's worst case is {worst_case} ms, at "
        f"or above the cli-ts job's own {job_ms} ms (timeout-minutes: {job_minutes}). The "
        f"deadlines decide how long the runner is busy, so the worst case has to fit inside the "
        f"bound that is supposed to end the job -- otherwise hung files still end as an "
        f"anonymous cancellation at the job limit."
    )
    assert budget <= job_ms - CLI_TS_JOB_RESERVE_MS, (
        f"CLI-TS SUITE BUDGET OUTGROWS THE JOB: the entry point budgets {budget} ms for the "
        f"suite inside the cli-ts job's {job_ms} ms (timeout-minutes: {job_minutes}), leaving "
        f"{job_ms - budget} ms for the install, typecheck and install-smoke steps. Those need "
        f"at least {CLI_TS_JOB_RESERVE_MS} ms; lower the budget or raise the job's "
        f"timeout-minutes deliberately, in review."
    )


@pytest.mark.skipif(
    _NODE is None,
    reason="needs node to execute the cli-ts entry point; the cli-ts job runs the same script",
)
def test_cli_ts_entry_point_clamps_each_file_to_the_budget_left() -> None:
    """The worst case is only real while each file's deadline is clamped by the budget left.

    This is the one assertion in this group made on the entry point's SOURCE, and the reason is
    that no cheap behaviour probe can see the difference: firing it requires a test file that is
    still running when the suite budget expires, and the only files on disk finish in seconds.
    The probe above proves the accounting around the budget (nothing runs, everything is
    reported as never-run, exit non-zero); this asserts the clamp that makes the reported worst
    case -- and the job-level bound computed from it -- true. Without it a single hung file is
    given its full per-file deadline even when the suite has already spent its budget, which is
    the arrangement this whole bound exists to replace.
    """
    source = (CLI_TS_ROOT / "scripts" / "test-ci.mjs").read_text(encoding="utf-8")
    assert re.search(r"const remaining = deadline - Date\.now\(\)", source), (
        "CLI-TS SUITE BUDGET UNTRACKED: apps/cli-ts/scripts/test-ci.mjs no longer computes how "
        "much of the suite budget is left before running each file, so there is nothing for a "
        "file's deadline to be clamped to."
    )
    assert re.search(r"if\s*\(\s*remaining\s*<=\s*0\s*\)", source), (
        "CLI-TS SUITE BUDGET UNENFORCED: apps/cli-ts/scripts/test-ci.mjs no longer has a branch "
        "for an exhausted suite budget, so the files that never ran are not reported -- a "
        "truncated run would look like a complete one."
    )
    assert re.search(r"\brun\(\s*file\s*,\s*Math\.min\(\s*perFileMs\s*,\s*remaining\s*\)\s*\)", source), (
        "CLI-TS SUITE BUDGET NOT CLAMPED: apps/cli-ts/scripts/test-ci.mjs runs each file with "
        "its full per-file deadline instead of `Math.min(perFileMs, remaining)`, so the suite "
        "can spend more wall clock than TEST_SUITE_BUDGET_MS allows -- and the worst case this "
        "guard compares against the cli-ts job's timeout-minutes would be a number the run does "
        "not honour."
    )


@pytest.mark.skipif(
    _NODE is None,
    reason="needs node to execute the cli-ts entry point; the cli-ts job runs the same script",
)
def test_cli_ts_entry_point_stops_at_the_suite_budget_and_reports_the_rest_as_failures() -> None:
    """The budget must be ENFORCED, and a file that never ran must not count as a pass.

    Everything above judges the numbers the entry point reports about itself; this one drives
    it. With a 1 ms budget the loop has no time left before its first file, so a correct entry
    point runs nothing, names every file as never-run, and exits non-zero -- there is no way to
    report success for a suite it did not run. (1 ms is the budget bound's floor on purpose; see
    the constants in apps/cli-ts/scripts/test-ci.mjs.)
    """
    result = subprocess.run(
        _cli_ts_entry_argv(),
        cwd=CLI_TS_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "TEST_SUITE_BUDGET_MS": "1"},
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, (
        f"CLI-TS SUITE BUDGET IGNORED: the entry point exited 0 with a 1 ms suite budget, so "
        f"the budget does not stop the run -- or a suite that ran out of budget is reported as "
        f"success. Output: {output[-1500:]!r}"
    )
    assert "NOT RUN" in output, (
        f"CLI-TS SUITE BUDGET UNREPORTED: the entry point burned through its 1 ms budget "
        f"without naming the files it never reached, so a truncated run is indistinguishable "
        f"from a full one to whoever reads the log. Output: {output[-1500:]!r}"
    )
    assert "all test files passed" not in output, (
        f"CLI-TS SUITE BUDGET IGNORED: the entry point printed 'all test files passed' with a "
        f"1 ms budget and files it never ran. Output: {output[-1500:]!r}"
    )


@pytest.mark.skipif(
    _NODE is None,
    reason="needs node to execute the cli-ts entry point; the cli-ts job runs the same script",
)
def test_cli_ts_entry_point_rejects_an_unbounded_deadline_override() -> None:
    """TEST_FILE_TIMEOUT_MS / TEST_SUITE_BUDGET_MS must be rejected, not clamped.

    These are the knobs the previous revision left unchecked: any value was accepted, so the
    bound the assertions above compute from the plan is only worth something while an
    out-of-range override fails the run instead of quietly becoming the runtime's deadline.
    """
    for name, value in (
        ("TEST_FILE_TIMEOUT_MS", "999999999"),
        ("TEST_FILE_TIMEOUT_MS", "0"),
        ("TEST_FILE_TIMEOUT_MS", "-1"),
        ("TEST_FILE_TIMEOUT_MS", "not-a-number"),
        ("TEST_SUITE_BUDGET_MS", "999999999"),
        ("TEST_SUITE_BUDGET_MS", "0"),
    ):
        result = _cli_ts_entry_plan({name: value})
        assert result.returncode != 0, (
            f"CLI-TS DEADLINE OVERRIDE UNCHECKED: the entry point accepted {name}={value!r} "
            f"(exit 0). An unbounded per-file deadline is how a hang turns into an anonymously "
            f"cancelled job, and a bound that any environment variable can move is not a "
            f"bound: the value must be rejected, not clamped. stdout: "
            f"{result.stdout[-500:]!r} stderr: {result.stderr[-500:]!r}"
        )


# --- the cli-ts frame-check gate ----------------------------------------------------------------
# The cli-ts job's node:test suite never opens a pty. The TUI's terminal-level claims -- key
# handling, modal layers, the theme actually repainting, the composer invariants, the home panel,
# search, syntax highlighting -- are established by scripts/pty_*.py, and until this gate was wired
# NONE of those scripts ran in CI: the typecheck only reads types, the two render tests in the
# node:test suite write into a pipe, and the install smoke drives the entry headlessly
# (`--output-format json`). A rendering or key-handling regression could therefore ship with every
# step green.
#
# The wiring is one hop longer again than test:ci's -- ci.yml -> package.json
# `scripts["check:frames:ci"]` -> scripts/pty-ci.mjs -> one bounded process per check -- so each hop
# is judged separately, and so is the CLASSIFICATION that keeps the coverage honest. The entry point
# runs only the checks that can fail (each exits non-zero on a failed assertion) and must reject any
# `scripts/pty_*.py` that nobody classified, so a new frame check cannot silently stay out of both
# the CI set and the local `check:frames` set.
FRAME_SCRIPTS_DIR = CLI_TS_ROOT / "scripts"
FRAME_ENTRY_SCRIPT = "scripts/pty-ci.mjs"
FRAME_CI_SCRIPT = "check:frames:ci"
FRAME_LOCAL_SCRIPT = "check:frames"
# What those two npm scripts must resolve to: the gate set, and the whole on-disk set.
FRAME_CI_SCRIPT_VALUE = f"node {FRAME_ENTRY_SCRIPT}"
FRAME_LOCAL_SCRIPT_VALUE = f"node {FRAME_ENTRY_SCRIPT} --all"
# The step's own command. Env assignments in front are allowed (a deliberate budget change is a
# review decision), but the invocation itself must be exactly this: `--all`, an extra `--` argument,
# a `-k`-style filter, a file list or a different script would all change WHICH checks CI runs while
# the step still looks present.
_FRAME_CI_INVOCATION = re.compile(r"^(?:[A-Za-z_]\w*=\S*\s+)*npm\s+run\s+check:frames:ci$")
# A path that can end the process non-zero: the property that separates a gate from a frame dump.
_FRAME_EXIT_PATH = re.compile(r"\b(?:sys\.exit|SystemExit)\b")
# The floor on the number of CI gates. Measured 11 gates / 15 checks on disk (2026-09-19) and the
# largest single check is one file, so this notices a collapse rather than a deliberate retirement;
# the disk/classification comparison and the exit-path invariant below are what notice the smaller
# movements. Like FLOOR_MINIMUM above, it is a round bound and must not be re-tightened to the
# measured count.
FRAME_GATES_FLOOR = 10
MAX_PTY_PER_CHECK_MS = 300_000


def _runs_cli_ts_frame_checks(step: Step) -> bool:
    """The TUI frame checks: the pty checks driven through scripts/pty-ci.mjs."""
    if not _is_cli_ts_scoped(step):
        return False
    return bool(
        re.search(r"\bnpm\s+run\s+check:frames:ci\b", step.command)
        or re.search(r"\bpty-ci\.mjs\b", step.command)
    )


def _pty_checks_on_disk() -> list[str]:
    """Every scripts/pty_*.py under apps/cli-ts/scripts, at any depth."""
    return sorted(
        f"scripts/{path.relative_to(FRAME_SCRIPTS_DIR).as_posix()}"
        for path in FRAME_SCRIPTS_DIR.rglob("pty_*.py")
        if path.is_file()
    )


def _frame_script_value(name: str) -> str:
    value = _cli_ts_scripts().get(name)
    assert isinstance(value, str) and value.strip(), (
        f"CLI-TS FRAME GATE MISSING: {CLI_TS_PACKAGE} has no non-empty `scripts.{name}`. That "
        f"script is the join between ci.yml and the entry point the assertions below judge, so "
        f"without it the step runs nothing -- or, with --if-present, silently succeeds."
    )
    return value


def _frame_entry_argv(name: str = FRAME_CI_SCRIPT) -> list[str]:
    return shlex.split(_frame_script_value(name))


def _frame_entry_plan(
    name: str = FRAME_CI_SCRIPT,
    *extra: str,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the frame-check entry point in `--list` mode: the real plan, without running checks."""
    return subprocess.run(
        [*_frame_entry_argv(name), *extra, "--list"],
        cwd=CLI_TS_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, **(env or {})},
    )


def _frame_plan(
    name: str = FRAME_CI_SCRIPT,
    *extra: str,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    result = _frame_entry_plan(name, *extra, env=env)
    assert result.returncode == 0, (
        f"CLI-TS FRAME ENTRY POINT FAILED: `{_frame_entry_argv(name) + list(extra)} --list` exited "
        f"{result.returncode}. stdout: {result.stdout[-2000:]!r} stderr: {result.stderr[-2000:]!r}"
    )
    return json.loads(result.stdout)


def test_ci_workflow_still_runs_the_cli_ts_frame_checks() -> None:
    """The pty frame checks must be a CI step, and the step must run the whole CI set."""
    steps = _all_steps()
    _assert_gate_runs(
        steps,
        f"{CLI_TS_GATE} (TUI frame checks)",
        _runs_cli_ts_frame_checks,
        "a step in the apps/cli-ts scope running `npm run check:frames:ci` "
        "(`node scripts/pty-ci.mjs`, one bounded process per pty check). Without it the TUI's "
        "only frame-level evidence -- key handling, modal layers, the theme repainting, the "
        "composer invariants, the home panel, search, syntax highlighting -- is unenforced: no "
        "other CI step opens a pty at all",
    )
    matches = [step for step in steps if _runs_cli_ts_frame_checks(step)]
    assert len(matches) == 1, (
        f"CI FRAME GATE DUPLICATED: {len(matches)} steps in {WORKFLOW_PATH} drive "
        f"{FRAME_ENTRY_SCRIPT}: {[step.summary for step in matches]}. The suite has one budget "
        f"and one set of deadlines; two steps would run the checks twice and each would still "
        f"look normal."
    )
    step = matches[0]
    lines = [line.strip() for line in step.command.splitlines() if line.strip()]
    assert lines and _FRAME_CI_INVOCATION.fullmatch(lines[-1]), (
        f"CI FRAME GATE NARROWED: {step.label} ends with "
        f"{lines[-1] if lines else '<no command>'!r}, not "
        f"`npm run check:frames:ci`. The step must run the checks the entry point's own CI set "
        f"names -- not a subset, a single file or a second runner -- because the deadlines, the "
        f"budget and the on-disk cross-check all belong to that entry point."
    )


def test_cli_ts_frame_check_scripts_are_wired_to_the_entry_point() -> None:
    """Both frame-check scripts must point at the entry point, one CI set and one whole set."""
    for name, expected in (
        (FRAME_CI_SCRIPT, FRAME_CI_SCRIPT_VALUE),
        (FRAME_LOCAL_SCRIPT, FRAME_LOCAL_SCRIPT_VALUE),
    ):
        value = _frame_script_value(name)
        verbs = [
            words[0].strip("\"'")
            for statement in re.split(r"[;&|\n]+", value)
            if (words := statement.strip().split())
        ]
        assert any(verb not in SILENT_VERBS for verb in verbs), (
            f"CLI-TS FRAME GATE SILENT: `{name}` is {value!r}, built only out of "
            f"{sorted(set(verbs))} -- commands that report success without running a check. "
            f"`{FRAME_LOCAL_SCRIPT}` is how a developer runs the whole set and "
            f"`{FRAME_CI_SCRIPT}` is what the cli-ts job runs; either one being a no-op leaves "
            f"the frame layer unenforced while the step stays green."
        )
        assert value.strip() == expected, (
            f"CLI-TS FRAME GATE MISWIRED: `{name}` is {value!r}, not {expected!r}. "
            f"`{FRAME_LOCAL_SCRIPT}` must run the WHOLE on-disk set (`--all`) and "
            f"`{FRAME_CI_SCRIPT}` must run the gate set: swapping them or adding arguments "
            f"changes which checks CI executes without changing the step that looks present."
        )
    assert (CLI_TS_ROOT / FRAME_ENTRY_SCRIPT).is_file(), (
        f"CLI-TS FRAME GATE DANGLING: both scripts run `{FRAME_ENTRY_SCRIPT}`, which does not "
        f"exist under {CLI_TS_ROOT}."
    )


@pytest.mark.skipif(
    _NODE is None,
    reason="needs node to execute the frame-check entry point; the cli-ts job runs the same script",
)
def test_cli_ts_frame_checks_cover_every_check_on_disk() -> None:
    """Every scripts/pty_*.py must be in the CI set or be a documented non-gate.

    This is the assertion that keeps the coverage from staying partial: a check that lands on
    disk unclassified (or classified and then deleted) is a frame claim nobody runs, and the
    entry point refuses to run at all in that state.
    """
    ci = _frame_plan()
    everything = _frame_plan(FRAME_CI_SCRIPT, "--all")
    on_disk = _pty_checks_on_disk()
    assert on_disk, (
        f"CLI-TS FRAME DISK SCAN BROKEN: no scripts/pty_*.py found under {FRAME_SCRIPTS_DIR}, so "
        f"the comparison below would be vacuous."
    )
    for plan, label in ((ci, FRAME_CI_SCRIPT), (everything, FRAME_LOCAL_SCRIPT)):
        assert list(plan["allChecks"]) == on_disk, (
            f"CLI-TS FRAME COVERAGE MISMATCH: `{label}` reports "
            f"{len(list(plan['allChecks']))} checks where {len(on_disk)} scripts/pty_*.py exist. "
            f"Only on disk: {sorted(set(on_disk) - set(plan['allChecks']))} | only in the plan: "
            f"{sorted(set(plan['allChecks']) - set(on_disk))}."
        )
    assert everything["mode"] == "all" and list(everything["files"]) == on_disk, (
        f"CLI-TS FRAME LOCAL SET INCOMPLETE: `npm run {FRAME_LOCAL_SCRIPT}` would run "
        f"{list(everything['files'])} (mode {everything['mode']!r}) where the full set on disk is "
        f"{on_disk}. The local entry point is the whole set by definition: it is where a check "
        f"that cannot be a gate is still exercised."
    )
    assert ci["mode"] == "ci", (
        f"CLI-TS FRAME CI SET UNMARKED: the CI plan reports mode {ci['mode']!r}, so the plan "
        f"cannot be told apart from a whole-set run."
    )
    gates = list(ci["ciChecks"])
    assert sorted(gates) == sorted(ci["files"]), (
        f"CLI-TS FRAME CI SET DIVERGES: the step would run {sorted(ci['files'])} where the "
        f"declared gate set is {sorted(gates)}."
    )
    evidence = list(ci["evidenceOnly"])
    reasons = {entry["file"]: entry["why"] for entry in evidence}
    assert len(reasons) == len(evidence), (
        f"CLI-TS FRAME CLASSIFICATION REPEATED: {len(evidence)} entries but {len(reasons)} "
        f"distinct files: {[entry['file'] for entry in evidence]}."
    )
    assert not (set(gates) & set(reasons)), (
        f"CLI-TS FRAME CLASSIFICATION CONTRADICTORY: {sorted(set(gates) & set(reasons))} is "
        f"listed both as a CI gate and as an evidence-only check."
    )
    assert sorted(set(gates) | set(reasons)) == on_disk, (
        f"CLI-TS FRAME CLASSIFICATION INCOMPLETE: gates + evidence-only = "
        f"{sorted(set(gates) | set(reasons))} where the checks on disk are {on_disk}. A check in "
        f"neither list is run by no entry point (`check:frames` is the whole set); a check in "
        f"both would have to be a gate and not a gate."
    )
    for file, why in reasons.items():
        assert file in on_disk, (
            f"CLI-TS FRAME CLASSIFICATION DANGLING: {file} is classified as evidence-only but is "
            f"not a script on disk."
        )
        assert isinstance(why, str) and len(why.split()) >= 8, (
            f"CLI-TS FRAME EXCLUSION UNREASONED: {file} is kept out of CI with {why!r}. The "
            f"reason is the record that says why this TUI claim is not enforced; write what the "
            f"check prints and what it lacks (a verdict, an exit path, env-gated instrumentation)."
        )
    assert ci["fileCount"] == len(gates) == len(list(ci["files"])) >= FRAME_GATES_FLOOR, (
        f"CLI-TS FRAME GATE SET TOO SMALL: the CI set is {len(gates)} checks "
        f"(fileCount {ci['fileCount']}), below the floor of {FRAME_GATES_FLOOR}. Measured 11 "
        f"gates / 15 checks on disk (2026-09-19); the largest single check is one file, so a set "
        f"this small means checks were deleted or downgraded rather than retired in review."
    )


@pytest.mark.skipif(
    _NODE is None,
    reason="needs node to execute the frame-check entry point; the cli-ts job runs the same script",
)
def test_cli_ts_frame_check_classification_matches_its_exit_path() -> None:
    """A gate must be able to fail; an evidence-only check must not be able to.

    The classification above is only worth something while it says something true about the
    scripts. A check listed as a gate that has no `sys.exit`/`SystemExit` path cannot go red, so
    the step looks enforced while the claim is not -- and the mirror case is a check filed as
    evidence-only which HAS gained a verdict, i.e. a gate kept out of CI for no reason.
    """
    plan = _frame_plan()
    gates = list(plan["ciChecks"])
    evidence = list(plan["evidenceOnly"])
    assert gates and evidence, (
        f"CLI-TS FRAME CLASSIFICATION VACUOUS: {len(gates)} gates and {len(evidence)} "
        f"evidence-only checks, so the invariant below would only be half-checked."
    )
    for file in gates:
        path = CLI_TS_ROOT / file
        assert path.is_file(), f"CLI-TS FRAME GATE DANGLING: {file} is not a file under {CLI_TS_ROOT}."
        source = path.read_text(encoding="utf-8")
        assert _FRAME_EXIT_PATH.search(source), (
            f"FRAME GATE CANNOT FAIL: {file} is in the CI gate set but has no `sys.exit`/"
            f"`SystemExit` path, so the cli-ts step stays green through the very regression this "
            f"check is supposed to catch. Give it a verdict that changes the exit status, or move "
            f"it to the evidence-only list with its reason."
        )
    for entry in evidence:
        file = entry["file"]
        path = CLI_TS_ROOT / file
        assert path.is_file(), (
            f"CLI-TS FRAME CLASSIFICATION DANGLING: {file} is not a file under {CLI_TS_ROOT}."
        )
        source = path.read_text(encoding="utf-8")
        assert not _FRAME_EXIT_PATH.search(source), (
            f"FRAME CHECK MISCLASSIFIED: {file} is listed as evidence-only ({entry['why']!r}) but "
            f"its source has an exit path, so it CAN fail a run. Move it into the CI gate set and "
            f"drop the reason: leaving a working check out of CI is how the frame layer stays "
            f"partly unenforced after someone takes the trouble to fix it."
        )


@pytest.mark.skipif(
    _NODE is None,
    reason="needs node to execute the frame-check entry point; the cli-ts job runs the same script",
)
def test_cli_ts_frame_check_deadlines_stay_inside_the_job() -> None:
    """The frame suite's worst case, plus test:ci's, must fit the cli-ts job with a reserve.

    The frame checks are the third thing in this job that can hang, after the node:test suite and
    the install smoke. Their deadlines decide how long the runner is busy, so they have to fit
    inside the bound that is supposed to end the job -- with room left for the install, the
    typecheck and the install smoke, which is the reserve test:ci's own budget is already held to.
    """
    job_minutes = _assert_job_timeout(
        "cli-ts",
        30,
        "It runs the frame-check suite through per-check deadlines, so this job's bound is the "
        "wall clock those deadlines have to fit inside, next to test:ci's own budget.",
    )
    job_ms = job_minutes * 60_000
    test_ci_budget = int(json.loads(_cli_ts_entry_plan().stdout)["suiteBudgetMs"])
    plan = _frame_plan()
    file_count = int(plan["fileCount"])
    per_check = int(plan["perCheckTimeoutMs"])
    budget = int(plan["suiteBudgetMs"])
    worst_case = int(plan["worstCaseSuiteMs"])

    assert file_count == len(list(plan["files"])) > 0, (
        f"CLI-TS FRAME PLAN INCONSISTENT: the entry point reports fileCount={file_count} for "
        f"{len(list(plan['files']))} checks."
    )
    assert 0 < per_check <= MAX_PTY_PER_CHECK_MS, (
        f"CLI-TS FRAME PER-CHECK DEADLINE UNBOUNDED: the entry point would give each frame check "
        f"{per_check} ms, above the {MAX_PTY_PER_CHECK_MS} ms this guard allows. Every check that "
        f"hangs is given that long, so the deadline bounds how long a broken run may take before "
        f"the suite budget stops it."
    )
    assert per_check <= budget, (
        f"CLI-TS FRAME PER-CHECK DEADLINE OUTLIVES THE SUITE: one check may run for {per_check} ms "
        f"inside a {budget} ms suite budget, so a single hanging check consumes the whole suite's "
        f"allowance and no other check's failure can be attributed."
    )
    assert worst_case == min(file_count * per_check, budget), (
        f"CLI-TS FRAME PLAN INCONSISTENT: the entry point reports a worst case of {worst_case} ms "
        f"for {file_count} checks x {per_check} ms inside a {budget} ms budget. The worst case is "
        f"what this guard compares against the job, so it must be the product of the two, capped "
        f"by the budget the run actually enforces."
    )
    assert worst_case <= budget < job_ms, (
        f"CLI-TS FRAME DEADLINES OUTGROW THE JOB: the frame suite's worst case is {worst_case} ms "
        f"inside a {budget} ms budget and the cli-ts job's own bound is {job_ms} ms "
        f"(timeout-minutes: {job_minutes}). Hung checks would still end as an anonymous "
        f"cancellation at the job limit."
    )
    assert budget + test_ci_budget + CLI_TS_JOB_RESERVE_MS <= job_ms, (
        f"CLI-TS FRAME SUITE BUDGET OUTGROWS THE JOB: the frame suite budgets {budget} ms and "
        f"test:ci already claims {test_ci_budget} ms inside the cli-ts job's {job_ms} ms "
        f"(timeout-minutes: {job_minutes}), leaving {job_ms - budget - test_ci_budget} ms for the "
        f"install, typecheck and install-smoke steps. Those need at least {CLI_TS_JOB_RESERVE_MS} "
        f"ms; lower a suite budget or raise the job's timeout-minutes deliberately, in review."
    )


@pytest.mark.skipif(
    _NODE is None,
    reason="needs node to execute the frame-check entry point; the cli-ts job runs the same script",
)
def test_cli_ts_frame_check_suite_budget_is_enforced_and_reported() -> None:
    """The frame budget must be ENFORCED, and a check that never ran must not count as a pass.

    Everything above judges the numbers the entry point reports about itself; this one drives it.
    With a 1 ms budget the loop has no time left before its first check, so a correct entry point
    runs nothing, names every check as never-run, and exits non-zero -- there is no way to report
    success for a suite it did not run.
    """
    result = subprocess.run(
        _frame_entry_argv(),
        cwd=CLI_TS_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PTY_SUITE_BUDGET_MS": "1"},
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0, (
        f"CLI-TS FRAME BUDGET IGNORED: the frame entry point exited 0 with a 1 ms suite budget, so "
        f"the budget does not stop the run -- or a suite that ran out of budget is reported as "
        f"success. Output: {output[-1500:]!r}"
    )
    assert "NOT RUN" in output, (
        f"CLI-TS FRAME BUDGET UNREPORTED: the entry point burned through its 1 ms budget without "
        f"naming the checks it never reached, so a truncated run is indistinguishable from a full "
        f"one to whoever reads the log. Output: {output[-1500:]!r}"
    )
    assert "all frame checks passed" not in output, (
        f"CLI-TS FRAME BUDGET IGNORED: the entry point printed 'all frame checks passed' with a "
        f"1 ms budget and checks it never ran. Output: {output[-1500:]!r}"
    )


@pytest.mark.skipif(
    _NODE is None,
    reason="needs node to execute the frame-check entry point; the cli-ts job runs the same script",
)
def test_cli_ts_frame_check_entry_point_rejects_an_unbounded_deadline() -> None:
    """PTY_CHECK_TIMEOUT_MS / PTY_SUITE_BUDGET_MS must be rejected, not clamped.

    The same rule as test:ci's knobs, and one more case: a budget above the ceiling the job can
    afford (the reserve the assertion above computes) must be rejected too, or an environment
    variable could move the bound the wiring test just proved.
    """
    for name, value in (
        ("PTY_CHECK_TIMEOUT_MS", "999999999"),
        ("PTY_CHECK_TIMEOUT_MS", "0"),
        ("PTY_CHECK_TIMEOUT_MS", "-1"),
        ("PTY_CHECK_TIMEOUT_MS", "not-a-number"),
        ("PTY_SUITE_BUDGET_MS", "999999999"),
        ("PTY_SUITE_BUDGET_MS", "0"),
        ("PTY_SUITE_BUDGET_MS", "720001"),
    ):
        result = _frame_entry_plan(FRAME_CI_SCRIPT, env={name: value})
        assert result.returncode != 0, (
            f"CLI-TS FRAME DEADLINE OVERRIDE UNCHECKED: the frame entry point accepted "
            f"{name}={value!r} (exit 0). An unbounded per-check deadline is how a hang turns into "
            f"an anonymously cancelled job, and a suite budget that any environment variable can "
            f"raise is not a bound: the value must be rejected, not clamped. stdout: "
            f"{result.stdout[-500:]!r} stderr: {result.stderr[-500:]!r}"
        )
