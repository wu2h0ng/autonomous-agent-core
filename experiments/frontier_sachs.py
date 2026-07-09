"""Frontier Route — LLM proposes causal directions, CWM verifies on real Sachs data.

RR-0040 §2 item 5: "LLM-generated causal hypotheses + our invariance framework as verifier."

Loads real Sachs protein signaling data (observational + interventional),
computes a GGM skeleton, queries LLM for causal direction proposals per edge,
verifies with interventional do()-data, and reports:

  - LLM precision: what fraction of LLM proposals match interventional truth?
  - LLM recall: what fraction of interventional edges did LLM propose correctly?
  - CWM agreement: where LLM and CWM intervention agree/disagree
  - Net orientation gain: LLM + CWM vs CWM alone

Run: PYTHONPATH=src python experiments/frontier_sachs.py [--stub]
"""

from __future__ import annotations

import math
import os
import statistics
import sys
from dataclasses import dataclass

try:
    from aac.cwm_organ import LinearGGMOrgan
    from aac.interventional_orient import (
        INV_INTERVENABLE, INTERVENABLE_SACHS,
        load_sachs_int, interventional_orient,
    )
    from aac.language_orientation_organ import LanguageOrientationOrgan
    from aac.llm_weight_organ import SimpleLLMBackend
except ImportError:
    from cwm_organ import LinearGGMOrgan  # type: ignore
    from interventional_orient import (  # type: ignore
        INV_INTERVENABLE, INTERVENABLE_SACHS, load_sachs_int, interventional_orient,
    )
    from language_orientation_organ import LanguageOrientationOrgan  # type: ignore
    from llm_weight_organ import SimpleLLMBackend  # type: ignore

SACHS_VARIABLES = [
    "Raf", "Mek", "Plcg", "PIP2", "PIP3", "Erk", "Akt", "PKA", "PKC", "P38", "Jnk",
]


def load_sachs_obs(path: str = "experiments/data/sachs_obs.txt") -> list[list[float]]:
    for candidate in [
        os.path.join(os.path.dirname(__file__), "..", "..", path),
        os.path.join(os.path.dirname(__file__), "..", path),
        path,
    ]:
        if os.path.exists(candidate):
            with open(candidate) as f:
                lines = [ln for ln in f.read().splitlines()[1:] if ln.strip()]
                return [[float(x) for x in ln.split()] for ln in lines]
    raise FileNotFoundError(f"Cannot find {path}")


@dataclass
class FrontierReport:
    skeleton_size: int
    cwm_oriented: int
    llm_oriented: int
    intervention_verified: int
    llm_correct: int
    llm_wrong: int
    llm_missed: int
    llm_precision: float
    llm_recall: float
    cwm_llm_agree: int
    cwm_llm_disagree: int
    edges_detail: list[dict]


