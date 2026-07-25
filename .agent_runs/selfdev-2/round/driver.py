"""SELFDEV-2 round driver: baseline pass@2 for 12 main tasks, then chain pass@2.

Sequential, per prereg. Persists progress after every attempt (resume-safe:
existing attempt files are skipped). Aborts early on repeated infra errors.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path("/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/canonical-convergence-20260715")
ROUND = ROOT / ".agent_runs/selfdev-2/round"
SELECTION = json.loads((ROOT / ".agent_runs/selfdev-2/selection.json").read_text())
MAIN = [t["instance_id"] for t in SELECTION["tasks"] if t["set"] == "main"]

ENV = dict(os.environ)
ENV["AGENT_OS_PROVIDER_TIMEOUT_SECONDS"] = "180"
ENV["PYTHONPATH"] = ".:src:packages/contracts/src:packages/os_core/src"
PY = str(ROOT / ".venv/bin/python")

TIMEOUTS = {"baseline": 900, "chain": 1500}


def run_arm(arm: str, instance_id: str, attempt: int) -> dict[str, object]:
    out_dir = ROUND / instance_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{arm}-attempt-{attempt}.json"
    err_file = out_dir / f"{arm}-attempt-{attempt}-stderr.log"
    if out_file.exists():
        return {"skip": True}
    subcommand = "benchmark-run-baseline" if arm == "baseline" else "benchmark-run-provider"
    cmd = [
        PY, "-m", "apps.cli",
        subcommand,
        ".agent_runs/selfdev-2/selection.json",
        instance_id,
    ]
    if arm == "chain":
        cmd += ["--approve", "--duration-seconds", "3600"]
    started = time.time()
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
        progress = {"last": f"{arm}:{instance_id}:attempt-{attempt}",
                    "elapsed_s": round(time.time() - started, 1),
                    "ts": time.time()}
        (ROUND / "progress.json").write_text(json.dumps(progress))


def main() -> None:
    infra_streak = 0
    for arm in ("baseline", "chain"):
        for instance_id in MAIN:
            for attempt in (1, 2):
                result = run_arm(arm, instance_id, attempt)
                if result.get("infra_error"):
                    infra_streak += 1
                    if infra_streak >= 3:
                        print(f"ABORT: 3 consecutive infra errors at {arm} {instance_id} a{attempt}", flush=True)
                        return
                else:
                    infra_streak = 0
                print(f"done {arm} {instance_id} attempt-{attempt}: "
                      f"{str(result)[:120]}", flush=True)
    print("ROUND COMPLETE", flush=True)


if __name__ == "__main__":
    sys.exit(main())
