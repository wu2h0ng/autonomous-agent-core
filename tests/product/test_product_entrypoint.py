"""Installed entry points after the terminal-line convergence.

The supported terminal client is the npm `agentos` / `agent-os` / `agent-os-ts`
bin (apps/cli-ts); the Python package only ships the governance daemon
(`agent-os-runtime`). The former Python `agent` / `agent-os` console scripts and
the frozen textual TUI (path B) were removed.
"""

from __future__ import annotations

import subprocess
import sys
from importlib.metadata import distribution
from pathlib import Path


def test_installed_console_scripts_are_daemon_and_work_cli() -> None:
    installed = distribution("autonomous-agent-core")
    console_scripts = {
        entry.name: entry
        for entry in installed.entry_points
        if entry.group == "console_scripts"
    }

    assert console_scripts.keys() == {"agent-os-runtime", "agent-os-work"}
    assert (
        console_scripts["agent-os-runtime"].value
        == "apps.runtime_daemon.__main__:main"
    )
    assert console_scripts["agent-os-work"].value == "apps.cli.__main__:main"
    assert installed.metadata["Requires-Python"] == ">=3.11"


def test_installed_product_package_contains_api_surface_resources() -> None:
    installed_files = {
        str(path) for path in distribution("autonomous-agent-core").files or ()
    }

    assert "apps/api_server/index.html" in installed_files
    assert "apps/api_server/preview-zh.html" in installed_files


def test_runtime_daemon_entrypoint_runs() -> None:
    executable = Path(sys.executable).with_name("agent-os-runtime")
    completed = subprocess.run(
        [str(executable), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert "agent-os-runtime" in completed.stdout


def test_work_cli_entrypoint_runs() -> None:
    executable = Path(sys.executable).with_name("agent-os-work")
    completed = subprocess.run(
        [str(executable), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert "agent-run" in completed.stdout
    assert "agent-admit-selfdev" in completed.stdout


def test_work_cli_help_lists_the_work_surface_without_suppress_markers() -> None:
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, "-m", "apps.cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "==SUPPRESS==" not in completed.stdout
    assert "agent-run" in completed.stdout
    assert "agent-admit-selfdev" in completed.stdout
