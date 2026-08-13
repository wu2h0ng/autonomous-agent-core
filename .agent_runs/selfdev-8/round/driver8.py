"""SELFDEV-8 round driver: ABAB interleaved arms, envelope E7 (600s).

Per frozen prereg: for each main task in frozen order — baseline a1, chain a1,
baseline a2, chain a2. Sequential only. Restores the workspace to the pinned
base commit before EVERY attempt (both arms). Persists per-attempt results
(resume-safe). Whitelist abort: the round aborts ONLY on whitelisted
genuine-infra typed signatures (BenchmarkContainerError codes, RUN_DENIED
workspace detail family, TaskConfigurationDrift exception type, docker
daemon free-text residual); unrecognized provider output records a consumed
FAILED_UNCLASSIFIED attempt and the round continues. Pause-on-403
(prereg §0.3): account-quota signatures (HTTP 403 / AUTHENTICATION_FAILED)
PAUSE the round instead of consuming the attempt — the pause is recorded, the
slot retries after a probe-gated resume (5-min probes, 2 consecutive healthy,
6h cumulative cap).

§3.5 driver8 vs driver7 authorized changes (ONLY these three):
  1. abort classifier uses typed signals (three surfaces) — see
     ABORT_CLASSIFIER_MAPPING below; the whitelist member SET stays
     byte-identical to E7 frozen values, only the matching mechanism is
     upgraded to typed surfaces; docker daemon stderr has no typed signal
     and remains a declared free-text residual.
  2. SSE fail-closed transport: malformed non-empty SSE delta now yields a
     typed MALFORMED ProviderFailure instead of silent drop — the terminal
     state enters the existing provider-infra attempt class (consumed
     attempt, no abort/pause), accounting semantics unchanged.
  3. scoped verifier binding (⑤): chain attempts MAY use the b32f2cb mirror
     verification channel; enabled flag frozen in the round manifest
     (default: not enabled — round-level independent verifier per §6).
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
ROUND = ROOT / ".agent_runs/selfdev-8/round"
SELECTION = json.loads((ROOT / ".agent_runs/selfdev-4/selection.json").read_text())
MAIN = [t for t in SELECTION["tasks"] if t["set"] == "main"]

ENV = dict(os.environ)
ENV["AGENT_OS_PROVIDER_TIMEOUT_SECONDS"] = "600"
ENV["PYTHONPATH"] = ".:src:packages/contracts/src:packages/os_core/src"
PY = str(ROOT / ".venv/bin/python")

TIMEOUTS = {"baseline": 1800, "chain": 2400}

# §3.5(3): scoped verifier 绑定(⑤)默认不启用 — 沿用 §6 独立 round-level verifier。
# 该开关在 round manifest 中冻结;启用与否不改变 driver 记账语义。
SCOPED_VERIFIER_ENABLED = False

# ---------------------------------------------------------------------------
# §3.5(1) abort classifier — typed 三面映射(prereg review P1-1 修正版)
# 映射表在 freeze manifest 中逐字绑定;白名单成员集合逐字承接 E7 冻结值。
# ---------------------------------------------------------------------------

# (a) 消耗侧 INVALID_PROVIDER 分类:provider 失败一律以 typed ProviderFailure.code 归类;
#     仅 AUTHENTICATION_FAILED(403 配额族)触发 §0.3 暂停。
PROVIDER_FAILURE_CODES = (
    "RATE_LIMITED",
    "TIMEOUT",
    "MALFORMED",
    "REFUSED",
    "UNAVAILABLE",
    "AUTHENTICATION_FAILED",
)

# (b) 尝试失败类:以 DenialReasonCode(①)归类。
DENIAL_REASON_CODES = (
    "PROPOSAL_AMBIGUOUS_OR_UNAUTHORIZED",
    "PROPOSAL_ENVELOPE_KEYS",
    "PROPOSAL_CONTENT_MISSING",
    "PROPOSAL_PATH_MISMATCH",
    "DIFF_VALIDATION_FAILED",
    "WORKSPACE_CHANGED_SINCE_PROPOSAL",
    "PATH_NOT_RELATIVE",
    "PATH_ESCAPES_WORKSPACE",
    "SYMLINK_FORBIDDEN",
    "WORKSPACE_STATE_RESERVED",
    "DIFF_MALFORMED",
    "DIFF_CREATES_EXISTING_FILE",
    "DIFF_TARGET_MISSING",
    "DIFF_CONTEXT_MISMATCH",
    "TEST_COMMAND_NOT_ALLOWLISTED",
    "SHELL_COMMAND_NOT_ALLOWLISTED",
    "SHELL_PROGRAM_DENIED",
    "SHELL_METACHARACTER_DENIED",
    "SHELL_PATH_OUTSIDE_WORKSPACE",
    "INVALID_CAPABILITY_ARGUMENTS",
)

# (c) genuine-infra 中止白名单:成员集合**逐字承接 E7 冻结值**(10 项,不得扩张)。
#     判定机制升级为 typed 面——E7 成员中 BENCHMARK_CONTAINER_UNAVAILABLE /
#     BENCHMARK_CONTAINER_BUILD_FAILED 与 BenchmarkContainerError typed code
#     常量同串;RUN_DENIED workspace 明细族(TaskConfigurationDrift 亦同);
#     docker daemon stderr / BENCHMARK_RESTORE_FAILED / workspace_restore_failed
#     无 typed 信号,保留自由文本匹配并显式声明为残余。
GENUINE_INFRA_WHITELIST = (  # E7 冻结值,逐字承接
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
BENCHMARK_CONTAINER_TYPED_CODES = (  # 判定面声明,不扩张集合
    "BENCHMARK_CONTAINER_UNAVAILABLE",
    "BENCHMARK_CONTAINER_BUILD_FAILED",
)
RUN_DENIED_WORKSPACE_DETAIL_MARKERS = (
    "benchmark workspace missing",
    "benchmark workspace is not clean",
    "benchmark workspace head drift",
)

ABORT_CLASSIFIER_MAPPING = {
    "consumption_side_invalid_provider": {
        "typed_surface": "ProviderFailure.code",
        "codes": PROVIDER_FAILURE_CODES,
        "pause_trigger_only": "AUTHENTICATION_FAILED",
    },
    "attempt_failure_classes": {
        "typed_surface": "DenialReasonCode",
        "codes": DENIAL_REASON_CODES,
    },
    "genuine_infra_whitelist": {
        "typed_surface": (
            "BenchmarkContainerError.code + SelfDevelopmentValidationError"
            "(RUN_DENIED) workspace detail family + TaskConfigurationDrift type"
        ),
        "member_set": "E7 frozen whitelist (byte-identical, 10 members)",
        "members": list(GENUINE_INFRA_WHITELIST),
        "typed_code_overlap": list(BENCHMARK_CONTAINER_TYPED_CODES),
        "declared_residual": "docker daemon stderr / BENCHMARK_RESTORE_FAILED / "
                             "workspace_restore_failed have no typed signal; "
                             "free-text matching retained",
    },
}


def classify_attempt(stderr_tail: str) -> dict[str, object]:
    """§3.5(1) typed abort classifier — returns mapping + class decision.

    判定顺序(最特异面优先,避免子串冲突):genuine-infra 白名单(E7 冻结 10 项,
    含 typed 常量同串成员与自由文本残余)→ DenialReasonCode →
    ProviderFailure.code → FAILED_UNCLASSIFIED 残余。
    """
    if any(m in stderr_tail for m in GENUINE_INFRA_WHITELIST):
        return {"class": "GENUINE_INFRA", "surface": "genuine-infra whitelist (typed)"}
    if any(c in stderr_tail for c in DENIAL_REASON_CODES):
        return {"class": "ATTEMPT_FAILURE", "surface": "DenialReasonCode"}
    if any(c in stderr_tail for c in PROVIDER_FAILURE_CODES):
        return {"class": "INVALID_PROVIDER", "surface": "ProviderFailure.code"}
    return {"class": "FAILED_UNCLASSIFIED", "surface": "residual"}


def _is_quota_event(stderr_tail: str) -> bool:
    """Account-quota signatures (403) — the ONLY pause trigger (prereg §0.3)."""
    return "AUTHENTICATION_FAILED" in stderr_tail or "HTTP 403" in stderr_tail


def _is_genuine_infra(stderr_tail: str) -> bool:
    """Whitelist abort via typed classifier (legacy-name shim for §3.5(1))."""
    return classify_attempt(stderr_tail)["class"] == "GENUINE_INFRA"


def _attempt_failure_class(stderr_tail: str) -> str | None:
    """DenialReasonCode 命中 → 既有尝试失败类(driver7 记账语义不变)。"""
    if any(m in stderr_tail for m in ("BASELINE_DIFF_INVALID", "provider diff failed validation")) or "DIFF_VALIDATION_FAILED" in stderr_tail or "DIFF_MALFORMED" in stderr_tail:
        return "DIFF_INVALID"
    if "must contain only path and" in stderr_tail or "PROPOSAL_PATH_MISMATCH" in stderr_tail:
        return "INVALID_ENVELOPE"
    if any(m in stderr_tail for m in ("BASELINE_DIFF_REJECTED", "patch does not apply", "unified diff context mismatch", "WORKSPACE_CHANGED_SINCE_PROPOSAL", "PATH_NOT_RELATIVE", "PATH_ESCAPES_WORKSPACE", "DIFF_TARGET_MISSING", "DIFF_CONTEXT_MISMATCH", "TEST_COMMAND_NOT_ALLOWLISTED", "SHELL_COMMAND_NOT_ALLOWLISTED")):
        return "APPLY_FAILED"
    return None


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
        # §3.5(1) typed classifier:provider weather → INVALID_PROVIDER(消耗尝试,
        # 不中止/暂停);denial reason → 尝试失败类;genuine-infra 白名单 → 中止;
        # 残余 → FAILED_UNCLASSIFIED。记账语义与 driver7 逐字相同。
        cl = classify_attempt(stderr_tail)
        cls = cl["class"]
        if cls == "INVALID_PROVIDER":
            out_file.write_text(json.dumps({
                "instance_id": instance_id, "arm": arm, "attempt": attempt,
                "attempt_class": "INVALID_PROVIDER",
                "classifier": cl,
                "stderr_tail": stderr_tail,
            }))
            return {"attempt_class": "INVALID_PROVIDER", "classifier": cl}
        if cls == "ATTEMPT_FAILURE":
            fail_class = _attempt_failure_class(stderr_tail) or "FAILED_UNCLASSIFIED"
            out_file.write_text(json.dumps({
                "instance_id": instance_id, "arm": arm, "attempt": attempt,
                "attempt_class": fail_class,
                "classifier": cl,
                "stderr_tail": stderr_tail,
            }))
            return {"attempt_class": fail_class, "classifier": cl}
        if cls == "GENUINE_INFRA":
            out_file.write_text(json.dumps({
                "instance_id": instance_id, "arm": arm, "attempt": attempt,
                "infra_error": True,
                "attempt_class": "FAILED_UNCLASSIFIED",
                "classifier": cl,
                "returncode": proc.returncode,
                "stderr_tail": stderr_tail,
            }))
            return {"infra_error": True, "attempt_class": "FAILED_UNCLASSIFIED", "classifier": cl}
        out_file.write_text(json.dumps({
            "instance_id": instance_id, "arm": arm, "attempt": attempt,
            "infra_error": False,
            "attempt_class": "FAILED_UNCLASSIFIED",
            "classifier": cl,
            "returncode": proc.returncode,
            "stderr_tail": stderr_tail,
        }))
        return {"attempt_class": "FAILED_UNCLASSIFIED", "infra_error": False, "classifier": cl}
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


PAUSE_PROBE_INTERVAL_S = 300
PAUSE_BUDGET_TOTAL_S = 6 * 3600
_pause_budget_remaining_s = PAUSE_BUDGET_TOTAL_S


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
