"""OpenAI-compatible tool JSON schemas for the Mandate coding terminal."""

from __future__ import annotations

from typing import Any

TERMINAL_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "workspace.read": {
        "type": "object",
        "additionalProperties": False,
        "required": ["path"],
        "properties": {
            "path": {
                "type": "string",
                "description": "Repo-relative file path to read",
            }
        },
    },
    "workspace.search": {
        "type": "object",
        "additionalProperties": False,
        "required": ["pattern"],
        "properties": {
            "pattern": {"type": "string", "description": "Python regex"},
            "glob": {"type": "string", "description": "Optional filename/path glob"},
            "path": {"type": "string", "description": "Optional subdirectory"},
            "max_matches": {"type": "integer", "minimum": 1, "maximum": 200},
        },
    },
    "workspace.glob": {
        "type": "object",
        "additionalProperties": False,
        "required": ["pattern"],
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern relative to repo root, e.g. **/*.py",
            },
            "max_results": {"type": "integer", "minimum": 1, "maximum": 1000},
        },
    },
    "workspace.apply_patch": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "path": {
                "type": "string",
                "description": "Target path for full-file replace mode",
            },
            "content": {
                "type": "string",
                "description": "Full new file contents for replace mode",
            },
            "diff": {
                "type": "string",
                "description": "Unified diff to apply (alternative to path+content)",
            },
            "expected_sha256": {
                "type": "string",
                "description": "Optional preimage sha256 for full-file mode",
            },
        },
        "description": "Provide either {path, content} or {diff}",
    },
    "workspace.run_tests": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "command": {
                "type": "string",
                "enum": ["pytest", "python -m pytest", "python3 -m pytest"],
            },
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120},
        },
    },
    "workspace.shell": {
        "type": "object",
        "additionalProperties": False,
        "required": ["argv"],
        "properties": {
            "argv": {
                "description": "Allowlisted argv list or shell-like string without metacharacters",
                "oneOf": [
                    {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    {"type": "string"},
                ],
            },
            "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 120},
        },
    },
}


def tool_parameters_for(capability_id: str) -> dict[str, Any]:
    return dict(
        TERMINAL_TOOL_SCHEMAS.get(
            capability_id,
            {"type": "object", "additionalProperties": True},
        )
    )


def tool_description_for(capability_id: str) -> str:
    descriptions = {
        "workspace.read": "Read a UTF-8 text file from the repository sandbox.",
        "workspace.search": "Regex search file contents under the repository.",
        "workspace.glob": "List repository paths matching a glob pattern.",
        "workspace.apply_patch": (
            "Modify files: full-file replace via path+content, or apply a unified diff."
        ),
        "workspace.run_tests": "Run an allowlisted pytest command in the repo.",
        "workspace.shell": (
            "Run an allowlisted program argv inside the repo (no shell metacharacters)."
        ),
    }
    return descriptions.get(capability_id, f"Invoke typed capability {capability_id}")
