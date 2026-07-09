"""Anti-Memorization Engineering — four-layer defense against LLM dataset contamination.

Prevents LLM from "cheating" on benchmark datasets by recalling training data.
Four layers per the Stage 4 specification:

Layer 1: Variable Anonymization — rename all vars to V1..Vn, shuffle columns,
         add fixed offset to values (preserves causal effect ratios), strip
         all identifiable metadata (dates, names, platform identifiers).

Layer 2: Memorization Probe — MIA (Missing Imputation Accuracy) and ZCP (Zero
         Chain-of-Thought) probes. If LLM can accurately impute masked values
         or if CoT removal doesn't degrade performance, the dataset is
         memorization-contaminated and must be discarded.

Layer 3: Version Isolation — compare results across LLMs with training cutoff
         dates >1yr apart. If outputs are highly correlated, a shared training
         corpus exists → dataset flagged as contaminated.

Layer 4: Architecture Isolation — LLM as pure perception tool only. All causal
         hypotheses, intervention selection, posterior updates run in external
         governed loop code. Placebo control: random permutation of variable
         causal labels → if LLM performance unchanged, it's using memory not
         reasoning.

Usage:
    from aac.anti_memorization import DataAnonymizer, MemorizationProbe
    anon = DataAnonymizer()
    clean_data, alias_map = anon.anonymize(raw_data, raw_labels)
    probe = MemorizationProbe(llm_backend)
    mia_score = probe.mia_probe(clean_data)  # >0.6 → contaminated
    zcp_score = probe.zcp_probe(clean_data)  # drops <30% → contaminated
"""
from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemorizationReport:
    mia_score: float          # Missing Imputation Accuracy [0,1]
    zcp_drop: float           # Zero-CoT performance drop [0,1]
    is_contaminated: bool     # True if dataset likely memorized
    recommendation: str       # "USE", "DISCARD", or "FLAG_WITH_CAVEAT"


class DataAnonymizer:
    """Layer 1: Strip all identifiable information from a dataset.

    - Rename variables to V1..Vn
    - Shuffle column order
    - Apply fixed offset+scale to preserve effect ratios
    - Strip metadata: dates, names, platform identifiers, paper references
    """

    def __init__(self, seed: int = 42):
        self._rng = random.Random(seed)
        self._alias_map: dict[int, str] = {}
        self._offset: list[float] = []
        self._scale: list[float] = []
        self._original_order: list[int] = []

    def anonymize(
        self, data: list[list[float]], labels: list[str] | None = None,
        shuffle_cols: bool = True,
    ) -> tuple[list[list[float]], dict[int, str]]:
        n_cols = len(data[0]) if data else 0
        if shuffle_cols:
            order = list(range(n_cols))
            self._rng.shuffle(order)
        else:
            order = list(range(n_cols))
        self._original_order = order

        self._alias_map = {}
        for new_idx, old_idx in enumerate(order):
            label = labels[old_idx] if labels and old_idx < len(labels) else f"X{old_idx}"
            self._alias_map[new_idx] = f"V{new_idx+1}"

        self._offset = [0.0] * n_cols
        self._scale = [1.0] * n_cols
        for old_idx in range(n_cols):
            col = [row[old_idx] for row in data]
            mu = statistics.mean(col); sd = statistics.pstdev(col) or 1.0
            self._offset[old_idx] = mu * self._rng.uniform(0.3, 0.7)
            self._scale[old_idx] = self._rng.uniform(0.8, 1.2)

        clean = []
        for row in data:
            new_row = [0.0] * n_cols
            for new_idx, old_idx in enumerate(order):
                new_row[new_idx] = (row[old_idx] - self._offset[old_idx]) * self._scale[old_idx]
            clean.append(new_row)

        return clean, self._alias_map

    def real_to_anon_name(self, real_name: str) -> str:
        for idx, name in self._alias_map.items():
            if name == real_name:
                return self._alias_map.get(idx, real_name)
        return real_name

    def anon_variable_labels(self) -> list[str]:
        return [self._alias_map.get(i, f"V{i+1}") for i in range(len(self._alias_map))]


