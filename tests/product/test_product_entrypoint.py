from __future__ import annotations

import subprocess
import sys
from importlib.metadata import distribution
from pathlib import Path


def test_installed_agent_surface_entrypoints_resolve_to_product_cli() -> None:
    installed = distribution("autonomous-agent-core")
    console_scripts = {
        entry.name: entry
        for entry in installed.entry_points
        if entry.group == "console_scripts"
    }

    assert console_scripts["agent"].value == "apps.cli.__main__:main"
    assert console_scripts["agent-os"].value == "apps.cli.__main__:main"
    assert console_scripts["agent"].load() is console_scripts["agent-os"].load()
    assert installed.metadata["Requires-Python"] == ">=3.11"


def test_installed_product_package_contains_api_surface_resources() -> None:
    installed_files = {
        str(path) for path in distribution("autonomous-agent-core").files or ()
    }

    assert "apps/api_server/index.html" in installed_files
    assert "apps/api_server/preview-zh.html" in installed_files


def test_installed_agent_command_is_the_mandate_product_surface() -> None:
    executable = Path(sys.executable).with_name("agent")

    completed = subprocess.run(
        [str(executable), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Mandate-top Agent Surface" in completed.stdout
    assert "Start the Cursor Agent" not in completed.stdout


def test_installed_agent_run_resolves_to_responsibility_work_command() -> None:
    for executable_name in ("agent", "agent-os"):
        executable = Path(sys.executable).with_name(executable_name)
        completed = subprocess.run(
            [str(executable), "run", "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert completed.returncode == 0, completed.stderr
        assert "--max-cycles" in completed.stdout
        assert "--prompt" not in completed.stdout
