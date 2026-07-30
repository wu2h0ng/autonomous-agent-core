"""SELFDEV-4 candidate gold-validation driver (self-hosted, sequential).

For each candidate: clone --shared from the local mirror, checkout base,
resolve f2p/p2p node ids against base+test_patch (per-id, drop unresolvable;
f2p unresolvable excludes the task), then run_gold_validation in the
per-repo container image. Writes one result JSON per task (resume-safe).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path("/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/canonical-convergence-20260715")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages/contracts/src"))
sys.path.insert(0, str(ROOT / "packages/os_core/src"))

from agent_os_contracts.benchmark_task import BenchmarkTaskValidationError  # noqa: E402
from agent_os_core import (  # noqa: E402
    ContainerRunner,
    ContainerVerifierExecutor,
    run_gold_validation,
)
from agent_os_core.benchmark_baseline import apply_unified_diff  # noqa: E402
from agent_os_core.benchmark_node_ids import resolve_benchmark_node_id  # noqa: E402
from apps.cli.__main__ import _benchmark_task_from_entry  # noqa: E402

POOL = json.loads((ROOT / ".agent_runs/selfdev-2/dataset/candidate-pool.json").read_text())
BY_ID = {t["instance_id"]: t for t in POOL}
MIRRORS = Path("/tmp/selfdev2-dryrun/mirrors")
WS_BASE = Path.home() / "Documents/AI-Agent-Projects/.cache/selfdev2-dryrun-ws"
RESULTS = Path("/tmp/selfdev2-dryrun/results")
RESULTS.mkdir(parents=True, exist_ok=True)

IMAGE = {
    "django/django": "selfdev2-dryrun-django:py39",
    "sphinx-doc/sphinx": "selfdev2-dryrun-sphinx:py39",
    "sympy/sympy": "selfdev2-dryrun-sympy:v1",
    "psf/requests": "selfdev2-dryrun-requests:v1",
    "pytest-dev/pytest": "selfdev2-dryrun-pytest:v1",
    "pylint-dev/pylint": "selfdev2-dryrun-pylint:v1",
    "astropy/astropy": "selfdev2-dryrun-astropy:py39",
    "scikit-learn/scikit-learn": "selfdev2-dryrun-sklearn:py39",
}
TIMEOUT = {"astropy/astropy": 900, "scikit-learn/scikit-learn": 900}
CANDIDATES = {
    "django/django": (["django__django-7530", "django__django-9296", "django__django-10097", "django__django-10880", "django__django-10973", "django__django-10999", "django__django-11066", "django__django-11087", "django__django-11099"], 4),
    "sympy/sympy": (["sympy__sympy-13551", "sympy__sympy-13852", "sympy__sympy-14976", "sympy__sympy-15017", "sympy__sympy-15345"], 3),
    "sphinx-doc/sphinx": (["sphinx-doc__sphinx-7889", "sphinx-doc__sphinx-7910", "sphinx-doc__sphinx-7985", "sphinx-doc__sphinx-8269", "sphinx-doc__sphinx-8459", "sphinx-doc__sphinx-8475", "sphinx-doc__sphinx-8721", "sphinx-doc__sphinx-9230", "sphinx-doc__sphinx-9658", "sphinx-doc__sphinx-9673", "sphinx-doc__sphinx-9711"], 3),
    "astropy/astropy": (["astropy__astropy-7671", "astropy__astropy-13033", "astropy__astropy-13579"], 2),
    "scikit-learn/scikit-learn": (["scikit-learn__scikit-learn-25747", "scikit-learn__scikit-learn-25973", "scikit-learn__scikit-learn-13142"], 2),
    "pytest-dev/pytest": (["pytest-dev__pytest-5809"], 1),
    "psf/requests": (["psf__requests-1724"], 1),
    "pylint-dev/pylint": (["pylint-dev__pylint-7277"], 1),
}


def sh(argv: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, check=False, **kw)


def _is_git_repo(candidate: Path) -> bool:
    return (candidate / "HEAD").exists() or (candidate / ".git" / "HEAD").exists()


def mirror_for(repo: str) -> Path:
    org, name = repo.split("/", 1)
    flat = repo.replace("/", "-")
    for candidate in (
        MIRRORS / f"{flat}.git",
        MIRRORS / flat,
        MIRRORS / f"{name}.git",
        MIRRORS / name,
        MIRRORS / f"{org}.git",
        MIRRORS / org,
        MIRRORS / org / f"{name}.git",
    ):
        if candidate.exists() and _is_git_repo(candidate):
            return candidate
    raise RuntimeError(f"mirror missing for {repo}")


def patch_file_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.startswith("diff --git "))


def resolve_ids(raw_ids: list[str], ws: Path) -> tuple[list[str], list[str], list[str]]:
    resolved, dropped = [], []
    for raw in raw_ids:
        if "[" in raw:
            dropped.append(raw)
            continue
        try:
            resolved.append(resolve_benchmark_node_id(raw, repo_root=ws))
        except BenchmarkTaskValidationError:
            dropped.append(raw)
    return resolved, dropped


def run_candidate(iid: str) -> dict[str, object]:
    entry = BY_ID[iid]
    repo = entry["repo"]
    result_path = RESULTS / f"{iid}.json"
    if result_path.exists():
        return json.loads(result_path.read_text())
    started = time.time()
    base: dict[str, object] = {
        "instance_id": iid, "repo": repo, "base_commit": entry["base_commit"],
        "image_tag": IMAGE[repo], "python_version": "3.9",
    }
    gold = (ROOT / ".agent_runs/selfdev-2/dataset" / entry["gold_patch_file"]).read_text()
    test_patch = (ROOT / ".agent_runs/selfdev-2/dataset" / entry["test_patch_file"]).read_text()
    if patch_file_count(gold) != 1 or patch_file_count(test_patch) != 1:
        record = {**base, "ok": False, "excluded": True,
                  "detail": "multi-file gold or test patch",
                  "duration_s": round(time.time() - started, 1)}
        result_path.write_text(json.dumps(record, indent=2))
        return record
    ws = WS_BASE / iid
    if ws.exists():
        subprocess.run(["rm", "-rf", str(ws)], check=False)
    sh(["git", "clone", "--shared", str(mirror_for(repo)), str(ws)])
    if not (ws / ".git").exists():
        record = {**base, "ok": False,
                  "detail": f"workspace clone failed for {repo}",
                  "duration_s": round(time.time() - started, 1)}
        result_path.write_text(json.dumps(record, indent=2))
        return record
    sh(["git", "-C", str(ws), "checkout", entry["base_commit"]])
    apply_unified_diff(ws, test_patch)
    try:
        f2p_resolved, f2p_dropped = resolve_ids(list(entry["f2p_node_ids"]), ws)
        p2p_resolved, p2p_dropped = resolve_ids(list(entry["p2p_node_ids"]), ws)
    finally:
        sh(["git", "-C", str(ws), "checkout", "--", "."])
        sh(["git", "-C", str(ws), "clean", "-fdx"])
    if f2p_dropped:
        record = {**base, "ok": False, "excluded": True,
                  "detail": f"unresolvable f2p ids: {f2p_dropped}",
                  "duration_s": round(time.time() - started, 1)}
        result_path.write_text(json.dumps(record, indent=2))
        return record
    task_entry = dict(entry)
    task_entry.update({
        "interpreter": "python3.9",
        "verifier_timeout_seconds": TIMEOUT.get(repo, 600),
        "min_output_tokens": 8192,
        "f2p_node_ids": f2p_resolved,
        "p2p_node_ids": p2p_resolved,
    })
    task = _benchmark_task_from_entry(task_entry)
    executor = ContainerVerifierExecutor(
        runner=ContainerRunner(),
        image_tag=IMAGE[repo],
        repo_root_host=ws.parent,
        gold_file_path=str(entry["gold_file_path"]),
    )
    try:
        outcome = run_gold_validation(
            task, ws,
            executor=executor,
            gold_patch=gold,
            test_patch=test_patch,
        )
        record = {
            **base,
            "ok": outcome.ok,
            "f2p_red_at_base": outcome.f2p_red_at_base,
            "f2p_green_at_gold": outcome.f2p_green_at_gold,
            "p2p_green_at_gold": outcome.p2p_green_at_gold,
            "f2p_resolved": f2p_resolved,
            "p2p_resolved": p2p_resolved,
            "p2p_dropped_unresolved": p2p_dropped,
            "p2p_vacuous": len(p2p_resolved) == 0,
            "detail": outcome.detail,
            "evidence_digest": outcome.evidence_digest,
            "duration_s": round(time.time() - started, 1),
        }
    except Exception as exc:  # noqa: BLE001 - record and move on
        record = {**base, "ok": False,
                  "detail": f"{type(exc).__name__}: {str(exc)[:300]}",
                  "f2p_resolved": f2p_resolved, "p2p_resolved": p2p_resolved,
                  "p2p_dropped_unresolved": p2p_dropped,
                  "duration_s": round(time.time() - started, 1)}
    result_path.write_text(json.dumps(record, indent=2))
    return record


def main() -> None:
    for repo, (ids, target) in CANDIDATES.items():
        validated = 0
        for iid in ids:
            record = run_candidate(iid)
            print(f"{iid}: ok={record.get('ok')} {str(record.get('detail'))[:100]}", flush=True)
            if record.get("ok"):
                validated += 1
                if validated >= target:
                    break
        print(f"REPO {repo}: validated={validated}/{target}", flush=True)
    print("S4 DRYRUN COMPLETE", flush=True)


if __name__ == "__main__":
    sys.exit(main())
