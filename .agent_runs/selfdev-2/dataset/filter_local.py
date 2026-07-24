"""Local filtering of SWE-bench Verified for the candidate pool.

Applies filters a, b, c, e (all local). Emits an intermediate JSON with
candidates that still need the remote gold-file size check (filter d).
"""
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
ALLOWLIST = {
    "django/django",
    "sympy/sympy",
    "psf/requests",
    "pytest-dev/pytest",
    "pallets/flask",
    "encode/requests-html",
}

df = pd.read_parquet(BASE / "raw" / "test-00000-of-00001.parquet")
print(f"dataset_size={len(df)}")

repo_counts_all = Counter(df["repo"])
print("repos_in_dataset:")
for repo, n in sorted(repo_counts_all.items(), key=lambda kv: -kv[1]):
    marker = "ALLOWED" if repo in ALLOWLIST else "excluded"
    print(f"  {repo}: {n} ({marker})")

drops = {}
candidates = []

# --- filter a: gold patch modifies exactly ONE file ---
stage = []
for _, r in df.iterrows():
    n_files = len(re.findall(r"^diff --git ", r["patch"], flags=re.M))
    if n_files == 1:
        stage.append(r)
drops["a_multi_or_zero_file_patch"] = len(df) - len(stage)
print(f"after a (single-file patch): {len(stage)} (dropped {drops['a_multi_or_zero_file_patch']})")

# --- filter b: repo allowlist ---
prev = len(stage)
stage = [r for r in stage if r["repo"] in ALLOWLIST]
drops["b_repo_not_in_allowlist"] = prev - len(stage)
dropped_repos = Counter(repo for repo, n in repo_counts_all.items() if repo not in ALLOWLIST for _ in range(n))
print(f"after b (repo allowlist): {len(stage)} (dropped {drops['b_repo_not_in_allowlist']})")

# --- filter c: gold file is .py ---
def gold_files(patch: str):
    return re.findall(r"^diff --git a/(\S+) b/\S+", patch, flags=re.M)

prev = len(stage)
kept = []
for r in stage:
    path = gold_files(r["patch"])[0]
    if path.endswith(".py"):
        kept.append(r)
stage = kept
drops["c_gold_file_not_py"] = prev - len(stage)
print(f"after c (.py gold file): {len(stage)} (dropped {drops['c_gold_file_not_py']})")

# --- filter e: FAIL_TO_PASS non-empty (applied before d so d only fetches survivors) ---
prev = len(stage)
kept = []
for r in stage:
    f2p = json.loads(r["FAIL_TO_PASS"])
    if len(f2p) > 0:
        kept.append(r)
stage = kept
drops["e_empty_fail_to_pass"] = prev - len(stage)
print(f"after e (FAIL_TO_PASS non-empty): {len(stage)} (dropped {drops['e_empty_fail_to_pass']})")

for r in stage:
    f2p = json.loads(r["FAIL_TO_PASS"])
    p2p = json.loads(r["PASS_TO_PASS"])
    candidates.append({
        "instance_id": r["instance_id"],
        "repo": r["repo"],
        "base_commit": r["base_commit"],
        "environment_setup_commit": r["environment_setup_commit"],
        "problem_statement": r["problem_statement"],
        "issue_text_hash": hashlib.sha256(r["problem_statement"].encode("utf-8")).hexdigest(),
        "problem_chars": len(r["problem_statement"]),
        "patch": r["patch"],
        "test_patch": r["test_patch"],
        "gold_file_path": gold_files(r["patch"])[0],
        "f2p_node_ids": f2p,
        "p2p_node_ids": p2p,
        "f2p_parametrized": any("[" in nid for nid in f2p),
    })

n_param = sum(1 for c in candidates if c["f2p_parametrized"])
print(f"pre-d candidates: {len(candidates)}; parametrized f2p ids among them: {n_param}")

out = {
    "dataset_size": len(df),
    "repo_counts_all": dict(repo_counts_all),
    "excluded_repo_counts": {k: v for k, v in dropped_repos.items()},
    "drops": drops,
    "candidates": candidates,
}
(BASE / "intermediate.json").write_text(json.dumps(out, indent=1))
print("wrote intermediate.json")
