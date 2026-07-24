"""Widening pass: extend candidate pool with 7 additional pip-installable repos.

Same filters as the original pass: a (single-file gold patch), c (.py gold file),
e (FAIL_TO_PASS non-empty), d (gold file <= 19000 bytes at base_commit).
New entries additionally get f2p_id_style. Existing 119 entries stay untouched.
"""
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
NEW_REPOS = {
    "sphinx-doc/sphinx",
    "matplotlib/matplotlib",
    "scikit-learn/scikit-learn",
    "astropy/astropy",
    "pydata/xarray",
    "pylint-dev/pylint",
    "mwaskom/seaborn",
}
MAX_BYTES = 19000
TIMEOUT = 10
RETRIES = 2
DELAY = 0.15
UA = {"User-Agent": "swe-bench-verified-candidate-pool-builder/1.0 (research; polite)"}

df = pd.read_parquet(BASE / "raw" / "test-00000-of-00001.parquet")
sub = df[df["repo"].isin(NEW_REPOS)]
print(f"new-repo instances in dataset: {len(sub)}")
print("per-repo start:", dict(Counter(sub["repo"])))

drops = {}

# filter a: gold patch modifies exactly ONE file
stage = [r for _, r in sub.iterrows()
         if len(re.findall(r"^diff --git ", r["patch"], flags=re.M)) == 1]
drops["a_multi_or_zero_file_patch"] = len(sub) - len(stage)
print(f"after a: {len(stage)} (dropped {drops['a_multi_or_zero_file_patch']})")

# filter c: gold file is .py
def gold_path(patch):
    return re.findall(r"^diff --git a/(\S+) b/\S+", patch, flags=re.M)[0]

prev = len(stage)
stage = [r for r in stage if gold_path(r["patch"]).endswith(".py")]
drops["c_gold_file_not_py"] = prev - len(stage)
print(f"after c: {len(stage)} (dropped {drops['c_gold_file_not_py']})")

# filter e: FAIL_TO_PASS non-empty (before d to minimize fetches; documented)
prev = len(stage)
stage = [r for r in stage if len(json.loads(r["FAIL_TO_PASS"])) > 0]
drops["e_empty_fail_to_pass"] = prev - len(stage)
print(f"after e: {len(stage)} (dropped {drops['e_empty_fail_to_pass']})")


def fetch_one(row):
    url = f"https://raw.githubusercontent.com/{row['repo']}/{row['base_commit']}/{gold_path(row['patch'])}"
    last_err = None
    for attempt in range(1 + RETRIES):
        time.sleep(DELAY)
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = resp.read()
            return row["instance_id"], True, body, None
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            last_err = str(exc)
    return row["instance_id"], False, None, last_err


fetch_results = {}
with ThreadPoolExecutor(max_workers=4) as ex:
    for i, (iid, ok, body, err) in enumerate(ex.map(fetch_one, stage), 1):
        fetch_results[iid] = (ok, body, err)
        if i % 25 == 0 or i == len(stage):
            print(f"{i}/{len(stage)} fetched", flush=True)

UNITTEST_RE = re.compile(r" \(.+\)$")

def f2p_style(ids):
    if all("::" in nid for nid in ids):
        return "pytest"
    if any(UNITTEST_RE.search(nid) for nid in ids):
        return "unittest"
    return "mixed"


new_entries = []
fetch_failures = []
oversize = 0
for r in stage:
    iid = r["instance_id"]
    ok, body, err = fetch_results[iid]
    if not ok:
        fetch_failures.append({"instance_id": iid, "error": err})
        continue
    if len(body) > MAX_BYTES:
        oversize += 1
        continue
    lines = body.count(b"\n") + (0 if body.endswith(b"\n") or not body else 1)

    tdir = BASE / "tasks" / iid
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "gold.patch").write_text(r["patch"])
    (tdir / "test.patch").write_text(r["test_patch"])
    (tdir / "issue.txt").write_text(r["problem_statement"])

    f2p = json.loads(r["FAIL_TO_PASS"])
    p2p = json.loads(r["PASS_TO_PASS"])
    p2p_truncated = len(p2p) > 20
    new_entries.append({
        "instance_id": iid,
        "repo": r["repo"],
        "base_commit": r["base_commit"],
        "environment_setup_commit": r["environment_setup_commit"],
        "issue_text_hash": hashlib.sha256(r["problem_statement"].encode("utf-8")).hexdigest(),
        "gold_file_path": gold_path(r["patch"]),
        "gold_file_bytes": len(body),
        "gold_file_lines": lines,
        "f2p_node_ids": f2p,
        "p2p_node_ids": p2p[:20] if p2p_truncated else p2p,
        "p2p_truncated": p2p_truncated,
        "gold_patch_file": f"tasks/{iid}/gold.patch",
        "test_patch_file": f"tasks/{iid}/test.patch",
        "problem_chars": len(r["problem_statement"]),
        "f2p_id_style": f2p_style(f2p),
    })

drops["d_gold_file_oversize"] = oversize
drops["d_fetch_failure"] = len(fetch_failures)
new_entries.sort(key=lambda e: e["instance_id"])

pool = json.loads((BASE / "candidate-pool.json").read_text())
old_ids = {e["instance_id"] for e in pool}
dupes = [e["instance_id"] for e in new_entries if e["instance_id"] in old_ids]
assert not dupes, f"id collision with existing pool: {dupes}"
merged = pool + new_entries
(BASE / "candidate-pool.json").write_text(json.dumps(merged, indent=1) + "\n")

summary = {
    "drops": drops,
    "added": len(new_entries),
    "added_per_repo": dict(Counter(e["repo"] for e in new_entries)),
    "style_per_repo": {
        repo: dict(Counter(e["f2p_id_style"] for e in new_entries if e["repo"] == repo))
        for repo in sorted(NEW_REPOS)
    },
    "parametrized_f2p_added": sorted(e["instance_id"] for e in new_entries
                                     if any("[" in nid for nid in e["f2p_node_ids"])),
    "fetch_failures": fetch_failures,
    "merged_pool_size": len(merged),
}
(BASE / "widening_summary.json").write_text(json.dumps(summary, indent=1))
print(json.dumps(summary, indent=1))
