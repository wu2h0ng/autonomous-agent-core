"""r-final runner contract (harness piece 2): faithful replay, RAW data only.

`run_rfinal` must: refuse unless Gate-2 is unlocked; re-derive the frozen candidate
and assert it matches the co-signed freeze (faithful replay of the EXACT candidate);
replay the frozen battery+VH over the r-final seeds deterministically; and emit
per-seed/per-arm RAW metrics (full_region / survival_steps / irreversible_loss) with
NO thresholds, NO enter_rate-vs-theta, NO verdict. The verdict belongs to the
independent kimicode adjudicator, on this raw data, per the frozen protocol.

The region metric is `full_region` (region held the whole run) -- the same metric the
calibration theta thresholds are derived from -- NOT "entered at least once".
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from aac.g_eco import GEcoHalt
from experiments import g_eco

# Fast calibration params shared with the Gate-2 tests; small r-final slice for speed.
AUDIT = tuple(range(1810, 1815))
RFINAL_SLICE = tuple(range(1900, 1903))
RUN_STEPS = 12


def _make_unlocked_bundle(tmp: Path) -> None:
    g_eco.write_pregate2_candidate(tmp, audit_seeds=AUDIT)
    # Clear the section-7a halts so the unlock branch is reachable (the real fast
    # calibration halts; that honesty is covered in test_gate2_unlock). Then co-sign.
    p = tmp / "g_eco.baseline_audit.json"
    import hashlib
    data = json.loads(p.read_text(encoding="utf-8"))
    data["halt_booleans"] = {k: False for k in data.get("halt_booleans", {})}
    data.pop("content_hash", None)
    data["content_hash"] = hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    p.write_text(json.dumps(data), encoding="utf-8")
    g_eco.write_gate2_cosign(tmp, founder_id="founder")


class TestRFinalRunner(unittest.TestCase):
    def test_refuses_when_gate2_locked(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            g_eco.write_pregate2_candidate(tmp, audit_seeds=AUDIT)  # no co-sign
            with self.assertRaises(GEcoHalt) as cm:
                g_eco.run_rfinal(tmp, audit_seeds=AUDIT)
            self.assertEqual(cm.exception.code, "GATE2_LOCKED_NO_COSIGN")

    def test_emits_raw_metrics_no_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _make_unlocked_bundle(tmp)
            out = g_eco.run_rfinal(
                tmp, audit_seeds=AUDIT, rfinal_seeds=RFINAL_SLICE, run_steps=RUN_STEPS
            )
            self.assertEqual(out["kind"], "g_eco.rfinal.raw")
            # every r-final arm present, every seed present, raw metrics only
            self.assertEqual(set(out["raw"]), set(g_eco.rfinal_arm_names()))
            for arm, rows in out["raw"].items():
                self.assertEqual([r["seed"] for r in rows], list(RFINAL_SLICE))
                for r in rows:
                    self.assertIn("full_region", r)
                    self.assertIn("survival_steps", r)
                    self.assertIn("irreversible_loss", r)
                    self.assertIsInstance(r["full_region"], bool)
            # NO verdict / threshold leakage anywhere in the payload
            blob = json.dumps(out)
            for forbidden in ("verdict", "theta", "θ", "enter_rate", "battery_best", "C_supported", "PASS"):
                self.assertNotIn(forbidden, blob)

    def test_deterministic_replay(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _make_unlocked_bundle(tmp)
            a = g_eco.run_rfinal(tmp, audit_seeds=AUDIT, rfinal_seeds=RFINAL_SLICE, run_steps=RUN_STEPS)
            b = g_eco.run_rfinal(tmp, audit_seeds=AUDIT, rfinal_seeds=RFINAL_SLICE, run_steps=RUN_STEPS)
            self.assertEqual(a["content_hash"], b["content_hash"])

    def test_refuses_on_candidate_drift(self) -> None:
        # Co-signed candidate was built with AUDIT seeds; re-deriving with DIFFERENT
        # calibration seeds must not silently run a different candidate.
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _make_unlocked_bundle(tmp)
            with self.assertRaises(GEcoHalt) as cm:
                g_eco.run_rfinal(
                    tmp,
                    audit_seeds=tuple(range(1815, 1820)),  # wrong: != co-signed candidate
                    rfinal_seeds=RFINAL_SLICE,
                    run_steps=RUN_STEPS,
                )
            self.assertEqual(cm.exception.code, "RFINAL_CANDIDATE_DRIFT")

    def test_c6_verified_c7_shell_flagged_pending(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _make_unlocked_bundle(tmp)
            out = g_eco.run_rfinal(tmp, audit_seeds=AUDIT, rfinal_seeds=RFINAL_SLICE, run_steps=RUN_STEPS)
            self.assertTrue(out["c6c7"]["shared_substrate_verified"])
            self.assertTrue(out["c6c7"]["no_calibration_refs_in_rfinal"])
            # Honest: C7 shell verification is a required pre-adjudication gate that
            # this piece does NOT yet perform -- it must be False, not silently absent.
            self.assertFalse(out["c6c7"]["c7_shell_verified"])
            self.assertFalse(out["adjudication_ready"])


if __name__ == "__main__":
    unittest.main()
