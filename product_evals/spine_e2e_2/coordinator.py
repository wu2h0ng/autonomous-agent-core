"""Non-interactive coordinator for the frozen interrupt/probe process pair."""

from __future__ import annotations

import subprocess
import sys


INTERRUPT_COMMAND = (
    sys.executable,
    "-m",
    "product_evals.spine_e2e_2.cli",
    "interrupt-batch",
)
PROBE_COMMAND = (
    sys.executable,
    "-m",
    "product_evals.spine_e2e_2.cli",
    "probe-active-lease",
)
RUNNER_ANCHOR_COMMAND = (
    sys.executable,
    "-m",
    "product_evals.spine_e2e_2.cli",
    "record-runner-anchor",
)


def run_interrupt_and_probe() -> None:
    subprocess.run(INTERRUPT_COMMAND, check=True)
    subprocess.run(RUNNER_ANCHOR_COMMAND, check=True)
    subprocess.run(PROBE_COMMAND, check=True)
    subprocess.run(RUNNER_ANCHOR_COMMAND, check=True)
