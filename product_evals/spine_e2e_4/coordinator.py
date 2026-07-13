"""Non-interactive coordinator for the frozen interrupt/probe process pair."""

from __future__ import annotations

import subprocess
import sys

from .identity import IDENTITY


_CLI_MODULE = f"product_evals.{IDENTITY.module_slug}.cli"


INTERRUPT_COMMAND = (
    sys.executable,
    "-m",
    _CLI_MODULE,
    "interrupt-batch",
)
PROBE_COMMAND = (
    sys.executable,
    "-m",
    _CLI_MODULE,
    "probe-active-lease",
)
RUNNER_ANCHOR_COMMAND = (
    sys.executable,
    "-m",
    _CLI_MODULE,
    "record-runner-anchor",
)


def run_interrupt_and_probe() -> None:
    subprocess.run(INTERRUPT_COMMAND, check=True)
    subprocess.run(RUNNER_ANCHOR_COMMAND, check=True)
    subprocess.run(PROBE_COMMAND, check=True)
    subprocess.run(RUNNER_ANCHOR_COMMAND, check=True)
