from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Mapping


REQUIRED_PATHS = frozenset(
    {
        "experiments/continual_retention_f1/__init__.py",
        "experiments/continual_retention_f1/baselines.py",
        "experiments/continual_retention_f1/contracts.py",
        "experiments/continual_retention_f1/dual_store.py",
        "experiments/continual_retention_f1/fixture.py",
        "experiments/continual_retention_f1/harness.py",
        "experiments/continual_retention_f1/manifest.py",
        "experiments/continual_retention_f1/oracle.py",
        "experiments/continual_retention_f1/qualification.py",
        "experiments/continual_retention_f1/scorer.py",
        "tests/test_continual_retention_f1.py",
        "tests/test_cls_f1_qualification_freeze_candidate.py",
        "docs/superpowers/specs/2026-07-18-cls-f1-qualification-design.md",
        "docs/superpowers/plans/2026-07-18-cls-f1-qualification.md",
        "docs/pre_spec/CLS-F1-QUALIFICATION.PREREG-CANDIDATE-2026-07-18.json",
    }
)


def verify_candidate_manifest(root: Path, manifest: Mapping[str, object]) -> bool:
    if manifest.get("status") != ["FREEZE_CANDIDATE", "NOT_FROZEN", "NOT_RUN"]:
        raise ValueError("manifest status drift")
    if manifest.get("active_freeze_input") is not False:
        raise ValueError("manifest cannot activate freeze authority")
    bindings = manifest.get("artifact_sha256")
    if not isinstance(bindings, dict) or set(bindings) != REQUIRED_PATHS:
        raise ValueError("manifest exact required paths drift")
    for relative_path, expected in bindings.items():
        relative = Path(relative_path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.as_posix() != relative_path
        ):
            raise ValueError("manifest unsafe path")
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError("manifest path must be a regular file")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"manifest digest drift: {relative_path}")
    return True
