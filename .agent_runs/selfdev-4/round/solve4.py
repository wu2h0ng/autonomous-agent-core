"""SELFDEV-2 solve determination: independent verifier re-run per prereg §6.

For every chain attempt with an apply_patch proposal in its task events,
extract the proposed content and re-run the independent verifier flow
(checkout base -> write candidate -> apply test patch -> f2p -> p2p ->
restore). Chain-internal outcomes are telemetry only; THIS is the solve
evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path("/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/canonical-convergence-20260715")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages/contracts/src"))
sys.path.insert(0, str(ROOT / "packages/os_core/src"))

from agent_os_core import (  # noqa: E402
    ContainerRunner,
    ContainerVerifierExecutor,
    run_benchmark_verifier,
)
from apps.cli.__main__ import _benchmark_task_from_entry  # noqa: E402

ROUND = ROOT / ".agent_runs/selfdev-4/round"
SELECTION = json.loads((ROOT / ".agent_runs/selfdev-4/selection.json").read_text())
TASKS = {t["instance_id"]: t for t in SELECTION["tasks"] if t["set"] == "main"}


def extract_candidate(attempt_file: Path) -> tuple[str, str] | None:
    data = json.loads(attempt_file.read_text())
    events = (data.get("task") or {}).get("events") or []
    for event in events:
        if event.get("event_type") != "ACTION_PROPOSED":
            continue
        action = (event.get("payload") or {}).get("action") or {}
        if action.get("capability_id") != "workspace.apply_patch":
            continue
        args = json.loads(action.get("arguments_json") or "{}")
        content = args.get("content")
        if isinstance(content, str) and content:
            return ("content", content)
        diff = args.get("diff")
        if isinstance(diff, str) and diff:
            return ("diff", diff)
    return None


def main() -> None:
    for iid, entry in TASKS.items():
        ws = ROOT / entry["workspace_path"]
        test_patch = (
            ROOT / ".agent_runs/selfdev-2/dataset" / "tasks" / iid / "test.patch"
        ).read_text(encoding="utf-8")
        task = _benchmark_task_from_entry(entry)
        executor = ContainerVerifierExecutor(
            runner=ContainerRunner(),
            image_tag=str(entry["image_tag"]),
            repo_root_host=ws.parent,
            gold_file_path=str(entry["gold_file_path"]),
        )
        for attempt in (1, 2):
            attempt_file = ROUND / iid / f"chain-attempt-{attempt}.json"
            verdict_file = ROUND / iid / f"chain-attempt-{attempt}-verdict.json"
            if not attempt_file.exists() or verdict_file.exists():
                continue
            candidate = extract_candidate(attempt_file)
            if candidate is None:
                continue
            kind, payload = candidate
            verdict = run_benchmark_verifier(
                task,
                ws,
                candidate_content=payload if kind == "content" else None,
                candidate_diff=payload if kind == "diff" else None,
                test_patch=test_patch,
                executor=executor,
            )
            record = {
                "instance_id": iid,
                "attempt": attempt,
                "independent_verifier": True,
                "solved": verdict.solved,
                "f2p_passed": verdict.f2p_passed,
                "p2p_passed": verdict.p2p_passed,
                "detail": verdict.detail,
                "evidence_digest": verdict.evidence_digest,
            }
            verdict_file.write_text(json.dumps(record, indent=2))
            print(f"{iid} a{attempt}: solved={verdict.solved} {verdict.detail[:100]}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
