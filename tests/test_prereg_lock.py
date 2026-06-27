"""Stage-2 prereg.lock double-bind (mechanism-code drift gate).

The founder-chosen double-bind: the Stage-1 co-sign pins the candidate; the Stage-2
prereg.lock pins the mechanism CODE behind it. `run_rfinal` raw data is NOT
adjudication-ready unless a prereg.lock is present AND every bound mechanism file
hash matches the current bytes (constitution gate #23). Drift -> RFINAL_PREREG_DRIFT.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from aac.g_eco import GEcoHalt
from experiments import g_eco

REPO_ROOT = Path(__file__).resolve().parents[1]
MECH = ("experiments/g_eco.py", "src/aac/g_eco.py", "src/envs/ecological_4cond.py")
AUDIT = tuple(range(1810, 1815))
RFINAL_SLICE = tuple(range(1900, 1903))
RUN_STEPS = 12


def _unlocked(tmp: Path) -> None:
    g_eco.write_pregate2_candidate(tmp, audit_seeds=AUDIT)
    p = tmp / "g_eco.baseline_audit.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["halt_booleans"] = {k: False for k in data.get("halt_booleans", {})}
    data.pop("content_hash", None)
    data["content_hash"] = hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    p.write_text(json.dumps(data), encoding="utf-8")
    g_eco.write_gate2_cosign(tmp, founder_id="founder")


def make_prereg_lock(lock_path: Path, *, tamper: bool = False) -> None:
    files = {rel: hashlib.sha256((REPO_ROOT / rel).read_bytes()).hexdigest() for rel in MECH}
    if tamper:
        files[MECH[0]] = "0" * 64  # pretend the mechanism file changed after freeze
    lock = {
        "prereg_id": "g-eco-test-lock",
        "spec_file_sha256": "0" * 64,
        "spec_sha256": "0" * 64,
        "mechanism_files": files,
        "target_head": None,
        "frozen_at": "2026-06-27T00:00:00+00:00",
    }
    lock_path.write_text(json.dumps(lock), encoding="utf-8")


def _run(tmp: Path, **kw):
    return g_eco.run_rfinal(
        tmp, audit_seeds=AUDIT, rfinal_seeds=RFINAL_SLICE, run_steps=RUN_STEPS, **kw
    )


class TestStage2PreregLock(unittest.TestCase):
    def test_no_lock_means_not_adjudication_ready(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _unlocked(tmp)
            out = _run(tmp)  # no prereg_lock
            self.assertFalse(out["c6c7"]["prereg_lock_verified"])
            self.assertFalse(out["adjudication_ready"])

    def test_verified_lock_makes_adjudication_ready(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _unlocked(tmp)
            lock = tmp / "prereg.lock"
            make_prereg_lock(lock)
            out = _run(tmp, prereg_lock=lock, prereg_target_root=REPO_ROOT)
            self.assertTrue(out["c6c7"]["prereg_lock_verified"])
            self.assertTrue(out["adjudication_ready"])
            self.assertEqual(out["prereg_id"], "g-eco-test-lock")

    def test_mechanism_drift_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _unlocked(tmp)
            lock = tmp / "prereg.lock"
            make_prereg_lock(lock, tamper=True)  # bound hash != current bytes
            with self.assertRaises(GEcoHalt) as cm:
                _run(tmp, prereg_lock=lock, prereg_target_root=REPO_ROOT)
            self.assertEqual(cm.exception.code, "RFINAL_PREREG_DRIFT")

    def test_missing_lock_path_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _unlocked(tmp)
            with self.assertRaises(GEcoHalt) as cm:
                _run(tmp, prereg_lock=tmp / "nope.lock", prereg_target_root=REPO_ROOT)
            self.assertEqual(cm.exception.code, "RFINAL_PREREG_LOCK_MISSING")


if __name__ == "__main__":
    unittest.main()
