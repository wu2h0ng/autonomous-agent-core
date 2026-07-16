from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agent_os_contracts import SrlEnvironmentEvent, SrlHelpRequest


@dataclass(frozen=True)
class FrozenUnit:
    unit_id: str
    repository_lineage: str
    arm_budget_seconds: int
    manifest: dict[str, str]
    snapshot_path: Path
    mission_path: Path
    events_path: Path
    expected_outcomes_path: Path


def _parse_digest(value: str) -> tuple[str, str]:
    """Return (algorithm, hex_digest) from manifest entries.

    Supports both ``sha256:<hex>`` and bare hex strings.
    """
    text = str(value).strip()
    if ":" in text:
        algorithm, _, digest = text.partition(":")
        return algorithm.lower(), digest.strip()
    return "sha256", text


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def load_frozen_unit(unit_dir: Path) -> FrozenUnit:
    unit_file = unit_dir / "unit.yaml"
    if not unit_file.is_file():
        raise FileNotFoundError(f"missing unit.yaml in {unit_dir}")

    raw: dict[str, Any] = yaml.safe_load(unit_file.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"unit.yaml must contain a mapping: {unit_file}")

    manifest = raw.get("manifest", {})
    if not isinstance(manifest, dict):
        raise ValueError(f"unit.yaml manifest must be a mapping: {unit_file}")

    snapshot_name = raw.get("snapshot_file", "snapshot.yaml")
    mission_name = raw.get("mission_file", "mission.yaml")
    events_name = raw.get("events_file", "events.yaml")
    expected_outcomes_name = raw.get("expected_outcomes_file", "expected_outcomes.yaml")

    snapshot_path = unit_dir / snapshot_name
    mission_path = unit_dir / mission_name
    events_path = unit_dir / events_name
    expected_outcomes_path = unit_dir / expected_outcomes_name

    for path in (snapshot_path, mission_path, events_path, expected_outcomes_path):
        if not path.is_file():
            raise FileNotFoundError(f"manifest references missing file: {path}")

    return FrozenUnit(
        unit_id=raw["unit_id"],
        repository_lineage=raw["repository_lineage"],
        arm_budget_seconds=int(raw["arm_budget_seconds"]),
        manifest={str(k): str(v) for k, v in manifest.items()},
        snapshot_path=snapshot_path,
        mission_path=mission_path,
        events_path=events_path,
        expected_outcomes_path=expected_outcomes_path,
    )


def verify_manifest(unit: FrozenUnit) -> bool:
    for filename, expected_raw in unit.manifest.items():
        algorithm, expected_digest = _parse_digest(expected_raw)
        if algorithm != "sha256":
            raise ValueError(f"unsupported digest algorithm '{algorithm}' for {filename}")
        path = unit.snapshot_path if filename == unit.snapshot_path.name else None
        path = path or (unit.mission_path if filename == unit.mission_path.name else None)
        path = path or (unit.events_path if filename == unit.events_path.name else None)
        path = path or (
            unit.expected_outcomes_path if filename == unit.expected_outcomes_path.name else None
        )
        if path is None:
            # Allow manifest entries for files not tracked by FrozenUnit (e.g. per-file sha256 sidecars).
            path = unit.snapshot_path.parent / filename
            if not path.is_file():
                raise FileNotFoundError(f"manifest entry not found: {filename}")
        actual_digest = _sha256_file(path)
        if actual_digest != expected_digest:
            raise ValueError(
                f"manifest mismatch for {filename}: expected {expected_digest}, got {actual_digest}"
            )
    return True


def load_events(events_path: Path) -> tuple[SrlEnvironmentEvent, ...]:
    raw: list[Any] = yaml.safe_load(events_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"events.yaml must contain a list: {events_path}")
    return tuple(SrlEnvironmentEvent.model_validate(item) for item in raw)


def _is_dangerous_path(path: str) -> bool:
    """Reject traversal and sensitive filenames."""
    if path.startswith("/") or ".." in path.split("/"):
        return True
    parts = Path(path).parts
    lowered = {p.lower() for p in parts}
    if "expected_outcomes" in lowered or "expected_outcomes.yaml" in lowered:
        return True
    if any(p.startswith("_log") or p.startswith(".") for p in parts):
        return True
    return False


class RsrlEventGateway:
    """In-memory event gateway for R-SRL-1 units.

    Enforces public-state contract: arms receive the same event ledger and
    repository bytes, but cannot read ``expected_outcomes.yaml`` or access
    another arm's runtime logs.
    """

    def __init__(self, units_root: Path):
        self.units_root = Path(units_root)
        self._units: dict[str, FrozenUnit] = {}
        self._events: dict[str, tuple[SrlEnvironmentEvent, ...]] = {}
        self._repo_files: dict[str, dict[str, bytes]] = {}
        self._actions: dict[tuple[str, str], list[dict]] = {}
        self._help_requests: dict[tuple[str, str], list[SrlHelpRequest]] = {}
        self._load_units()

    def _load_units(self) -> None:
        for unit_dir in sorted(self.units_root.iterdir()):
            if not unit_dir.is_dir():
                continue
            unit = load_frozen_unit(unit_dir)
            self._units[unit.unit_id] = unit
            self._events[unit.unit_id] = load_events(unit.events_path)
            self._repo_files[unit.unit_id] = self._load_repo_files(unit_dir)

    def _load_repo_files(self, unit_dir: Path) -> dict[str, bytes]:
        repo_dir = unit_dir / "repo"
        files: dict[str, bytes] = {}
        if repo_dir.is_dir():
            for path in sorted(repo_dir.rglob("*")):
                if path.is_file():
                    rel = path.relative_to(repo_dir).as_posix()
                    files[rel] = path.read_bytes()
        return files

    def list_events(self, arm_id: str, unit_id: str) -> tuple[SrlEnvironmentEvent, ...]:
        if unit_id not in self._units:
            raise ValueError(f"unknown unit_id: {unit_id}")
        return self._events.get(unit_id, ())

    def read_repository(self, arm_id: str, unit_id: str, path: str) -> bytes:
        if unit_id not in self._units:
            raise ValueError(f"unknown unit_id: {unit_id}")
        if _is_dangerous_path(path):
            raise PermissionError(f"access denied to path: {path}")
        files = self._repo_files.get(unit_id, {})
        if path not in files:
            raise FileNotFoundError(f"repository path not found: {path}")
        return files[path]

    def emit_help_request(self, arm_id: str, unit_id: str, request: SrlHelpRequest) -> None:
        if unit_id not in self._units:
            raise ValueError(f"unknown unit_id: {unit_id}")
        self._help_requests.setdefault((arm_id, unit_id), []).append(request)

    def record_action(self, arm_id: str, unit_id: str, action: dict) -> None:
        if unit_id not in self._units:
            raise ValueError(f"unknown unit_id: {unit_id}")
        if not isinstance(action, dict):
            raise TypeError("action must be a dict")
        self._actions.setdefault((arm_id, unit_id), []).append(action)

    def finalize_unit(self, arm_id: str, unit_id: str) -> dict:
        if unit_id not in self._units:
            raise ValueError(f"unknown unit_id: {unit_id}")
        return {
            "unit_id": unit_id,
            "arm_id": arm_id,
            "event_count": len(self._events.get(unit_id, ())),
            "action_count": len(self._actions.get((arm_id, unit_id), [])),
            "help_request_count": len(self._help_requests.get((arm_id, unit_id), [])),
            "repository_files": sorted(self._repo_files.get(unit_id, {}).keys()),
        }
