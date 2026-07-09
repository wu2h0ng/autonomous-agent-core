"""Unified multi-seed live-environment suite.

Run: PYTHONPATH=src python experiments/live_env_suite.py
"""
from __future__ import annotations

import json

from aac.live_env_harness import run_suite


def main() -> None:
    result = run_suite(seeds=list(range(10)), budget=12, n_particles=40)
    print(json.dumps(result, indent=2))
    with open("experiments/live_env_suite.result.json", "w") as f:
        json.dump(result, f, indent=2)
    print("\nWrote experiments/live_env_suite.result.json")


if __name__ == "__main__":
    main()
