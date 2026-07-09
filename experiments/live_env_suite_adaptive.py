"""Adaptive multi-seed live-environment suite.

This sweep enables two bounded guards:
- Change-point detection + posterior reset for regime-shift environments.
- Conservative edge-marginal filtering for latent-confounder environments.

Run: PYTHONPATH=src python experiments/live_env_suite_adaptive.py
"""
from __future__ import annotations

import json

from aac.live_env_harness import run_suite_adaptive


def main() -> None:
    result = run_suite_adaptive(
        seeds=list(range(10)),
        budget=12,
        n_particles=40,
        drift_threshold=1.0,
        latent_marginal_threshold=0.35,
    )
    print(json.dumps(result, indent=2))
    with open("experiments/live_env_suite_adaptive.result.json", "w") as f:
        json.dump(result, f, indent=2)
    print("\nWrote experiments/live_env_suite_adaptive.result.json")


if __name__ == "__main__":
    main()
