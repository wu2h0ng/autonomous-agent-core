"""Gate-2 unlock verifier contract (r-final harness, Stage 1: founder co-sign).

These pin the unlock predicate: `assert_gate2_unlocked` stays LOCKED by default
and unlocks ONLY on a founder co-sign whose recorded hashes match the exact
frozen bundle bytes, with §9 static firewalls passing and no §7a halt fired.

Honesty note (Stage 1): the co-sign object is a deliberate-action + tamper-evidence
gate, NOT a cryptographic barrier — a JSON `cosigned_by` marker is forgeable by any
writer. The identity teeth come from the Stage-2 prereg.lock + meta-runner
actor!=reviewer gate. These tests therefore assert FORM (marker + exact-hash
binding + firewalls + audit), not unforgeable identity.

No mechanism is exercised beyond the frozen candidate bundle. No r-final seed runs.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from aac.g_eco import GEcoHalt
from experiments import g_eco


def _make_bundle(tmp: Path) -> None:
    # Same fast params as the existing pre-Gate-2 candidate test.
    g_eco.write_pregate2_candidate(tmp, audit_seeds=tuple(range(1810, 1815)))


def _clear_audit_halts(tmp: Path) -> None:
    """Clear the section-7a halt booleans on the bundle's audit, then re-hash.

    The fast 5-seed calibration legitimately HALTS (VH approx MINIMAX indistinguishable;
    ablation hitchhikes) -- that honest outcome is asserted by test_locked_when_audit_halts.
    To exercise the verifier's UNLOCK branch deterministically (decoupled from the
    mechanism's empirical verdict, which only kimicode decides on real r-final seeds),
    we clear only the audit's halt booleans here and leave every frozen
    rate/threshold/battery value untouched.
    """
    p = tmp / "g_eco.baseline_audit.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["halt_booleans"] = {k: False for k in data.get("halt_booleans", {})}
    data.pop("content_hash", None)
    data["content_hash"] = hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    p.write_text(json.dumps(data), encoding="utf-8")


class TestGate2Unlock(unittest.TestCase):
    def test_locked_by_default_without_cosign(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _make_bundle(tmp)
            with self.assertRaises(GEcoHalt) as cm:
                g_eco.assert_gate2_unlocked(tmp)
            self.assertEqual(cm.exception.code, "GATE2_LOCKED_NO_COSIGN")

    def test_unlocks_with_valid_founder_cosign(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _make_bundle(tmp)
            _clear_audit_halts(tmp)  # fixture: reach the unlock branch; not a verdict
            g_eco.write_gate2_cosign(tmp, founder_id="founder")
            ctx = g_eco.assert_gate2_unlocked(tmp)
            self.assertTrue(ctx["gate2_unlocked"])
            self.assertEqual(ctx["cosigned_by"], "founder")
            self.assertEqual(tuple(ctx["rfinal_seeds"]), tuple(range(1900, 1930)))
            self.assertTrue(ctx["static_firewalls_verified"])

    def test_locked_when_audit_halts(self) -> None:
        # The real fast-calibration audit HALTS; even with a valid co-sign the gate
        # must stay locked (do not unlock a section-7a-halted candidate).
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _make_bundle(tmp)
            g_eco.write_gate2_cosign(tmp, founder_id="founder")
            with self.assertRaises(GEcoHalt) as cm:
                g_eco.assert_gate2_unlocked(tmp)
            self.assertEqual(cm.exception.code, "GATE2_AUDIT_HALT")

    def test_cosign_requires_founder_id(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _make_bundle(tmp)
            with self.assertRaises(GEcoHalt) as cm:
                g_eco.write_gate2_cosign(tmp, founder_id="  ")
            self.assertEqual(cm.exception.code, "GATE2_COSIGN_NO_FOUNDER")

    def test_locked_when_frozen_file_swapped_after_cosign(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _make_bundle(tmp)
            g_eco.write_gate2_cosign(tmp, founder_id="founder")
            # Re-generate the bundle with DIFFERENT calibration seeds: a different
            # candidate now sits on disk, but the co-sign still records the old
            # hashes. Swapping the frozen candidate after co-sign must stay locked.
            g_eco.write_pregate2_candidate(tmp, audit_seeds=tuple(range(1815, 1820)))
            with self.assertRaises(GEcoHalt) as cm:
                g_eco.assert_gate2_unlocked(tmp)
            self.assertEqual(cm.exception.code, "GATE2_COSIGN_HASH_MISMATCH")

    def test_locked_when_cosign_self_tampered(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _make_bundle(tmp)
            g_eco.write_gate2_cosign(tmp, founder_id="founder")
            cosign_path = tmp / g_eco.GATE2_COSIGN_FILE
            data = json.loads(cosign_path.read_text(encoding="utf-8"))
            # Flip a recorded hash but leave content_hash stale -> tamper-evident.
            first = next(iter(data["frozen_artifacts"]))
            data["frozen_artifacts"][first] = "0" * 64
            cosign_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(GEcoHalt) as cm:
                g_eco.assert_gate2_unlocked(tmp)
            self.assertEqual(cm.exception.code, "GATE2_COSIGN_TAMPERED")

    def test_locked_when_cosign_marker_wrong(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _make_bundle(tmp)
            g_eco.write_gate2_cosign(tmp, founder_id="founder")
            cosign_path = tmp / g_eco.GATE2_COSIGN_FILE
            data = json.loads(cosign_path.read_text(encoding="utf-8"))
            data["marker"] = "NOT_FROZEN"
            # Re-hash so the content_hash is self-consistent: isolates the marker check.
            data.pop("content_hash", None)
            data["content_hash"] = hashlib.sha256(
                json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            cosign_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(GEcoHalt) as cm:
                g_eco.assert_gate2_unlocked(tmp)
            self.assertEqual(cm.exception.code, "GATE2_COSIGN_INVALID")

    def test_locked_when_audit_halt_booleans_empty(self) -> None:
        # kimicode review (2026-06-27, MED): an EMPTY halt_booleans must NOT read as
        # "no halt" -- an empty map means the section-7a audit never produced verdicts.
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _make_bundle(tmp)
            p = tmp / "g_eco.baseline_audit.json"
            data = json.loads(p.read_text(encoding="utf-8"))
            data["halt_booleans"] = {}
            data.pop("content_hash", None)
            data["content_hash"] = hashlib.sha256(
                json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            p.write_text(json.dumps(data), encoding="utf-8")
            g_eco.write_gate2_cosign(tmp, founder_id="founder")
            with self.assertRaises(GEcoHalt) as cm:
                g_eco.assert_gate2_unlocked(tmp)
            self.assertEqual(cm.exception.code, "GATE2_AUDIT_INCOMPLETE")

    def test_locked_when_cosign_seeds_mismatch(self) -> None:
        # kimicode review (2026-06-27, LOW): the co-signed seed ranges must be
        # validated, not just the module constants.
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _make_bundle(tmp)
            _clear_audit_halts(tmp)
            g_eco.write_gate2_cosign(tmp, founder_id="founder")
            cosign_path = tmp / g_eco.GATE2_COSIGN_FILE
            data = json.loads(cosign_path.read_text(encoding="utf-8"))
            data["seeds"]["rfinal"] = [1810, 1839]  # overlaps calibration band
            data.pop("content_hash", None)
            data["content_hash"] = hashlib.sha256(
                json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            cosign_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(GEcoHalt) as cm:
                g_eco.assert_gate2_unlocked(tmp)
            self.assertEqual(cm.exception.code, "GATE2_COSIGN_SEED_MISMATCH")

    def test_locked_when_bundle_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            _make_bundle(tmp)
            g_eco.write_gate2_cosign(tmp, founder_id="founder")
            (tmp / "g_eco.thresholds.json").unlink()
            with self.assertRaises(GEcoHalt):
                # verify_pregate2_candidate_bundle fires first on the missing file.
                g_eco.assert_gate2_unlocked(tmp)


if __name__ == "__main__":
    unittest.main()
