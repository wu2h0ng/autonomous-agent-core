"""Sachs LLM Organ v2 — batched edge queries for speed.
Run: PYTHONPATH=src python experiments/sachs_llm_orient_v2.py
"""
from __future__ import annotations

import json, os, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

API_KEY = os.environ.get("KIMI_API_KEY", "")
API_URL = "https://api.kimi.com/coding/v1/chat/completions"
PROTEINS = ["Raf","Mek","Plcg","PIP2","PIP3","Erk","Akt","PKA","PKC","P38","Jnk"]
GROUND_TRUTH = [
    ("PKC","Raf"),("PKC","Mek"),("PKC","Jnk"),("PKC","P38"),("PKC","PKA"),
    ("PKA","Raf"),("PKA","Mek"),("PKA","Erk"),("PKA","Akt"),("PKA","Jnk"),("PKA","P38"),
    ("Raf","Mek"),("Mek","Erk"),("Erk","Akt"),
    ("Plcg","PIP2"),("Plcg","PIP3"),("PIP3","PIP2"),
]


def query_kimi_batch(edges_batch):
    ed_str = "\n".join(f"  ({i}:{PROTEINS[i]}) -- ({j}:{PROTEINS[j]})" for i,j in edges_batch)
    prompt = f"""Proteins: {', '.join(f'{i}:{p}' for i,p in enumerate(PROTEINS))}
Undirected edges:
{ed_str}
Return ONLY JSON: {{"orientations": [{{"i": X, "j": Y, "direction": "X→Y", "score": 0.0-1.0}}, ...]}}"""
    payload = json.dumps({
        "model": "kimi-k2.6",
        "messages": [
            {"role": "system", "content": "Molecular biology expert. Return ONLY valid JSON with orientations array. Be concise."},
            {"role": "user", "content": prompt},
        ],
        "thinking": {"type": "disabled"},
    }).encode("utf-8")
    req = urllib.request.Request(API_URL, data=payload, headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}",
    })
    with urllib.request.urlopen(req, timeout=300) as resp:
        rj = json.loads(resp.read().decode())
        content = rj["choices"][0]["message"]["content"].strip()
        if content.startswith("```"): content = content.split("```")[1]
        if content.startswith("json"): content = content[4:]
        return json.loads(content).get("orientations", [])


def load_sachs_obs():
    path = os.path.join(os.path.dirname(__file__), "data", "sachs_obs.txt")
    with open(path) as f:
        rows = [ln.split() for ln in f.read().splitlines()[1:] if ln.strip()]
    return [[float(v) for v in r] for r in rows]


def main():
    obs = load_sachs_obs()
    n = len(PROTEINS)
    true_edges = frozenset({(PROTEINS.index(a), PROTEINS.index(b)) for a,b in GROUND_TRUTH})
    print(f"Sachs: n={n}, |E|={len(true_edges)}")

    from aac.product_engine import ProductDiscoveryEngine
    engine = ProductDiscoveryEngine(skeleton_tau=0.05, use_fast_orient=False, n_particles=30)
    result = engine.discover(obs, true_edges)
    sk = list(result.skeleton)
    print(f"GGM skeleton: {len(sk)} edges, recall={result.recall:.3f}")

    batch_size = 3
    all_orientations = []
    for i in range(0, len(sk), batch_size):
        batch = []
        for undir in sk[i:i+batch_size]:
            parts = list(undir)
            if len(parts) == 2: batch.append((parts[0], parts[1]))
        if not batch: continue
        print(f"  Querying batch {i//batch_size+1}: {len(batch)} edges...", end=" ", flush=True)
        t0 = time.time()
        orients = query_kimi_batch(batch)
        all_orientations.extend(orients)
        print(f"got {len(orients)} in {time.time()-t0:.0f}s")

    llm_correct = llm_total = 0
    for o in all_orientations:
        i, j, d, s = o["i"], o["j"], o["direction"], o["score"]
        if d == f"{i}→{j}":
            if (i,j) in true_edges: llm_correct += 1
            llm_total += 1
        elif d == f"{j}→{i}":
            if (j,i) in true_edges: llm_correct += 1
            llm_total += 1
    llm_orient = llm_correct / max(llm_total, 1)
    print(f"\nLLM orientation: {llm_correct}/{llm_total} = {llm_orient:.3f}")
    print(f"GGM baseline: orient={result.orientation_accuracy:.3f}")
    print(f"LLM lift: {llm_orient - result.orientation_accuracy:+.3f}")


if __name__ == "__main__":
    main()
