"""Assemble the final candidate pool, per-task files, and acquisition report."""
import hashlib
import json
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent
MAX_BYTES = 19000

inter = json.loads((BASE / "intermediate.json").read_text())
fetch = {r["instance_id"]: r for r in json.loads((BASE / "fetch_results.json").read_text())}

drops = dict(inter["drops"])
pool = []
oversize_dropped = 0
fetch_failures = []

for cand in inter["candidates"]:
    fr = fetch[cand["instance_id"]]
    if not fr["ok"]:
        fetch_failures.append({"instance_id": cand["instance_id"], "error": fr["error"]})
        continue
    if fr["bytes"] > MAX_BYTES:
        oversize_dropped += 1
        continue
    pool.append((cand, fr))

drops["d_gold_file_oversize"] = oversize_dropped
drops["d_fetch_failure"] = len(fetch_failures)

entries = []
for cand, fr in pool:
    iid = cand["instance_id"]
    tdir = BASE / "tasks" / iid
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "gold.patch").write_text(cand["patch"])
    (tdir / "test.patch").write_text(cand["test_patch"])
    (tdir / "issue.txt").write_text(cand["problem_statement"])

    p2p = cand["p2p_node_ids"]
    p2p_truncated = len(p2p) > 20
    entries.append({
        "instance_id": iid,
        "repo": cand["repo"],
        "base_commit": cand["base_commit"],
        "environment_setup_commit": cand["environment_setup_commit"],
        "issue_text_hash": cand["issue_text_hash"],
        "gold_file_path": cand["gold_file_path"],
        "gold_file_bytes": fr["bytes"],
        "gold_file_lines": fr["lines"],
        "f2p_node_ids": cand["f2p_node_ids"],
        "p2p_node_ids": p2p[:20] if p2p_truncated else p2p,
        "p2p_truncated": p2p_truncated,
        "gold_patch_file": f"tasks/{iid}/gold.patch",
        "test_patch_file": f"tasks/{iid}/test.patch",
        "problem_chars": cand["problem_chars"],
    })

entries.sort(key=lambda e: e["instance_id"])
(BASE / "candidate-pool.json").write_text(json.dumps(entries, indent=1) + "\n")

# sanity: verify hashes of written issue files match issue_text_hash
bad = [e["instance_id"] for e in entries
       if hashlib.sha256((BASE / "tasks" / e["instance_id"] / "issue.txt").read_bytes()).hexdigest() != e["issue_text_hash"]]
assert not bad, f"hash mismatch: {bad}"

pool_repo_counts = Counter(e["repo"] for e in entries)
param_in_pool = [e["instance_id"] for e in entries if any("[" in nid for nid in e["f2p_node_ids"])]
n_p2p_trunc = sum(1 for e in entries if e["p2p_truncated"])
retried = sum(1 for r in fetch.values() if r.get("ok") and r.get("attempts", 1) > 1)

print(f"pool_size={len(entries)}")
print(f"pool per repo: {dict(pool_repo_counts)}")
print(f"p2p_truncated={n_p2p_trunc} parametrized_f2p_in_pool={len(param_in_pool)} fetch_retried={retried}")

summary = {
    "drops": drops,
    "pool_size": len(entries),
    "pool_repo_counts": dict(pool_repo_counts),
    "param_in_pool": param_in_pool,
    "n_p2p_trunc": n_p2p_trunc,
    "fetch_failures": fetch_failures,
    "retried": retried,
}
(BASE / "assembly_summary.json").write_text(json.dumps(summary, indent=1))
print("wrote candidate-pool.json, tasks/, assembly_summary.json")
