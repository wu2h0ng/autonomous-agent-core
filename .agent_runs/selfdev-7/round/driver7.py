"""SELFDEV-7 round driver: ABAB interleaved arms, envelope E7 (600s).

Per frozen prereg: for each main task in frozen order — baseline a1, chain a1,
baseline a2, chain a2. Sequential only. Restores the workspace to the pinned
base commit before EVERY attempt (both arms). Persists per-attempt results
(resume-safe). Whitelist abort: the round aborts ONLY on whitelisted
genuine-infra stderr signatures (docker daemon, workspace missing/dirty/drift,
restore failure, configuration drift); unrecognized provider output records a
consumed FAILED_UNCLASSIFIED attempt and the round continues. Pause-on-403
(prereg §0.3): account-quota signatures (HTTP 403 / AUTHENTICATION_FAILED)
PAUSE the round instead of consuming the attempt — the pause is recorded, the
slot retries after a probe-gated resume (5-min probes, 2 consecutive healthy,
6h cumulative cap).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path("/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/canonical-convergence-20260715")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages/contracts/src"))
sys.path.insert(0, str(ROOT / "packages/os_core/src"))
ROUND = ROOT / ".agent_runs/selfdev-7/round"
SELECTION = json.loads((ROOT / ".agent_runs/selfdev-4/selection.json").read_text())
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
    cmd = [PY, "-m", "apps.cli", subcommand, ".agent_runs/selfdev-4/selection.json", instance_id]
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
        stderr_tail = (proc.stderr or "")[-400:]
        if _is_quota_event(stderr_tail):
            if _pause_budget_remaining_s > 0:
                # prereg §0.3: 403 quota events PAUSE the round, not consume it —
                # record the pause event, keep the invoked marker, and let the
                # main loop retry this slot after the probe-gated resume.
                (out_dir / f"{arm}-attempt-{attempt}-quota-pause-{int(started)}.json").write_text(json.dumps({
                    "instance_id": instance_id, "arm": arm, "attempt": attempt,
                    "quota_pause": True, "stderr_tail": stderr_tail,
                    "ts": started,
                }))
                out_file.unlink(missing_ok=True)
                return {"paused_quota": True}
            # pause budget exhausted: quota events now consume INVALID_PROVIDER
            out_file.write_text(json.dumps({
                "instance_id": instance_id, "arm": arm, "attempt": attempt,
                "attempt_class": "INVALID_PROVIDER",
                "detail": "quota event recorded after the cumulative pause budget was exhausted",
                "stderr_tail": stderr_tail,
            }))
            return {"attempt_class": "INVALID_PROVIDER"}
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
        if "BASELINE_DIFF_INVALID" in stderr_tail or "provider diff failed validation" in stderr_tail:
            out_file.write_text(json.dumps({
                "instance_id": instance_id, "arm": arm, "attempt": attempt,
                "attempt_class": "DIFF_INVALID",
                "stderr_tail": stderr_tail,
            }))
            return {"attempt_class": "DIFF_INVALID"}
        if "must contain only path and" in stderr_tail:
            out_file.write_text(json.dumps({
                "instance_id": instance_id, "arm": arm, "attempt": attempt,
                "attempt_class": "INVALID_ENVELOPE",
                "stderr_tail": stderr_tail,
            }))
            return {"attempt_class": "INVALID_ENVELOPE"}
        if "BASELINE_DIFF_REJECTED" in stderr_tail or "patch does not apply" in stderr_tail or "unified diff context mismatch" in stderr_tail:
            out_file.write_text(json.dumps({
                "instance_id": instance_id, "arm": arm, "attempt": attempt,
                "attempt_class": "APPLY_FAILED",
                "stderr_tail": stderr_tail,
            }))
            return {"attempt_class": "APPLY_FAILED"}
        out_file.write_text(json.dumps({
            "instance_id": instance_id, "arm": arm, "attempt": attempt,
            "infra_error": _is_genuine_infra(stderr_tail),
            "attempt_class": "FAILED_UNCLASSIFIED",
            "returncode": proc.returncode,
            "stderr_tail": stderr_tail,
        }))
        return {
            "attempt_class": "FAILED_UNCLASSIFIED",
            "infra_error": _is_genuine_infra(stderr_tail),
        }
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


GENUINE_INFRA_MARKERS = (
    "docker daemon",
    "Cannot connect to the Docker daemon",
    "BENCHMARK_CONTAINER_UNAVAILABLE",
    "BENCHMARK_CONTAINER_BUILD_FAILED",
    "benchmark workspace missing",
    "benchmark workspace is not clean",
    "benchmark workspace head drift",
    "TaskConfigurationDrift",
    "BENCHMARK_RESTORE_FAILED",
    "workspace_restore_failed",
)


def _is_genuine_infra(stderr_tail: str) -> bool:
    """Whitelist abort: only genuine task-environment failures count.

    Per the SELFDEV-5 adjudication's structural fix: the driver NEVER aborts
    on unrecognized provider output — unrecognized output records a consumed
    FAILED_UNCLASSIFIED attempt and the round continues.
    """
    return any(marker in stderr_tail for marker in GENUINE_INFRA_MARKERS)


def health_gate() -> bool:
    """Pre-round provider health gate (prereg §3). Probes are NOT attempts."""
    import json as _json
    import urllib.request

    base_url = os.environ.get("AGENT_OS_PROVIDER_BASE_URL", "")
    model = os.environ.get("AGENT_OS_PROVIDER_MODEL", "")
    key_env = os.environ.get("AGENT_OS_PROVIDER_API_KEY_ENV", "OPENAI_API_KEY")
    api_key = os.environ.get(key_env, "")
    if not (base_url and model and api_key):
        print("health gate: provider env incomplete", flush=True)
        return False

    def probe(content: str, max_tokens: int, timeout: int) -> str | None:
        body = _json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens,
        }).encode()
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    return None
                payload = _json.loads(resp.read().decode())
            return payload["choices"][0]["message"]["content"] or ""
        except Exception:
            return None

    for i in range(3):
        if probe("reply with the single word: ok", 8, 30) is None:
            print(f"health gate: small probe {i+1} failed", flush=True)
            return False
    reserve = next(t for t in SELECTION["tasks"] if t["set"] == "reserve")
    gold_rel = str(reserve["gold_file_path"])
    file_bytes = (ROOT / str(reserve["workspace_path"]) / gold_rel).read_text(
        encoding="utf-8"
    )
    medium_prompt = (
        f"Here is the current content of {gold_rel}:\n```\n{file_bytes}\n```\n"
        "Output ONLY a unified diff (--- a/... +++ b/... with @@ hunks) that "
        "adds a one-line comment at the end of the file."
    )
    medium_text = probe(medium_prompt, 4096, 300)
    if medium_text is None:
        print("health gate: medium probe failed (no response)", flush=True)
        return False
    from agent_os_core import extract_unified_diff

    if extract_unified_diff(medium_text) is None:
        print("health gate: medium probe produced no extractable diff", flush=True)
        return False
    print("health gate: PASS", flush=True)
    return True


QUOTA_MARKERS = ("AUTHENTICATION_FAILED", "HTTP 403")
PAUSE_PROBE_INTERVAL_S = 300
PAUSE_BUDGET_TOTAL_S = 6 * 3600
_pause_budget_remaining_s = PAUSE_BUDGET_TOTAL_S


def _is_quota_event(stderr_tail: str) -> bool:
    """Account-quota signatures (403) — the ONLY pause trigger (prereg §0.3)."""
    return any(marker in stderr_tail for marker in QUOTA_MARKERS)


def _pause_until_healthy() -> bool:
    """Probe-gated pause with a CUMULATIVE budget (prereg §0.3).

    Returns True when 2 consecutive healthy probes allow resume; False when
    the cumulative 6h budget is exhausted — callers then record subsequent
    quota events as consumed INVALID_PROVIDER attempts instead of pausing.
    """
    global _pause_budget_remaining_s
    healthy_streak = 0
    while True:
        if _pause_budget_remaining_s <= 0:
            print("pause budget exhausted (6h cumulative) — subsequent quota events consume INVALID_PROVIDER", flush=True)
            return False
        if health_gate():
            healthy_streak += 1
        else:
            healthy_streak = 0
        print(f"pause probe: healthy_streak={healthy_streak} remaining={_pause_budget_remaining_s}s", flush=True)
        if healthy_streak >= 2:
            print("resume after pause", flush=True)
            return True
        _pause_budget_remaining_s -= PAUSE_PROBE_INTERVAL_S
        time.sleep(PAUSE_PROBE_INTERVAL_S)


def main() -> None:
    if not health_gate():
        print("ROUND NOT STARTED: provider health gate failed", flush=True)
        return
    infra_streak = 0
    for entry in MAIN:
        instance_id = str(entry["instance_id"])
        for attempt in (1, 2):
            for arm in ("baseline", "chain"):
                while True:
                    result = run_arm(arm, entry, attempt)
                    if result.get("paused_quota"):
                        _pause_until_healthy()
                        continue
                    break
                if result.get("infra_error"):
                    infra_streak += 1
                    if infra_streak >= 3:
                        print(f"ABORT: 3 consecutive genuine-infra errors at {arm} {instance_id} a{attempt}", flush=True)
                        return
                else:
                    infra_streak = 0
                print(f"done {arm} {instance_id} attempt-{attempt}: {str(result)[:120]}", flush=True)
    print("ROUND COMPLETE", flush=True)


if __name__ == "__main__":
    sys.exit(main())
