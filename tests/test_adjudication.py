"""Adjudication handoff (harness piece 3): packet assembly + verify-and-narrate.

`build_adjudication_packet` hands raw + frozen thresholds + protocol to the independent
kimicode adjudicator. `verify_adjudication_integrity` is Claude's verify-and-narrate: it
recomputes the section-3 quantities + gate booleans from the RAW data and confirms
kimicode's verdict is arithmetically faithful and used the FROZEN theta -- WITHOUT
re-judging MET/NOT_MET (that is kimicode's) and without touching the founder's final
conclusion. The live `kimi` invocation is an orchestration step, deliberately NOT
embedded in the harness module (no subprocess in mechanism-adjacent code).
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from aac.g_eco import GEcoHalt
from experiments import g_eco

AUDIT = tuple(range(1810, 1815))
RFINAL_SLICE = tuple(range(1900, 1906))
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


def _faithful_verdict(raw_payload: dict, freeze_dir: Path) -> dict:
    raw = raw_payload["raw"]
    th = json.loads((freeze_dir / "g_eco.thresholds.json").read_text())
    vh = raw["VH"]
    vh_er = sum(1 for r in vh if r["full_region"]) / len(vh)
    bb = g_eco._battery_best(raw)
    bbr = raw[bb]
    bb_er = sum(1 for r in bbr if r["full_region"]) / len(bbr)
    pairwise = sum(1 for v, b in zip(vh, bbr) if v["full_region"] and not b["full_region"])
    vh_med = g_eco._median([r["irreversible_loss"] for r in vh])
    g5 = all(vh_med < g_eco._median([r["irreversible_loss"] for r in raw[b]])
             for b in g_eco.RFINAL_BATTERY_NAMES)
    boot = th["verdict_mechanics"]["bootstrap"]
    diffs = [v["survival_steps"] - b["survival_steps"] for v, b in zip(vh, bbr)]
    g4_p = g_eco._wilcoxon_p_two_sided(diffs)
    g4_lo, _g4_hi = g_eco._bootstrap_ci(diffs, B=boot["B"], seed=boot["resample_seed"])
    g4 = (g4_p < 0.05) and (g4_lo > 0)
    return {
        "reported": {
            "enter_rate_vh": vh_er,
            "battery_best_arm": bb,
            "battery_best_enter_rate": bb_er,
            "pairwise_vh_strict_count": pairwise,
            "vh_irreversible_median": vh_med,
            "gate4_p": g4_p,
            "gate4_ci_lower": g4_lo,
        },
        "thresholds_used": {"theta_hi": th["theta_hi"], "theta_lo": th["theta_lo"]},
        "gates": {
            "G-Eco-1": vh_er >= th["theta_hi"],
            "G-Eco-2": bb_er <= th["theta_lo"],
            "G-Eco-3": pairwise >= 22,
            "G-Eco-4": g4,
            "G-Eco-5": g5,
        },
        "verdict": "C_NOT_SUPPORTED",
    }


class TestAdjudication(unittest.TestCase):
    def _raw(self, tmp: Path) -> dict:
        root = Path(__file__).resolve().parents[1]
        _unlocked(tmp)
        mech = {
            rel: hashlib.sha256((root / rel).read_bytes()).hexdigest()
            for rel in ("experiments/g_eco.py", "src/aac/g_eco.py", "src/envs/ecological_4cond.py")
        }
        lock = tmp / "prereg.lock"
        lock.write_text(json.dumps({
            "prereg_id": "t", "spec_file_sha256": "0" * 64, "spec_sha256": "0" * 64,
            "mechanism_files": mech, "target_head": None, "frozen_at": "2026-06-27T00:00:00+00:00",
        }))
        return g_eco.run_rfinal(
            tmp, audit_seeds=AUDIT, rfinal_seeds=RFINAL_SLICE, run_steps=RUN_STEPS,
            prereg_lock=lock, prereg_target_root=root,
        )

    def test_packet_refuses_when_not_adjudication_ready(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            raw = self._raw(tmp)
            raw["adjudication_ready"] = False
            with self.assertRaises(GEcoHalt) as cm:
                g_eco.build_adjudication_packet(tmp, raw, tmp / "packet")
            self.assertEqual(cm.exception.code, "ADJUDICATION_NOT_READY")

    def test_packet_assembles(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            raw = self._raw(tmp)
            out = g_eco.build_adjudication_packet(tmp, raw, tmp / "packet")
            for f in ("g_eco.rfinal.raw.json", "g_eco.thresholds.json", "ADJUDICATION_TASK.json"):
                self.assertTrue((tmp / "packet" / f).exists())
                self.assertIn(f, out["files"])

    def test_integrity_ok_on_faithful_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            raw = self._raw(tmp)
            report = g_eco.verify_adjudication_integrity(_faithful_verdict(raw, tmp), raw, tmp)
            self.assertTrue(report["integrity_ok"], report["mismatches"])

    def test_integrity_fails_on_fabricated_number(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            raw = self._raw(tmp)
            v = _faithful_verdict(raw, tmp)
            v["reported"]["enter_rate_vh"] = v["reported"]["enter_rate_vh"] + 0.5  # fabricate
            report = g_eco.verify_adjudication_integrity(v, raw, tmp)
            self.assertFalse(report["integrity_ok"])
            self.assertIn("enter_rate_vh", report["mismatches"])

    def test_integrity_fails_on_ragged_rows(self) -> None:
        # kimicode LOW (2026-06-27): unequal per-arm row counts must be flagged, not
        # silently truncated by zip().
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            raw = self._raw(tmp)
            v = _faithful_verdict(raw, tmp)
            raw["raw"]["LIN"] = raw["raw"]["LIN"][:-1]  # drop one row -> ragged
            report = g_eco.verify_adjudication_integrity(v, raw, tmp)
            self.assertFalse(report["integrity_ok"])
            self.assertIn("row_length_mismatch", report["mismatches"])

    def test_integrity_fails_on_nonfrozen_theta(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            raw = self._raw(tmp)
            v = _faithful_verdict(raw, tmp)
            v["thresholds_used"]["theta_hi"] = 0.0  # not the frozen value
            report = g_eco.verify_adjudication_integrity(v, raw, tmp)
            self.assertFalse(report["integrity_ok"])
            self.assertIn("theta_not_frozen", report["mismatches"])


    def test_gate4_stats_known_answers(self) -> None:
        # all-zero diffs -> p == 1.0, CI == (0,0)
        self.assertEqual(g_eco._wilcoxon_p_two_sided([0.0] * 10), 1.0)
        self.assertEqual(g_eco._bootstrap_ci([0.0] * 10, B=200, seed=1), (0.0, 0.0))
        # strongly positive (n=20, all +5): p tiny, CI collapses to (5,5)
        d = [5.0] * 20
        self.assertLess(g_eco._wilcoxon_p_two_sided(d), 0.001)
        self.assertEqual(g_eco._bootstrap_ci(d, B=500, seed=611038), (5.0, 5.0))
        # symmetric mix -> not significant
        self.assertGreater(g_eco._wilcoxon_p_two_sided([1.0, -1.0, 2.0, -2.0, 3.0, -3.0]), 0.05)

    def test_integrity_recomputes_gate4_and_catches_fabrication(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            raw = self._raw(tmp)
            v = _faithful_verdict(raw, tmp)
            report = g_eco.verify_adjudication_integrity(v, raw, tmp)
            self.assertTrue(report["gate4_stat_recomputed"])
            self.assertTrue(report["integrity_ok"], report["mismatches"])
            v["gates"]["G-Eco-4"] = not v["gates"]["G-Eco-4"]  # flip -> inconsistent
            bad = g_eco.verify_adjudication_integrity(v, raw, tmp)
            self.assertFalse(bad["integrity_ok"])
            self.assertIn("G-Eco-4_inconsistent", bad["mismatches"])


if __name__ == "__main__":
    unittest.main()
