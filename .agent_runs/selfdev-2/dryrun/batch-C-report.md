# SELFDEV-2 Gold-Validation Dry-Run — Batch C Report

- **Date:** 2026-07-23 (local, UTC+8)
- **Worktree:** `autonomous-agent-core/.worktrees/canonical-convergence-20260715`
- **Docker:** colima up, server 29.1.3 (linux/arm64), 2 CPUs / 4 GB
- **Batch repos:** astropy/astropy, scikit-learn/scikit-learn, pydata/xarray
- **Executor code:** worktree as-is — the batch-B `,rw=true` mount-token bug
  (EXECUTOR-BUG-1) is fixed in repo code (no driver-side stripping needed;
  `ContainerRunner` is used with the stock subprocess runner).
- **Artifacts:**
  - results: `/tmp/selfdev2-dryrun/results/<instance_id>.json` (5 batch-C files)
  - images: `/tmp/selfdev2-dryrun/images/{astropy-astropy,scikit-learn-scikit-learn,pydata-xarray}.Dockerfile` + `.pins.json`
  - mirrors: `/tmp/selfdev2-dryrun/mirrors/{astropy-astropy,scikit-learn-scikit-learn,pydata-xarray}.git` (full `--mirror` clones)
  - driver: `/tmp/selfdev2-dryrun/runner-C.py` (resumable; skips existing results)
  - workspaces: `/tmp/selfdev2-dryrun/ws` → symlink to
    `~/Documents/AI-Agent-Projects/.cache/selfdev2-dryrun-ws` (colima exports
    only /Users; lesson 1)

## Outcome summary

| repo | tried | validated (ok) | target met |
|---|---:|---:|---|
| astropy/astropy | 2 | **2** | yes (2/2) |
| scikit-learn/scikit-learn | 2 | **2** | yes (2/2) |
| pydata/xarray | 1 | **1** | yes (1/1) |

All five runs show the required phase semantics: base+test_patch F2P **red**
(exit 1), base+gold+test_patch F2P **and** P2P **green** (exit 0). Verifier
timeout: 900 s/phase (astropy, sklearn), 600 s (xarray) — actual phase runs
were all < 20 s.

| instance_id | duration | p2p set | evidence_digest (sha256, prefix) |
|---|---:|---|---|
| astropy__astropy-13453 | 14.9 s | 9 real | d94909563ffa9973… |
| astropy__astropy-14182 | 15.4 s | 9 real | cfc0d27ece818384… |
| scikit-learn__scikit-learn-13328 | 6.8 s | 9 real | efa2cb58d2d2ebd0… |
| scikit-learn__scikit-learn-14141 | 8.7 s | 2 real | e9c6361f8ed4f52a… |
| pydata__xarray-4075 | 6.1 s | **0 (vacuous, see below)** | 32946b5ffffc439a… |

**Multi-file test_patch flag:** none of the five validated tasks has a
multi-file test patch (all 1 file). Multi-file test patches were excluded up
front during candidate selection (executor single-file fail-closed rule,
`validate_unified_diff`).

## Candidate selection sweep (lesson 3, applied to f2p **and** p2p)

Every pool id for the three repos was classified before any container run.
`[` = parametrized (non-resolvable under `is_valid_benchmark_node_id`).

- **astropy/astropy (8 pool tasks):**
  - `astropy__astropy-12907` — excluded (f2p parametrized; acquisition report).
  - `astropy__astropy-13033`, `-13579`, `-14309` — f2p clean but stored p2p
    lists contain parametrized ids (lesson-3 sweep); kept as curation
    fallbacks, **not needed** (target reached with clean tasks).
  - `astropy__astropy-7336` — excluded: 2-file test.patch **and** parametrized
    p2p ids.
  - `astropy__astropy-7671` — clean ids but astropy 3.x era (2018) requiring a
    different image; queued last, **not needed**.
  - Tried & validated: **13453, 14182** (fully clean id lists, 0 dropped).
- **scikit-learn/scikit-learn (7 pool tasks):**
  - `scikit-learn__scikit-learn-13135`, `-13779` — excluded (f2p parametrized;
    acquisition report).
  - `scikit-learn__scikit-learn-13142` — excluded: 2-file test.patch **and**
    parametrized p2p ids.
  - `scikit-learn__scikit-learn-25973` — excluded (parametrized p2p ids).
  - Tried & validated: **13328, 14141** (fully clean id lists, 0 dropped).
    Third slot `25747` (sklearn 1.3.dev era, 2023 — would have needed a
    second image) unused.
