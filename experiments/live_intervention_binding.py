"""Live intervention binding benchmark.

Connects the CWM discovery loop to a controllable simulation environment and
compares BOED-driven interventions against a random baseline.

Usage:
    PYTHONPATH=src python experiments/live_intervention_binding.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from aac.interactive_discovery_loop import run_live_intervention_benchmark


def main() -> None:
    start = time.time()
    result = run_live_intervention_benchmark(
        n_nodes=4,
        edges={(0, 1), (0, 2), (1, 3), (2, 3)},
        n_obs=100,
        budget=20,
        seed=42,
    )
    result["elapsed_s"] = round(time.time() - start, 3)

    out_path = Path(__file__).with_suffix(".result.json")
    out_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
