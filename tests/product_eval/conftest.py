"""Session isolation for the product-evaluation suite.

The frozen SPINE arms take their provider configuration from the process
environment, because that is where ``AgentOSApplication`` reads it. A test (or a
harness entry point it drives) that writes those variables and does not undo the
write leaves every later test in the same pytest process pointed at a loopback
endpoint that has already been closed -- so the suite's result depends on the
order the files happen to be collected in.

The scoped helper ``provider_environment`` is the fix; this fixture is the
backstop that keeps the guarantee true for callers that have not been converted
yet, and it is why a new leak cannot silently change another test's meaning.
The whole environment is restored rather than only the provider variables: the
provider surface is not the only thing a test can write, and a leak of anything
else is the same defect. Measured 2026-09-18 against the suite with this fixture
in place and without it: identical tallies, so the restore changes no legitimate
cross-test dependency.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _restore_process_environment() -> None:
    snapshot = dict(os.environ)
    try:
        yield
    finally:
        for name in [name for name in os.environ if name not in snapshot]:
            del os.environ[name]
        os.environ.update(snapshot)


# --------------------------------------------------------------------------- #
# Hermetic offline runner fixture (P3 shard, 2026-09-19)
# --------------------------------------------------------------------------- #
# The cross-repo "runner contract" tests were quarantined because they invoke the
# sibling worktree ``ai-agent-engineering-workflow/.worktrees/team-event-contract-
# v1-20260713`` pinned at ``50eb4d27...`` -- which is not materialized in a fresh
# clone or CI. This fixture vendors a *recorded* copy of that runner's contract
# surface (the closed TeamEvent schema, the public record builder, and the
# init/permission/team-event CLI that writes the same .agent_runs ledger layout)
# into ``tests/product_eval/fixtures/hermetic_runner/``, wraps it in a clean git
# repo on the pinned branch name, and points every test module's RUNNER_*
# constants at it. The consumer-side logic under test (fail-closed JSON-schema
# validation, typed authority binding, receipt content-addressing and mutation
# rejection) is identical; only the producer is a deterministic, keyless stub.
#
# If the real sibling worktree IS present and checked out at the exact pinned
# branch/HEAD, it is used; otherwise the vendored hermetic runner keeps the suite
# green offline with zero external assets.

_HERMETIC_FIXTURE_SRC = (
    Path(__file__).resolve().parent / "fixtures" / "hermetic_runner"
)
_PINNED_BRANCH = "codex/team-event-contract-v1-20260713"
_PINNED_HEAD = "50eb4d27b17688f0943f80207dddb702983afd51"


@dataclass(frozen=True)
class HermeticRunner:
    worktree: Path
    python: Path
    branch: str
    head: str


def _git(args: list[str], cwd: Path) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=cwd, check=True, text=True, capture_output=True
    )
    return completed.stdout.strip()


def _build_hermetic_runner() -> HermeticRunner:
    root = Path(tempfile.mkdtemp(prefix="hermetic-runner-"))
    target = root / "runner"
    shutil.copytree(_HERMETIC_FIXTURE_SRC, target)
    # A dedicated python shim (symlink to the current interpreter) so the runner
    # interpreter path is distinct from the product interpreter the
    # "non-pinned interpreter" rejection test exercises.
    shim = target / "bin" / "python"
    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.unlink(missing_ok=True)
    shim.symlink_to(sys.executable)

    _git(["init", "-q"], target)
    # Point HEAD at the pinned branch name (unborn), then commit so rev-parse
    # resolves to a real sha on that branch.
    _git(["symbolic-ref", "HEAD", f"refs/heads/{_PINNED_BRANCH}"], target)
    subprocess.run(
        ["git", "config", "user.email", "hermetic@example.com"],
        cwd=target, check=True, text=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Hermetic Runner"],
        cwd=target, check=True, text=True, capture_output=True,
    )
    _git(["add", "-A"], target)
    _git(["commit", "-q", "-m", "hermetic pinned runner fixture"], target)
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], target)
    head = _git(["rev-parse", "HEAD"], target)
    # Resolve the worktree so /var -> /private/var (macOS) symlinks collapse; the
    # qualification module resolves import_path but the test compares against the
    # injected constant, so both must be in the same resolved form.
    return HermeticRunner(
        worktree=target.resolve(), python=shim, branch=branch, head=head
    )


def _real_sibling_runner() -> HermeticRunner | None:
    """Return the real pinned runner only if checked out at the exact SHA."""

    workspace_root = Path(__file__).resolve().parents[3]
    worktree = (
        workspace_root
        / "ai-agent-engineering-workflow"
        / ".worktrees"
        / "team-event-contract-v1-20260713"
    )
    python = (
        workspace_root
        / "ai-agent-engineering-workflow"
        / ".venv"
        / "bin"
        / "python"
    )
    if not worktree.is_dir() or not python.is_file():
        return None
    try:
        branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], worktree)
        head = _git(["rev-parse", "HEAD"], worktree)
        dirty = _git(["status", "--porcelain"], worktree)
    except (subprocess.CalledProcessError, OSError):
        return None
    if branch != _PINNED_BRANCH or head != _PINNED_HEAD or dirty:
        return None
    return HermeticRunner(worktree=worktree, python=python, branch=branch, head=head)


@pytest.fixture(scope="session")
def hermetic_runner() -> HermeticRunner:
    real = _real_sibling_runner()
    if real is not None:
        return real
    return _build_hermetic_runner()


# These test modules are collected by pytest in "prepend" import mode (no
# __init__.py in tests/product_eval/), so they live in sys.modules under their bare
# top-level name -- NOT as tests.product_eval.*. Import by that exact name (falling
# back to the dotted form) or monkeypatch patches a duplicate the tests never see.
_RUNNER_CONST_MODULES = (
    "test_json_schema_contract",
    "tests.product_eval.test_json_schema_contract",
    "test_runner_contract_qualification",
    "tests.product_eval.test_runner_contract_qualification",
    "test_spine_e2e_4_assets",
    "tests.product_eval.test_spine_e2e_4_assets",
    "test_spine_e2e_4_combined_qualification",
    "tests.product_eval.test_spine_e2e_4_combined_qualification",
    "test_spine_e2e_4_scratch_cli",
    "tests.product_eval.test_spine_e2e_4_scratch_cli",
)


@pytest.fixture(autouse=True)
def _point_tests_at_hermetic_runner(
    monkeypatch: pytest.MonkeyPatch, hermetic_runner: HermeticRunner
) -> None:
    for module_name in _RUNNER_CONST_MODULES:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        for attr, value in (
            ("RUNNER_WORKTREE", hermetic_runner.worktree),
            ("RUNNER_PYTHON", hermetic_runner.python),
            ("RUNNER_BRANCH", hermetic_runner.branch),
            ("RUNNER_HEAD", hermetic_runner.head),
        ):
            if hasattr(module, attr):
                monkeypatch.setattr(module, attr, value)
        # Some test helpers capture RUNNER_WORKTREE / RUNNER_PYTHON as *default
        # keyword argument values*, which are bound at function-definition time and
        # do NOT follow a later monkeypatch of the module global. Rewrite their
        # __kwdefaults__ so those helpers default to the hermetic runner too.
        for fn_name in ("_run_runner", "_runner_subprocess", "_runner_contract_value"):
            fn = getattr(module, fn_name, None)
            if callable(fn) and getattr(fn, "__kwdefaults__", None):
                new_kw = dict(fn.__kwdefaults__)
                if "runner_worktree" in new_kw:
                    new_kw["runner_worktree"] = hermetic_runner.worktree
                if "runner_python" in new_kw:
                    new_kw["runner_python"] = hermetic_runner.python
                if "RUNNER_WORKTREE" in new_kw:
                    new_kw["RUNNER_WORKTREE"] = hermetic_runner.worktree
                if "RUNNER_PYTHON" in new_kw:
                    new_kw["RUNNER_PYTHON"] = hermetic_runner.python
                monkeypatch.setattr(fn, "__kwdefaults__", new_kw)


# --------------------------------------------------------------------------- #
# Quarantine mechanism (shard D, 2026-09-19)
# --------------------------------------------------------------------------- #
# A `quarantine(reason=...)` mark is the ONLY sanctioned way to suppress an offline
# deterministic test in this suite. It is converted here into a skip that always carries
# its reason, so:
#   * there is no silent `@pytest.mark.skip` (a reason is mandatory),
#   * no test is deleted (the mark sits on the test and runs when the asset lands),
#   * every quarantined item appears, with its reason, in `-rs` and in the report below.
# Lift a quarantine only when the named asset is available and the test re-confirms green
# in this repo (not just on the author's machine).
def pytest_collection_modifyitems(config, items):  # type: ignore[no-untyped-def]
    """Convert every quarantined item into a reason-bearing skip.

    Two sources, one rule:
      * an in-file ``@pytest.mark.quarantine(reason=...)`` on the item itself;
      * the central manifest ``_quarantine.QUARANTINE_BUCKETS`` (exact nodeids).

    Both require a non-empty reason. A reasonless quarantine is a silent skip and is
    rejected here rather than silently suppressing a test. The resulting skips print their
    reason under ``-rs`` and are tallied below.
    """
    from tests.product_eval._quarantine import QUARANTINE_BUCKETS

    manifest = {}
    for bucket in QUARANTINE_BUCKETS.values():
        reason = bucket["reason"]
        owner = bucket.get("owner", "<unowned>")
        review_by = bucket.get("review_by", "<no-review-by>")
        label = f"{reason} [owner={owner}; review_by={review_by}]"
        for nodeid in bucket["nodeids"]:
            manifest[nodeid] = label

    quarantined: list[str] = []
    for item in items:
        reasons: list[str] = []
        for mark in item.iter_markers(name="quarantine"):
            reason = mark.kwargs.get("reason")
            if not reason:
                raise RuntimeError(
                    f"quarantine mark on {item.nodeid!r} must carry a reason= explaining "
                    "what asset is missing, why it cannot run in this repo, and when it "
                    "can be lifted. A reasonless quarantine is a silent skip and is rejected."
                )
            reasons.append(reason)
        # Central manifest match (exact nodeid).
        if item.nodeid in manifest:
            reasons.append(manifest[item.nodeid])
        for reason in reasons:
            item.add_marker(pytest.mark.skip(reason=f"[quarantine] {reason}"))
        if reasons:
            quarantined.append(f"{item.nodeid} :: {reasons[0]}")
    if quarantined:
        print(
            "\n".join(
                ["", "=== QUARANTINED product_eval tests (asset-gated, not silent skips) ==="]
                + [f"  - {line}" for line in quarantined]
            )
        )
