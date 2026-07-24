"""Filter d: fetch gold file at base_commit, keep only <= 19000 bytes.

Polite fetching: max 4 concurrent, 10s timeout per attempt, up to 2 retries,
small delay between requests per worker.
"""
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = Path(__file__).resolve().parent
MAX_BYTES = 19000
TIMEOUT = 10
RETRIES = 2  # additional attempts after the first
DELAY = 0.15

inter = json.loads((BASE / "intermediate.json").read_text())
candidates = inter["candidates"]

UA = {"User-Agent": "swe-bench-verified-candidate-pool-builder/1.0 (research; polite)"}


def fetch_one(cand):
    url = f"https://raw.githubusercontent.com/{cand['repo']}/{cand['base_commit']}/{cand['gold_file_path']}"
    last_err = None
    for attempt in range(1 + RETRIES):
        time.sleep(DELAY)
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = resp.read()
            return {
                "instance_id": cand["instance_id"],
                "ok": True,
                "bytes": len(body),
                "lines": body.count(b"\n") + (0 if body.endswith(b"\n") or not body else 1),
                "attempts": attempt + 1,
            }
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            last_err = str(e)
    return {"instance_id": cand["instance_id"], "ok": False, "error": last_err}


results = []
with ThreadPoolExecutor(max_workers=4) as ex:
    for i, res in enumerate(ex.map(fetch_one, candidates), 1):
        results.append(res)
        if i % 25 == 0 or i == len(candidates):
            print(f"{i}/{len(candidates)} fetched", flush=True)

(BASE / "fetch_results.json").write_text(json.dumps(results, indent=1))
ok = sum(1 for r in results if r["ok"])
fail = len(results) - ok
oversize = sum(1 for r in results if r["ok"] and r["bytes"] > MAX_BYTES)
print(f"fetch ok={ok} fail={fail} oversize(>{MAX_BYTES})={oversize}")