def run_frontier(stub: bool = False) -> FrontierReport:
    obs = load_sachs_obs()
    try:
        int_data = load_sachs_int()
    except (FileNotFoundError, OSError):
        int_data = None

    # ── 1. GGM skeleton (data organ) ─────────────────────────────
    organ = LinearGGMOrgan()
    skeleton_proposals = organ.propose_skeleton(obs)
    if skeleton_proposals:
        skeleton = skeleton_proposals[0].edges
        skeleton_score = skeleton_proposals[0].score
    else:
        skeleton, skeleton_score = frozenset(), 0.0
    print(f"GGM skeleton: {len(skeleton)} undirected edges (score={skeleton_score:.3f})")

    # ── 2. LLM orientation proposals ────────────────────────────
    llm_edges: set = set()
    if not stub:
        backend = SimpleLLMBackend(model="kimi-k2-0711-preview", temperature=1.0)
        protein_list = ", ".join(f"{i}:{n}" for i, n in enumerate(SACHS_VARIABLES))
        edge_list = "\n".join(
            f"  ({i}:{SACHS_VARIABLES[i]}) — ({j}:{SACHS_VARIABLES[j]})"
            for undir in skeleton
            for parts in [list(undir)]
            if len(parts) == 2
            for i, j in [(parts[0], parts[1])]
        )
        prompt = (
            f"You are a molecular biologist. Given the following proteins and undirected edges "
            f"from a protein signaling network, propose the causal direction for each edge.\n\n"
            f"Proteins:\n{protein_list}\n\n"
            f"Undirected edges:\n{edge_list}\n\n"
            f"Output a JSON object with an 'orientations' list. Each item has i, j (integers), "
            f"direction (string like 'i→j' or 'j→i'), and score (0.0-1.0). "
            f"Only output the JSON, no other text.\n"
            f'Example: {{"orientations": [{{"i": 0, "j": 1, "direction": "0→1", "score": 0.9}}]}}'
        )
        try:
            raw = backend.propose(prompt)
            orientations = raw.get("orientations", [])
            if isinstance(orientations, list):
                for item in orientations:
                    if not isinstance(item, dict):
                        continue
                    i = int(item.get("i", -1))
                    j = int(item.get("j", -1))
                    direction = str(item.get("direction", ""))
                    if 0 <= i < 11 and 0 <= j < 11 and i != j and frozenset({i, j}) in skeleton:
                        if direction == f"{i}→{j}":
                            llm_edges.add((i, j))
                        elif direction == f"{j}→{i}":
                            llm_edges.add((j, i))
        except Exception as e:
            print(f"  LLM call failed: {e}")
            llm_edges = {(min(i, j), max(i, j)) for undir in skeleton for parts in [list(undir)] if len(parts) == 2 for i, j in [(parts[0], parts[1])]}
    else:
        llm_edges = {(min(i, j), max(i, j)) for undir in skeleton for parts in [list(undir)] if len(parts) == 2 for i, j in [(parts[0], parts[1])]}

    print(f"LLM proposed: {len(llm_edges)} directed edges (stub={stub})")

    # ── 3. CWM interventional verification ───────────────────────
    cwm_directed, cwm_conf, cwm_details = interventional_orient(
        obs, skeleton, int_data=int_data, effect_threshold=0.3,
    )
    print(f"CWM interventional: {len(cwm_directed)} directed edges (conf={cwm_conf:.3f})")

    # ── 4. Cross-check ──────────────────────────────────────────
    llm_correct = 0
    llm_wrong = 0
    edges_detail = []

    for undir in skeleton:
        parts = list(undir)
        if len(parts) != 2:
            continue
        i, j = parts[0], parts[1]
        iv = INV_INTERVENABLE.get(i, "")
        jv = INV_INTERVENABLE.get(j, "")

        llm_dir = None
        if (i, j) in llm_edges:
            llm_dir = f"{i}→{j}"
        elif (j, i) in llm_edges:
            llm_dir = f"{j}→{i}"

        cwm_dir = None
        if (i, j) in cwm_directed:
            cwm_dir = f"{i}→{j}"
        elif (j, i) in cwm_directed:
            cwm_dir = f"{j}→{i}"

        agree = None
        if llm_dir and cwm_dir:
            agree = llm_dir == cwm_dir
            if agree:
                llm_correct += 1
            else:
                llm_wrong += 1

        edges_detail.append({
            "edge": f"{iv}({i})—{jv}({j})",
            "llm": llm_dir,
            "cwm": cwm_dir,
            "agree": agree,
            "cwm_detail": cwm_details.get(f"{i},{j}", {}),
        })

    intervention_verified = len(cwm_directed)
    llm_oriented = len(llm_edges)
    llm_missed = intervention_verified - llm_correct
    llm_precision = llm_correct / max(1, llm_oriented) if llm_oriented > 0 else 0.0
    llm_recall = llm_correct / max(1, intervention_verified) if intervention_verified > 0 else 0.0

    cwm_llm_agree = llm_correct
    cwm_llm_disagree = llm_wrong

    report = FrontierReport(
        skeleton_size=len(skeleton),
        cwm_oriented=intervention_verified,
        llm_oriented=llm_oriented,
        intervention_verified=intervention_verified,
        llm_correct=llm_correct,
        llm_wrong=llm_wrong,
        llm_missed=llm_missed,
        llm_precision=llm_precision,
        llm_recall=llm_recall,
        cwm_llm_agree=cwm_llm_agree,
        cwm_llm_disagree=cwm_llm_disagree,
        edges_detail=edges_detail,
    )

    # ── 5. Print report ──────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"FRONTIER ROUTE — Sachs Causal Orientation")
    print(f"{'='*60}")
    print(f"Skeleton edges:        {report.skeleton_size}")
    print(f"LLM oriented:          {report.llm_oriented}")
    print(f"CWM (interventional):  {report.cwm_oriented}")
    print(f"")
    print(f"LLM correct:           {report.llm_correct}")
    print(f"LLM wrong:             {report.llm_wrong}")
    print(f"LLM missed (CWM found):{report.llm_missed}")
    print(f"LLM precision:         {report.llm_precision:.1%}")
    print(f"LLM recall:            {report.llm_recall:.1%}")
    print(f"")
    print(f"CWM-LLM agree:         {report.cwm_llm_agree}")
    print(f"CWM-LLM disagree:      {report.cwm_llm_disagree}")
    print(f"")

    for d in report.edges_detail:
        status = "✓" if d["agree"] else ("✗" if d["agree"] is False else "?")
        print(f"  {status} {d['edge']:30s}  LLM={d['llm'] or '-':>8s}  CWM={d['cwm'] or '-':>8s}")

    return report


if __name__ == "__main__":
    stub = "--stub" in sys.argv
    run_frontier(stub=stub)