- **pydata/xarray (3 pool tasks):**
  - `pydata__xarray-4356`, `-4966` — excluded (f2p parametrized; acquisition
    report).
  - `pydata__xarray-4075` — f2p clean (2 ids), **but all 20 stored p2p ids are
    parametrized**; checked the raw parquet: the FULL p2p list (958 ids) is
    100% parametrized — xarray's fixture-parametrized suite produces no
    non-parametrized p2p id at all. Ran with the curated p2p set = empty
    (batch-A p2p-curation semantics; `p2p_dropped` recorded in the result
    JSON, `vacuous_p2p: true`). **p2p green is vacuous for this task** — the
    f2p red→gold-green signal is real, but downstream selection should decide
    whether a vacuous-p2p task stays in the final pool. This is the only
    xarray-runnable task; without curation the repo would validate 0.

## astropy/astropy

- **Image:** `selfdev2-dryrun-astropy:py39` (`python:3.9-slim-bookworm`, 1.04 GB)
- **Repo in image:** cloned to `/repo` @ `cdf311e0714e61…` (env commit of the
  13453/13579 group, astropy 5.2.dev), `python setup.py build_ext --inplace
  -j 2` then `pip install --no-build-isolation .` — **/repo kept**: the baked
  `sitecustomize.py` overlays all compiled `*.so` (17 files) plus the
  setuptools_scm-generated `astropy/_version.py` into the `/work` checkout at
  every interpreter start (lesson 4: `git clean -fdx` between phases wipes
  untracked artifacts). `/work` source shadows site-packages
  (sys.path[0]=cwd), so base_commit code + overlaid artifacts is what pytest
  imports. Candidate 14182 (base 2022-12, 5.3.dev series) validated fine
  against this 5.2.dev build — no second image needed.
- **Python/pins** (`images/astropy-astropy.pins.json`): setuptools==65.6.3,
  setuptools_scm==7.1.0, Cython==0.29.36, extension-helpers==1.1.0,
  numpy==1.23.5, pyerfa==2.0.1.1, PyYAML==6.0.1, packaging==23.2,
  pytest==7.4.4, pytest-doctestplus==1.0.0, pytest-astropy-header==0.2.2,
  pytest-remotedata==0.4.0, hypothesis==6.88.4, beautifulsoup4==4.12.2,
  html5lib==1.1.
  - hypothesis is **required**: the base checkout's root `conftest.py` does
    `import hypothesis` unconditionally.
  - pytest-doctestplus is **required**: setup.cfg addopts has `--doctest-rst`.
  - bs4/html5lib keep io.ascii html tests running (not skipped).
- **Base image pinned to `-bookworm` (recorded finding):** `python:3.9-slim`
  now resolves to Debian trixie (GCC 14), which promotes
  `-Wincompatible-pointer-types`/`-Wint-conversion` to hard errors; the
  2022-era astropy C sources (`wcslib_celprm_wrap.c`, `fast_sigma_clip.c`)
  fail to compile. Bookworm's GCC 12 keeps them as warnings. First trixie
  build failed exactly this way; bookworm rebuild succeeded in ~4 min.
- Candidates tried: 13453 (ok), 14182 (ok). 3rd slot (13579, curated p2p)
  unused.

## scikit-learn/scikit-learn

- **Image:** `selfdev2-dryrun-sklearn:py39` (`python:3.9-slim-bookworm`, 1.4 GB)
- **Repo in image:** cloned to `/repo` @ `7813f7efb5b201…` (env commit of the
  13328 group, **sklearn 0.21.2**, 2019-05 — the SWE-bench sklearn instance
  numbers 13xxx are 2019 PRs, not 2022). Same in-place build + sitecustomize
  `*.so` overlay (50 files) as astropy. Candidate 14141 (base 2019-06,
  0.22.dev series; `_show_versions` is pure-python) validated fine against
  the 0.21.2 build.
- **Python/pins** (`images/scikit-learn-scikit-learn.pins.json`):
  setuptools==59.8.0 (**<60 required**: sklearn 0.21 builds via
  numpy.distutils, which setuptools>=60 breaks), Cython==0.29.36,
  numpy==1.23.5 (last series before `np.int` removal), scipy==1.9.3,
  joblib==0.15.1, pytest==7.4.4. All cp39 manylinux_aarch64 wheels exist.
