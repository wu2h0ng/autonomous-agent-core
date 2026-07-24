# SWE-bench Verified — Candidate Pool Acquisition Report

- **Run date (fetch date):** 2026-07-23 (UTC)
- **Dataset:** `princeton-nlp/SWE-bench_Verified` (HuggingFace, revision `c104f840cc67f8b6eec6f759ebc8b2693d585d4a`, last modified 2025-02-18)
- **Source URL:** https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified/resolve/main/data/test-00000-of-00001.parquet
- **Raw artifact:** `raw/test-00000-of-00001.parquet` (2,096,679 bytes, matches HF API `download_size`)
- **Dataset size:** 500 instances (test split)
- **Final pool size:** **119** (target ≥ 40 — met)
- **Output:** `candidate-pool.json` + per-task dirs `tasks/<instance_id>/{gold.patch,test.patch,issue.txt}`

## Repos present in dataset (all 12)

| repo | instances | allowlisted |
|---|---:|---|
| django/django | 231 | yes |
| sympy/sympy | 75 | yes |
| sphinx-doc/sphinx | 44 | no |
| matplotlib/matplotlib | 34 | no |
| scikit-learn/scikit-learn | 32 | no |
| astropy/astropy | 22 | no |
| pydata/xarray | 22 | no |
| pytest-dev/pytest | 19 | yes |
| pylint-dev/pylint | 10 | no |
| psf/requests | 8 | yes |
| mwaskom/seaborn | 2 | no |
| pallets/flask | 1 | yes |

Note: `encode/requests-html` (in the allowlist) does **not** occur in SWE-bench Verified at all.

## Filter drop counts (sequential)

| filter | rule | dropped | remaining |
|---|---|---:|---:|
| start | — | — | 500 |
| a | gold `patch` modifies exactly one file (`diff --git` headers) | 71 | 429 |
| b | repo in pip-installable allowlist | 137 | 292 |
| c | gold file is `.py` | 0 | 292 |
| e | `FAIL_TO_PASS` non-empty | 0 | 292 |
| d | gold file at `base_commit` ≤ 19000 bytes (raw.githubusercontent.com) | 173 | **119** |
| d | fetch failure | 0 | 119 |

Filter e was applied before d purely to minimize outbound HTTP requests; e dropped 0
instances, so all per-rule drop counts are identical to the spec order a→b→c→d→e.

Per-rule b exclusion detail (instances dropped because repo not allowlisted):
sphinx-doc/sphinx 44, matplotlib/matplotlib 34, scikit-learn/scikit-learn 32,
astropy/astropy 22, pydata/xarray 22, pylint-dev/pylint 10, mwaskom/seaborn 2 — total 166
dataset-wide, of which 137 reached filter b (29 had already been dropped by filter a).

## Final pool per repo

| repo | pool tasks |
|---|---:|
| django/django | 86 |
| sympy/sympy | 22 |
| pytest-dev/pytest | 9 |
| psf/requests | 2 |
| **total** | **119** |

`pallets/flask` ends with 0: its single instance (`pallets__flask-5014`) passed a/b/c/e
but its gold file is 24,356 bytes at base_commit → dropped by filter d.

## Anomalies

- **Parametrized FAIL_TO_PASS node ids (contain `[`) — NOT usable for seeded selection:**
  6 in the final pool (9 before filter d; `psf__requests-5414`, `psf__requests-6028`,
  `pytest-dev__pytest-7521` were removed by d).
  In-pool instances to exclude downstream:
  - `pytest-dev__pytest-10081`
  - `pytest-dev__pytest-5787`
  - `pytest-dev__pytest-7205`
  - `pytest-dev__pytest-7236`
  - `pytest-dev__pytest-7324`
  - `pytest-dev__pytest-7432`

  → **113 of 119 pool tasks are fully usable** (≥ 40 target still met after exclusion).
- **Fetch failures:** none — 292/292 gold files fetched OK from raw.githubusercontent.com
  (≤4 concurrent, 10 s timeout, 2 retries available; 0 retries actually needed).
- **`PASS_TO_PASS` truncation:** 75 of 119 entries have >20 p2p node ids; for those the
  first 20 are stored with `p2p_truncated=true` (per spec).
- **Node-id format:** django/flask/requests use unittest-style ids
  (`test_x (module.Class)`), sympy/pytest use pytest `::` ids — stored as-is.

## Provenance / reproducibility

