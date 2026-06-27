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
    return {
        "reported": {
            "enter_rate_vh": vh_er,
            "battery_best_arm": bb,
            "battery_best_enter_rate": bb_er,
            "pairwise_vh_strict_count": pairwise,
            "vh_irreversible_median": vh_med,
        },
        "thresholds_used": {"theta_hi": th["theta_hi"], "theta_lo": th["theta_lo"]},
        "gates": {
            "G-Eco-1": vh_er >= th["theta_hi"],
            "G-Eco-2": bb_er <= th["theta_lo"],
            "G-Eco-3": pairwise >= 22,
            "G-Eco-5": g5,
        },
        "verdict": "C_NOT_SUPPORTED",
    }


class TestAdjudication(unittest.TestCase):
    def _raw(self, tmp: Path) -> dict:
        _unlocked(tmp)
        return g_eco.run_rfinal(tmp, audit_seeds=AUDIT, rfinal_seeds=RFINAL_SLICE, run_steps=RUN_STEPS)

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


if __name__ == "__main__":
    unittest.main()
