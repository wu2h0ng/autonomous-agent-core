"""G-ECO-REOPEN-1 experiment CLI.

The CLI refuses r-final execution unless a prereg.lock is supplied and the
current mechanism bytes match the lock. Scientific verdicts are emitted only by
the adjudication mode over raw frozen-result JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from aac.g_eco_reopen import (
    G_ECO_REOPEN_1_SEEDS,
    PREREG_ID,
    adjudicate_nbsc_result,
    assert_fresh_seed_allocation,
    finalize_locked_nbsc_result,
    run_nbsc_battery,
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON object required: {path}")
    return data


def _verify_prereg_lock(
    lock_path: Path,
    *,
    target_dir: Path,
    spec_path: Path,
    seed_allocation_path: Path,
) -> dict[str, Any]:
    lock = _load_json(lock_path)
    if lock.get("prereg_id") != PREREG_ID:
        raise RuntimeError(
            f"prereg_id mismatch: expected {PREREG_ID}, got {lock.get('prereg_id')!r}"
        )
    mechanism_files = lock.get("mechanism_files")
    if not isinstance(mechanism_files, dict) or not mechanism_files:
        raise RuntimeError("prereg.lock missing mechanism_files")
    drift: list[str] = []
    for rel, expected_hash in sorted(mechanism_files.items()):
        path = target_dir / rel
        if not path.is_file():
            drift.append(f"missing:{rel}")
        elif _sha256_file(path) != expected_hash:
            drift.append(f"modified:{rel}")
    if _sha256_file(spec_path) != lock.get("spec_file_sha256"):
        drift.append("modified:prereg_spec_source")

    seed_rel = os.path.relpath(seed_allocation_path.resolve(), target_dir.resolve())
    if mechanism_files.get(seed_rel) != _sha256_file(seed_allocation_path):
        drift.append(f"seed-allocation-not-locked:{seed_rel}")
    if drift:
        raise RuntimeError("prereg.lock mechanism drift: " + ", ".join(drift))
    return lock


def run_smoke(args: argparse.Namespace) -> int:
    assert_fresh_seed_allocation(G_ECO_REOPEN_1_SEEDS)
    result = run_nbsc_battery(G_ECO_REOPEN_1_SEEDS["smoke_determinism_only"])
    payload = {
        "mode": "smoke",
        "smoke_not_evidence": True,
        "result": result,
    }
    _write_json(args.out, payload)
    print(json.dumps({"ok": True, "out": str(args.out)}, sort_keys=True))
    return 0


def run_rfinal(args: argparse.Namespace) -> int:
    lock = _verify_prereg_lock(
        args.prereg_lock,
        target_dir=args.target_dir,
        spec_path=args.spec,
        seed_allocation_path=args.seed_allocation,
    )
    result = finalize_locked_nbsc_result(
        run_nbsc_battery(G_ECO_REOPEN_1_SEEDS["r_final"]),
        lock,
        lock_path=str(args.prereg_lock),
    )
    _write_json(args.out, result)
    print(json.dumps({"ok": True, "out": str(args.out)}, sort_keys=True))
    return 0


def run_adjudicate(args: argparse.Namespace) -> int:
    raw = _load_json(args.raw)
    verdict = adjudicate_nbsc_result(raw)
    payload = {
        "prereg_id": raw.get("prereg_id"),
        "raw_result": str(args.raw),
        "verdict": verdict,
    }
    _write_json(args.out, payload)
    print(json.dumps({"ok": True, "out": str(args.out), "verdict": verdict["verdict"]}, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)

    smoke = modes.add_parser("smoke")
    smoke.add_argument("--out", required=True, type=Path)
    smoke.set_defaults(func=run_smoke)

    rfinal = modes.add_parser("run-rfinal")
    rfinal.add_argument("--prereg-lock", required=True, type=Path)
    rfinal.add_argument("--spec", required=True, type=Path)
    rfinal.add_argument("--seed-allocation", required=True, type=Path)
    rfinal.add_argument("--target-dir", default=Path("."), type=Path)
    rfinal.add_argument("--out", required=True, type=Path)
    rfinal.set_defaults(func=run_rfinal)

    adjudicate = modes.add_parser("adjudicate")
    adjudicate.add_argument("--raw", required=True, type=Path)
    adjudicate.add_argument("--out", required=True, type=Path)
    adjudicate.set_defaults(func=run_adjudicate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
