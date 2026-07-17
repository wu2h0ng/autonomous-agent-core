import hashlib
import json
from pathlib import Path

import experiments.continual_retention_f1 as package
import pytest
from experiments.continual_retention_f1.manifest import verify_candidate_manifest


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
    assert verify_candidate_manifest(ROOT, manifest)


def test_manifest_rejects_deleted_or_extra_self_resigned_binding():
    manifest = json.loads(MANIFEST.read_text())
    deleted = json.loads(json.dumps(manifest))
    deleted["artifact_sha256"].pop("experiments/continual_retention_f1/scorer.py")
    with pytest.raises(ValueError, match="exact required paths"):
        verify_candidate_manifest(ROOT, deleted)
    extra = json.loads(json.dumps(manifest))
    extra["artifact_sha256"]["README.md"] = hashlib.sha256(
        (ROOT / "README.md").read_bytes()
    ).hexdigest()
    with pytest.raises(ValueError, match="exact required paths"):
        verify_candidate_manifest(ROOT, extra)


def test_package_cannot_mint_freeze_or_result_authority():
    for forbidden in ("freeze", "authorize_run", "run_result", "mint_receipt"):
        assert not hasattr(package, forbidden)
