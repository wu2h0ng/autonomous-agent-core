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
# The explicit exemption list: one literal basename at a time, never a pattern.
_ALLOWLIST = re.compile(r"^\s*ALLOWED_UNCOLLECTED=(?P<value>.*)$", re.MULTILINE)
_ALLOWED_ENTRY = re.compile(r"[A-Za-z0-9_.-]+")


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
        """The command with everything that cannot change WHAT runs normalised away."""
        text = re.sub(r"^\s*if\s+!\s*", "", self.line)
        text = re.sub(r";\s*then\s*$", "", text)
        text = re.sub(r"\s*>\s*\S+\s*$", "", text)
        text = re.sub(r"--collect-only\b", " ", text)
        return " ".join(text.split())


def _pytest_invocations(command: str) -> list[PytestInvocation]:
    """Every pytest line in a run block, with the positional (target) words it names."""
    invocations: list[PytestInvocation] = []
    for line in command.splitlines():
        match = re.search(r"\bpytest\b(.*)$", line)
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


def test_ci_gate_steps_are_not_softened() -> None:
    steps = _all_steps()
    gated = [
        step
        for step in steps
        if _runs_product_suite(step)
        or _runs_cli_ts_tests(step)
        or _runs_cli_ts_typecheck(step)
        or _runs_cli_ts_install_smoke(step)
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
        f"more place where a wildcard can hide; write the file names out."
    )
    entries = literal.group("inner").split()
    for entry in entries:
        assert _ALLOWED_ENTRY.fullmatch(entry), (
            f"CI FILE-SET GATE EXEMPTION TOO BROAD: {step.label} exempts {entry!r} via "
            f"ALLOWED_UNCOLLECTED, but an entry must be one literal file name. A glob "
            f"(`*`, `test_*`) or a path prefix exempts every module it matches from the "
            f"disk/collection comparison -- the wildcard would silently restore exactly "
            f"the hole this gate closes. Exempt one file at a time, each with its reason "
            f"in the comment above the list. Entries judged: {entries}"
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
