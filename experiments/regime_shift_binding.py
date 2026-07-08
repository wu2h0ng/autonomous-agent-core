"""Regime-shift live-intervention benchmark.

Run: PYTHONPATH=src python experiments/regime_shift_binding.py
"""
from __future__ import annotations

import json

from aac.interactive_discovery_loop import run_regime_shift_benchmark


def main() -> None:
    result = run_regime_shift_benchmark(seed=42)
    print(json.dumps(result, indent=2))
    with open("experiments/regime_shift_binding.result.json", "w") as f:
        json.dump(result, f, indent=2)
    print("\nWrote experiments/regime_shift_binding.result.json")


if __name__ == "__main__":
    main()
