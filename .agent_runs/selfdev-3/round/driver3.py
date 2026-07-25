"""SELFDEV-3 round driver: ABAB interleaved arms, envelope E2 (600s).

Per frozen prereg: for each main task in frozen order — baseline a1, chain a1,
baseline a2, chain a2. Sequential only. Restores the workspace to the pinned
base commit before EVERY attempt (both arms). Persists per-attempt results
(resume-safe). Aborts on 3 consecutive NON-provider infra errors.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path("/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/canonical-convergence-20260715")
ROUND = ROOT / ".agent_runs/selfdev-3/round"
SELECTION = json.loads((ROOT / ".agent_runs/selfdev-2/selection.json").read_text())
MAIN = [t for t in SELECTION["tasks"] if t["set"] == "main"]

ENV = dict(os.environ)
ENV["AGENT_OS_PROVIDER_TIMEOUT_SECONDS"] = "600"
ENV["PYTHONPATH"] = ".:src:packages/contracts/src:packages/os_core/src"
PY = str(ROOT / ".venv/bin/python")

TIMEOUTS = {"baseline": 1800, "chain": 2400}


def restore_workspace(entry: dict[str, object]) -> None:
    ws = ROOT / str(entry["workspace_path"])
    base = str(entry["base_commit"])
    subprocess.run(["git", "-C", str(ws), "checkout", "--", "."], capture_output=True)
    subprocess.run(["git", "-C", str(ws), "clean", "-fdx"], capture_output=True)
    subprocess.run(["git", "-C", str(ws), "checkout", base], capture_output=True)
    dirty = subprocess.run(["git", "-C", str(ws), "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
    head = subprocess.run(["git", "-C", str(ws), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if dirty or head != base:
        raise RuntimeError(f"workspace restore failed for {entry['instance_id']}")


def run_arm(arm: str, entry: dict[str, object], attempt: int) -> dict[str, object]:
    instance_id = str(entry["instance_id"])
    out_dir = ROUND / instance_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{arm}-attempt-{attempt}.json"
    err_file = out_dir / f"{arm}-attempt-{attempt}-stderr.log"
    if out_file.exists():
        return {"skip": True}
    subcommand = "benchmark-run-baseline" if arm == "baseline" else "benchmark-run-provider"
    cmd = [PY, "-m", "apps.cli", subcommand, ".agent_runs/selfdev-2/selection.json", instance_id]
    if arm == "chain":
        cmd += ["--approve", "--duration-seconds", "3600"]
    started = time.time()
    try:
        restore_workspace(entry)
    except RuntimeError:
        return {"infra_error": True, "reason": "workspace_restore_failed"}
    # invoked marker: written BEFORE the provider node can be reached, so an
    # interrupted attempt is auditable as consumed INVALID (prereg §3).
    invoked_file = out_dir / f"{arm}-attempt-{attempt}-invoked.json"
    invoked_file.write_text(json.dumps({
        "instance_id": instance_id, "arm": arm, "attempt": attempt,
        "invoked_at": started,
    }))
    try:
        proc = subprocess.run(
            cmd, cwd=ROOT, env=ENV, capture_output=True, text=True,
            timeout=TIMEOUTS[arm],
        )
        err_file.write_text(proc.stderr or "")
        if proc.returncode == 0 and proc.stdout.strip():
            out_file.write_text(proc.stdout)
            return json.loads(proc.stdout)
        stderr_tail = (proc.stderr or "")[-400:]
        if "provider request timed out" in stderr_tail or "UNAVAILABLE" in stderr_tail:
            out_file.write_text(json.dumps({
                "instance_id": instance_id, "arm": arm, "attempt": attempt,
                "attempt_class": "INVALID_PROVIDER",
                "stderr_tail": stderr_tail,
            }))
            return {"attempt_class": "INVALID_PROVIDER"}
        out_file.write_text(json.dumps({
            "instance_id": instance_id, "arm": arm, "attempt": attempt,
            "infra_error": True, "returncode": proc.returncode,
            "stderr_tail": stderr_tail,
        }))
        return {"infra_error": True}
    except subprocess.TimeoutExpired:
        err_file.write_text("driver timeout")
        out_file.write_text(json.dumps({
            "instance_id": instance_id, "arm": arm, "attempt": attempt,
            "infra_error": True, "reason": "driver_timeout",
        }))
        return {"infra_error": True}
    finally:
        (ROUND / "progress.json").write_text(json.dumps({
            "last": f"{arm}:{instance_id}:attempt-{attempt}",
            "elapsed_s": round(time.time() - started, 1),
            "ts": time.time(),
        }))


def main() -> None:
    infra_streak = 0
    for entry in MAIN:
        instance_id = str(entry["instance_id"])
        for attempt in (1, 2):
            for arm in ("baseline", "chain"):
                result = run_arm(arm, entry, attempt)
                if result.get("infra_error"):
                    infra_streak += 1
                    if infra_streak >= 3:
                        print(f"ABORT: 3 consecutive infra errors at {arm} {instance_id} a{attempt}", flush=True)
                        return
                else:
                    infra_streak = 0
                print(f"done {arm} {instance_id} attempt-{attempt}: {str(result)[:120]}", flush=True)
    print("ROUND COMPLETE", flush=True)


if __name__ == "__main__":
    sys.exit(main())