- **Vendored joblib fix (recorded finding):** sklearn 0.21's vendored
  `sklearn/externals/joblib` ships a cloudpickle that predates the Python 3.8
  `CodeType` change and cannot import on 3.9 (`TypeError: an integer is
  required (got type bytes)`; chain: `sklearn/__init__ → .base →
  sklearn.utils → ._joblib → externals.joblib → loky → cloudpickle`).
  Upstream's own escape hatch `SKLEARN_SITE_JOBLIB=1` — honored by
  `sklearn/utils/_joblib.py` at every candidate base commit — routes to the
  site joblib 0.15.1. Baked as `ENV SKLEARN_SITE_JOBLIB=1` in the image
  (verified: no other module at the base commits imports the vendored joblib
  outside `sklearn/tests/test_site_joblib.py`, which we do not run). No extra
  pytest plugins needed: `--disable-pytest-warnings` and `--doctest-modules`
  in the old setup.cfg addopts are pytest-core features.
- Candidates tried: 13328 (ok), 14141 (ok). 3rd slot (25747) unused.

## pydata/xarray

- **Image:** `selfdev2-dryrun-xarray:py39` (`python:3.9-slim` = trixie, 546 MB;
  pure Python — no C-compile, so no bookworm pin needed)
- **Repo in image:** cloned to `/repo` @ `1c198a191127c6…` (env commit,
  xarray 0.18.1.dev, 2021-05), `pip install /repo`; runtime uses the `/work`
  checkout (base 2020-05, 0.16.1.dev) via plain shadowing — no overlay.
- **Python/pins** (`images/pydata-xarray.pins.json`): numpy==1.21.6,
  pandas==1.2.5, setuptools==65.6.3, setuptools_scm==6.4.2, pytest==7.4.4,
  pytest-env==1.1.3 (provides the `env` ini key in the base checkout's
  setup.cfg). pandas 1.1.x has no cp39 manylinux_aarch64 wheel; 1.2.5 is the
  closest era wheel and imports the 0.16-era base cleanly (verified at
  collect-only).
- Candidates tried: 4075 (ok; vacuous p2p as recorded above).

## Infra / executor findings (must-fix before the real round)

- **GCC 14 vs era C code:** any compiled-repo image for pre-2023 sources must
  pin `python:3.9-slim-bookworm` (or add
  `-Wno-error=incompatible-pointer-types -Wno-error=int-conversion` CFLAGS).
  `python:3.9-slim` moving to trixie silently broke the naive first build.
  Recommend the image-build step record the exact base digest, not just the
  moving tag.
- **Compiled-repo overlay pattern works:** in-place build at env commit +
  sitecustomize `*.so` (+`_version.py`) overlay survived all executor
  restore cycles (`git clean -fdx` between phases) and validated across
  nearby dev-series bases (5.2 image × 5.3 base; 0.21.2 image × 0.22 base).
  This is cheaper than per-task images and should be the documented pattern
  for astropy/sklearn-class repos.
- **Vendored-deps landmine:** era repos may vendor broken-on-new-python deps
  (sklearn 0.21 joblib/cloudpickle). Prefer upstream env-var escape hatches
  (`SKLEARN_SITE_JOBLIB`) over patching the checkout.
- **p2p curation gap (pool-level):** parametrized ids occur in p2p lists, and
  for xarray they make up 100% of the full PASS_TO_PASS list (958/958). The
  admission pipeline needs an explicit rule for p2p curation (drop
  non-resolvable p2p ids, recorded) and a decision on whether tasks whose
  curated p2p set ends up empty are admissible. xarray-4075's validation is
  real on f2p but vacuous on p2p — flagged in its result JSON.
- Batch-B findings stand: workspaces under /Users (colima), node-id
  resolution against base+test_patch (lesson 2) — both applied via
  `runner-C.py`; no new occurrences of prose p2p ids in this batch's repos
  (django-13343 class), only parametrized ones.

## Procedure compliance

- Sequential within the batch: one docker build at a time (2-CPU/4 GB VM),
  one validation at a time; network only at mirror-clone and image-build
  (verifier containers run `--network none`, `--read-only`, tmpfs, 2g/2cpu/
  512pids limits, single bind mount — stock `ContainerRunner`).
- No repo code changes; no git commits anywhere. Workspaces cloned
  `--shared` from local mirrors under the colima-visible cache path.
- `results/*.json` written after every task (pass or fail), incremental and
  resume-safe (reruns skip existing results — verified on xarray resume).
- Per-task result fields: `instance_id, repo, ok, f2p_red_at_base,
  f2p_green_at_gold, p2p_green_at_gold, detail, evidence_digest, image_tag,
  python_version, duration_s` — all present, plus diagnostics (`base_commit`,
  `test_patch_files`, `f2p_resolved`, `p2p_resolved_count`, `p2p_dropped`,
  `excluded`, `vacuous_p2p`, `error`).
- Left untried (recorded for completeness): astropy 7671 (3.x era, separate
  image), astropy 13033/13579/14309 (curatable p2p fallbacks), sklearn 25747
  (1.3.dev era, separate image) — all targets already met.
