"""Regenerate SHA-256 digests for the four frozen top-level unit files.

Usage (from the unit directory):
    python regenerate_manifest.py

This overwrites the ``manifest`` block in ``unit.yaml`` with fresh digests
for ``snapshot.yaml``, ``mission.yaml``, ``events.yaml`` and
``expected_outcomes.yaml``. It is intended for reproducibility during unit
design and review; it is not imported by the evaluation harness at runtime.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


FROZEN_FILES = [
    "snapshot.yaml",
    "mission.yaml",
    "events.yaml",
    "expected_outcomes.yaml",
]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def regenerate(unit_dir: Path) -> None:
    unit_file = unit_dir / "unit.yaml"
    if not unit_file.is_file():
        raise FileNotFoundError(f"missing {unit_file}")

    original = unit_file.read_text(encoding="utf-8")

    manifest_lines = ["manifest:"]
    for name in FROZEN_FILES:
        digest = _sha256_file(unit_dir / name)
        manifest_lines.append(f"  {name}: sha256:{digest}")

    new_manifest = "\n".join(manifest_lines) + "\n"

    # Replace the existing manifest block with the regenerated one.
    pattern = re.compile(r"^manifest:\n(?:  \S+: sha256:[a-f0-9]+\n)+", re.MULTILINE)
    if not pattern.search(original):
        raise ValueError("could not locate manifest block in unit.yaml")

    updated = pattern.sub(new_manifest, original)
    unit_file.write_text(updated, encoding="utf-8")
    print(f"Updated manifest in {unit_file}")
    for line in manifest_lines:
        print(line)


if __name__ == "__main__":
    regenerate(Path(__file__).parent)