Scripts kept alongside the data (not part of the pool contract):
`filter_local.py` (filters a,b,c,e → `intermediate.json`),
`fetch_sizes.py` (filter d → `fetch_results.json`),
`assemble.py` (pool JSON + task files → `assembly_summary.json`).
Run with `uv run --with pandas --with pyarrow` (repo venv untouched; no packages installed
into `.venv`). Issue-text hashes verified: sha256 of every written `issue.txt` matches its
`issue_text_hash`.

---

## Widening pass (2026-07-23)

**Supersedes the pool size above: merged pool is now 162 entries across 10 repos.**

- **Reason:** the original pool spanned only 4 repos, insufficient for the founder's
  stratified selection (cap 2–3 tasks per repo over N=12 + 6 reserve). The 7 repos
  previously excluded by the pip-installable allowlist all qualify under the design intent
  "pip-installable in a plain venv on linux/arm64" (manylinux aarch64 wheels or pure Python).
- **Method:** identical filters on the same raw parquet — a (gold patch touches exactly one
  file), c (gold file `.py`), e (FAIL_TO_PASS non-empty), d (gold file ≤ 19000 bytes at
  `base_commit`, raw.githubusercontent.com, ≤4 concurrent, 10 s timeout, 2 retries).
  Filter e again applied before d to minimize HTTP requests; it dropped 0, so counts are
  order-independent. New entries carry one additional field `f2p_id_style`
  (`pytest` if all f2p ids contain `::`, `unittest` if any matches `test_x (module.Class)`,
  else `mixed`); the original 119 entries were **not** retrofitted.
- **Script:** `widen_pool.py`; stats in `widening_summary.json`.

### Widening drop counts and per-repo added

| repo | start | dropped a (multi/zero-file) | dropped d (oversize) | **added** |
|---|---:|---:|---:|---:|
| sphinx-doc/sphinx | 44 | 8 | 16 | **20** |
| astropy/astropy | 22 | 3 | 11 | **8** |
| scikit-learn/scikit-learn | 32 | 2 | 23 | **7** |
| pydata/xarray | 22 | 5 | 14 | **3** |
| pylint-dev/pylint | 10 | 6 | 1 | **3** |
| matplotlib/matplotlib | 34 | 4 | 28 | **2** |
| mwaskom/seaborn | 2 | 1 | 1 | **0** |
| **total** | 166 | 29 | 94 | **43** |

Filter c (non-`.py` gold file) and filter e (empty FAIL_TO_PASS) dropped 0 instances across
all 7 repos. Fetch failures: 0 (137/137 fetched OK).

### Repos ending at zero after filters

- **mwaskom/seaborn** — 0 added (1 instance had a multi-file gold patch, the other's gold
  file exceeded 19000 bytes).

### Anomalies in the widening pass

- **Parametrized FAIL_TO_PASS ids (contain `[`) among new entries — 9, NOT usable:**
  `astropy__astropy-12907`, `matplotlib__matplotlib-24026`, `pydata__xarray-4356`,
  `pydata__xarray-4966`, `scikit-learn__scikit-learn-13135`,
  `scikit-learn__scikit-learn-13779`, `sphinx-doc__sphinx-8265`, `sphinx-doc__sphinx-8621`,
  `sphinx-doc__sphinx-9367`.
  Combined with the 6 from the original pass, **15 of 162** merged entries are unusable →
  **147 fully usable tasks**.
- **f2p_id_style distribution:** all 43 new entries are `pytest`-style. In the merged pool
  (style derived on the fly for the original 119, not persisted): django/django has
  78 `unittest` + 8 `mixed`; sympy/sympy is 22 `mixed` (its f2p ids are bare function names
  like `test_Identity`, matching neither `::` nor the parenthetical unittest form);
  django `mixed` cases contain prose-like ids (e.g. `Migration directories without an
  __init__.py file are loaded.`). All other repos are uniformly `pytest`-style.

### Merged pool per repo (totals)

| repo | tasks | id style |
|---|---:|---|
| django/django | 86 | 78 unittest, 8 mixed |
| sympy/sympy | 22 | 22 mixed |
| sphinx-doc/sphinx | 20 | 20 pytest |
| pytest-dev/pytest | 9 | 9 pytest |
| astropy/astropy | 8 | 8 pytest |
| scikit-learn/scikit-learn | 7 | 7 pytest |
| pydata/xarray | 3 | 3 pytest |
| pylint-dev/pylint | 3 | 3 pytest |
| matplotlib/matplotlib | 2 | 2 pytest |
| psf/requests | 2 | 2 pytest |
| **total** | **162** | |

Post-merge invariant sweep re-run over all 162 entries: bytes ≤ 19000, single `diff --git`
header matching `gold_file_path`, f2p non-empty, no duplicate instance_ids, all
`tasks/<instance_id>/` files present and non-empty — **no errors**.
