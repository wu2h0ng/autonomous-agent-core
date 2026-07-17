import hashlib
import json
from pathlib import Path

import experiments.continual_retention_f1 as package


ROOT = Path(__file__).parents[1]
MANIFEST = (
    ROOT / "docs/pre_spec/CLS-F1-QUALIFICATION.EXACT-CONTENT-MANIFEST-2026-07-18.json"
)


def test_candidate_manifest_is_exact_and_non_active():
    manifest = json.loads(MANIFEST.read_text())
    assert manifest["status"] == ["FREEZE_CANDIDATE", "NOT_FROZEN", "NOT_RUN"]
    assert manifest["active_freeze_input"] is False
    for path, digest in manifest["artifact_sha256"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest


def test_package_cannot_mint_freeze_or_result_authority():
    for forbidden in ("freeze", "authorize_run", "run_result", "mint_receipt"):
        assert not hasattr(package, forbidden)