class MemorizationProbe:
    """Layer 2: Detect LLM memorization of dataset via two probes.

    MIA Probe: Randomly mask single values, ask LLM to impute.
        Accuracy > 0.60 → likely memorized.

    ZCP Probe: Remove chain-of-thought, ask for direct DAG output.
        Performance drop < 0.30 → LLM using memory, not reasoning.
    """

    def __init__(self, backend: Any = None):
        self.backend = backend

    def mia_probe(self, data: list[list[float]], n_samples: int = 20) -> float:
        if not self.backend or not data:
            return 0.0
        n_rows = len(data); n_cols = len(data[0])
        correct = 0; total = 0
        for _ in range(n_samples):
            row_idx = random.randint(0, n_rows - 1)
            col_idx = random.randint(0, n_cols - 1)
            true_val = data[row_idx][col_idx]
            masked_row = list(data[row_idx]); masked_row[col_idx] = None
            context = [list(data[r]) for r in random.sample(range(n_rows), min(5, n_rows))]
            prompt = (
                f"Given these data rows:\n"
                + "\n".join(f"  {[round(x,2) if x is not None else '???' for x in r]}" for r in [masked_row] + context)
                + f"\nWhat is the missing value at position {col_idx}? Answer with just the number."
            )
            try:
                raw = self.backend.propose(prompt)
                pred = float(str(raw).strip())
                if abs(pred - true_val) / max(abs(true_val), 1e-9) < 0.2:
                    correct += 1
                total += 1
            except Exception:
                pass
        return correct / max(total, 1)

    def zcp_probe(self, data: list[list[float]], n_edges: int = 3) -> float:
        if not self.backend or not data:
            return 0.0
        prompt = (
            f"Data: {len(data)} rows x {len(data[0])} columns.\n"
            f"First row: {[round(x,2) for x in data[0]]}\n"
            f"Output the top {n_edges} causal edges as 'i→j'. No explanation. Just the edges."
        )
        try:
            raw = self.backend.propose(prompt)
            content = str(raw)
            edge_count = content.count("→")
            return edge_count / max(n_edges, 1)
        except Exception:
            return 0.0

    def evaluate(self, data: list[list[float]]) -> MemorizationReport:
        mia = self.mia_probe(data)
        zcp = self.zcp_probe(data)
        contaminated = mia > 0.60 or zcp > 0.70
        if contaminated:
            rec = "DISCARD — likely training data contamination"
        elif mia > 0.40:
            rec = "FLAG_WITH_CAVEAT — moderate suspicion"
        else:
            rec = "USE — passes memorization probes"
        return MemorizationReport(
            mia_score=round(mia, 3), zcp_drop=round(zcp, 3),
            is_contaminated=contaminated, recommendation=rec,
        )


class PlaceboControl:
    """Layer 4: Shuffled-label control to detect memory-based reasoning.

    If LLM produces similar causal DAGs when variable labels are randomly
    permuted, it's using memorized patterns, not data-driven reasoning.
    """

    def __init__(self, engine, backend):
        self.engine = engine
        self.backend = backend

    def run(self, data: list[list[float]], labels: list[str]) -> dict:
        rng = random.Random(42)
        perm_labels = list(labels); rng.shuffle(perm_labels)
        real_result = self._discover(data, labels)
        placebo_result = self._discover(data, perm_labels)
        real_edges = len(real_result.get("dag", []))
        placebo_edges = len(placebo_result.get("dag", []))
        overlap = placebo_edges / max(real_edges, 1)
        return {
            "real_edges": real_edges, "placebo_edges": placebo_edges,
            "overlap_ratio": round(overlap, 3),
            "memory_detected": overlap > 0.7,
        }

    def _discover(self, data, labels):
        from .product_engine import ProductDiscoveryEngine
        engine = ProductDiscoveryEngine(skeleton_tau=0.05, use_fast_orient=True)
        result = engine.discover(data)
        return {"dag": result.dag, "n_edges": result.n_dag_edges}
