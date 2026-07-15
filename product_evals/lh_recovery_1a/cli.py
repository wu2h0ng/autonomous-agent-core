"""Local public-surface utility for the LH-RECOVERY-1A Task 7 harness."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path

from apps.api_server.app import AgentOSApplication


@dataclass(frozen=True, slots=True)
class EpisodePaths:
    workspace: Path
    database: Path


def episode_paths(root: Path, case_id: str, arm: str) -> EpisodePaths:
    if (
        type(case_id) is not str
        or not case_id
        or Path(case_id).name != case_id
        or arm not in {"C", "F", "R", "K"}
    ):
        raise ValueError("case_id and arm must be safe declared components")
    base = Path(root) / "episodes" / case_id / arm
    return EpisodePaths(
        workspace=base / "workspace",
        database=base / "state" / "agent-os.db",
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="lh-recovery-1a")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--arm", required=True, choices=("C", "F", "R", "K"))
    parser.add_argument("task_id")
    args = parser.parse_args()
    paths = episode_paths(args.root, args.case_id, args.arm)
    paths.database.parent.mkdir(parents=True, exist_ok=True)
    paths.workspace.mkdir(parents=True, exist_ok=True)
    application = AgentOSApplication(
        database=paths.database,
        workspace=paths.workspace,
    )
    print(
        json.dumps(
            application.task_json(args.task_id),
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
