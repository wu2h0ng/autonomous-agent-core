"""Exact-source isolated runner.

This is not a general Python sandbox. It executes only externally supplied,
exactly verified source bytes in an isolated interpreter with a minimal
environment and no inherited secrets.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .freeze_candidate import FreezeCandidateManifest, verify_freeze_candidate


def run_sealed_qualification(
    manifest: FreezeCandidateManifest, repo_root: Path
) -> dict[str, object]:
    root = repo_root.resolve()
    verify_freeze_candidate(manifest, root)
    with tempfile.TemporaryDirectory(prefix="nonoracle-sealed-") as directory:
        isolated = Path(directory)
        for binding in manifest.file_bindings:
            if not binding.path.startswith("research_tools/nonoracle_discovery/"):
                continue
            target = isolated / binding.path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / binding.path, target)
        script = (
            "import json,sys;"
            f"sys.path.insert(0,{str(isolated)!r});"
            "from research_tools.nonoracle_discovery.qualification import run_synthetic_qualification;"
            "r=run_synthetic_qualification();"
            "print(json.dumps({'mode':r.mode,'receipt_digest':r.receipt_digest},sort_keys=True))"
        )
        completed = subprocess.run(
            [sys.executable, "-I", "-S", "-c", script],
            cwd=isolated,
            env={"PATH": os.defpath, "PYTHONHASHSEED": "0"},
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise ValueError("sealed runner returned a non-object")
    return value
