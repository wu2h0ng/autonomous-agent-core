# Gold-Validation Dry-Run — Batch A Report

- **Date:** 2026-07-23 (UTC)
- **Scope:** batch A repos — sympy/sympy, psf/requests, pytest-dev/pytest, pylint-dev/pylint, matplotlib/matplotlib
- **Harness:** `agent_os_core.benchmark_executor.run_gold_validation` + `ContainerVerifierExecutor` (ADR-0056 decision 5 semantics: base+test_patch → f2p RED; base+gold+test_patch → f2p AND p2p GREEN), node ids resolved with `agent_os_core.benchmark_node_ids.resolve_benchmark_node_ids`, timeout 600 s per pytest invocation.
- **Daemon:** colima (vz/virtiofs, aarch64), docker server 29.1.3.
- **Artifacts:** per-task JSONs in `/tmp/selfdev2-dryrun/results/<instance_id>.json` (instance_id, repo, ok, phase booleans, detail, evidence_digest, image_tag, python_version, duration_s, plus resolved-id/dropped-p2p metadata); driver `/tmp/selfdev2-dryrun/driver.py`; Dockerfiles `/tmp/selfdev2-dryrun/images/`; logs `/tmp/selfdev2-dryrun/logs/`; mirrors `/tmp/selfdev2-dryrun/mirrors/`.

## Totals

| repo | validated / target | tried | excluded | verdict |
|---|---:|---:|---:|---|
| sympy/sympy | **2 / 2** | 2 (+2 excluded) | 2 | target MET |
| psf/requests | **1 / 2** | 2 | 0 | NOT met — only 2 usable candidates exist, exhausted |
| pytest-dev/pytest | **2 / 2** | 3 | 0 | target MET |
| pylint-dev/pylint | **2 / 2** | 2 | 0 | target MET (3rd candidate not needed) |
| matplotlib/matplotlib | **1 / 1** | 1 | 0 | target MET (2nd candidate parametrized-f2p, pre-excluded) |
| **total** | **8 / 8** | 10 runs | 2 excluded | |

**Multi-file flag (validated tasks):** none — every validated task has a single-file gold patch AND a single-file test patch (`gold_patch_files=1`, `test_patch_files=1` in the JSONs), so none collide with the executor's single-file fail-closed rule.

## Infra workarounds (recorded, repo code untouched)

1. **docker 29 `rw=true` incompatibility:** the harness's `ContainerRunner` emits `--mount type=bind,src=...,dst=/work,rw=true`; docker 29.1.3 rejects `rw` ("unknown option"). The driver's injected `DockerRunner` strips the `,rw=true` suffix before `subprocess.run` (rw is the docker default) — semantics preserved, no repo-code change. Without this every run exits 125 (`BENCHMARK_CONTAINER_RUN_FAILED`).
2. **colima VM exports only `/Users`:** host `/tmp` is NOT bind-mountable (the VM has its own `/private/tmp`; early probes silently created VM-local dirs). Workspaces live in `~/Documents/AI-Agent-Projects/.cache/selfdev2-dryrun-ws/`; `/tmp/selfdev2-dryrun/ws` is a symlink there. The harness's `Path.resolve()` boundary check resolves both consistently, and docker receives the real `/Users/...` path.
3. **Loopback works under `--network none`** (required for the requests httpbin server).
4. **Manual `docker run` bring-up/verify runs** used `--network none` and no other network flags, matching the harness's lockdown; network was used only at `docker build` / `git clone` time.
5. **Driver resolution updated (batch-B lesson 2):** node-id resolution now runs against base+test_patch (apply test_patch → resolve → restore), so f2p tests added by the test patch resolve. Two earlier sympy exclusions predate this change and were not re-run (skip-existing rule); see sympy section.

## Images (all `FROM python:3.9-slim`, Python 3.9.25, linux/arm64)

| image tag | repo checkout in image | install / dep notes |
|---|---|---|
| `selfdev2-dryrun-sympy:v1` | `/repo` @ `50b81f9f6b` (env commit of first candidate, 2017-06) | `pip install -e .` (mpmath) + `mpmath==1.3.0` + `pytest==6.2.5`. pytest 6.2.5 chosen because the era root `conftest.py` calls `Config.getvalue`, removed in pytest 7. sympy/mpmath are pure Python; the workspace checkout shadows the install via cwd. |
| `selfdev2-dryrun-requests:v1` | `/repo` @ `4bceb312f1` (2013-12) | 2013 requests vendors all deps — no repo install needed (import resolves from the workspace). `pytest==7.4.4` + local httpbin stack `flask==2.2.5 werkzeug==2.2.3 markupsafe==2.1.3 itsdangerous==2.1.2 jinja2==3.1.3 click==8.1.7 httpbin==0.10.2`. `ENV HTTPBIN_URL=http://127.0.0.1:8080/` (2013 tests read it, default `http://httpbin.org` — unreachable offline); ENTRYPOINT starts `/opt/httpbin_server.py` (Flask httpbin on loopback) and waits for the port before `exec "$@"`. All 26 f2p/p2p test bodies were pre-audited: every network call goes through `httpbin(...)`; the single literal URL (`http://kennethreitz.org/`) is only prepared, never fetched. |
| `selfdev2-dryrun-pytest:v1` | `/repo` @ `c2f762460f` (2019-08, pytest 5.1 era) | `pip install -e .` + pins `pluggy==0.13.1 py==1.11.0 attrs==21.4.0 more-itertools==8.14.0 packaging==21.3 wcwidth==0.2.5 atomicwrites==1.4.0 iniconfig==1.1.1 toml==0.10.2 importlib-metadata==1.7.0 six==1.12.0`. `importlib-metadata` is needed because 5.1-era `config/__init__.py` imports it unconditionally (its `python_version<"3.8"` marker excludes it on py3.9); `six` is imported by the 5.2-era `_pytest/assertion/__init__.py`. `ENV PYTHONPATH=/work/src` (src layout — the workspace checkout runs itself); ENTRYPOINT copies the setuptools-scm-generated `/repo/src/_pytest/_version.py` into the workspace each run (`git clean -fdx` wipes it between phases). Candidate test files need no extra test deps (stdlib + `unittest.mock` only). |
| `selfdev2-dryrun-pylint:v1` | `/repo` @ `e90702074e` (2022-12, shared env commit) | `pip install -e .[testutils]` + `astroid==2.12.13 py~=1.11.0 pytest~=7.2 typing-extensions~=4.4`. astroid 2.12.13 is the middle ground across the candidate bases (2.14-era caps at `<=2.12.0-dev0`, 2.15/2.16-era floors at `>=2.12.1`); empirically compatible with both validated bases. `pytest-timeout`/`pytest-benchmark`/`pytest-xdist` not needed — markers are registered in `setup.cfg [tool:pytest]` (addopts is only `--strict-markers`). `spelling` extra skipped (pyenchant needs system libenchant; not imported by these tests). |
| `selfdev2-dryrun-matplotlib:v1` | `/repo` @ `de98877e3d` (2022-09, two days before 3.6.0) | **Wheel-based, not source-built:** base is `v3.5.0-1931-ga2a1b0a11b` on master toward 3.6.0. `numpy==1.26.4 matplotlib==3.6.0` (manylinux aarch64 wheel) `pytest==7.4.4 pyparsing==2.4.7 setuptools==65.7.0`. Era pins needed because mpl's own `filterwarnings=error` turns pyparsing-3.x and pkg_resources deprecation warnings into collection errors. Removed the wheel's `matplotlib-3.6.0-py3.9-nspkg.pth` (setuptools legacy-namespace .pth that pre-seeds `sys.modules['mpl_toolkits']` → site-packages, cross-linking 3.6.0 `mpl_toolkits` against the workspace's 3.6-dev `matplotlib`). `ENV PYTHONPATH=/work/lib`; ENTRYPOINT copies the wheel's `*.so` + `_version.py` into the mounted workspace each run (harness `git clean -fdx` wipes them between phases). Earlier entrypoint bug fixed: `cd` leaked into the verifier process (now a subshell). |

## Per-repo outcomes

### sympy/sympy — validated 2/2 (target met)

| instance | result | duration | notes |
|---|---|---:|---|
| sympy__sympy-12419 | **ok=True** | 14.7 s | f2p `test_Identity` → `sympy/matrices/expressions/tests/test_matexpr.py::test_Identity`; red at base exit=1 (genuine failure), green at gold; p2p 13/20 effective (7 bare-name ids matched ≠1 file at base and were dropped from the curated set). |
| sympy__sympy-13551 | excluded | 2.8 s | f2p bare name `test_issue_13546` matched 0 files at base (the test is added by test.patch). Resolved pre-lesson-2; re-check confirms it **does** resolve against base+test_patch (`sympy/concrete/tests/test_products.py::test_issue_13546`) — not re-run per skip-existing rule. |
| sympy__sympy-13852 | excluded | 3.2 s | same class (`test_polylog_values`; resolves as `sympy/functions/special/tests/test_zeta_functions.py::test_polylog_values` under base+test_patch). |
| sympy__sympy-13974 | **ok=True** | 12.7 s | red→green clean; p2p 4/4 effective. |

### psf/requests — validated 1/2 (exhausted; only 2 usable candidates)

| instance | result | duration | notes |
|---|---|---:|---|
| psf__requests-1724 | ok=False | 8.5 s | **task-class failure (era/dataset semantics), not env.** f2p not red at base: all 6 f2p tests pass at base+test_patch. The underlying bug (unicode method name, gold adds `builtin_str(method)`) is Python-2-only — on py3.9 `u'POST'` is `str`, so the gold change is a no-op and no py3.9 environment can make these red at base; the dataset f2p list is inconsistent with the patch pair under py3.9. Gold f2p and p2p are green (exit=0), so the environment itself is sound. |
| psf__requests-1766 | **ok=True** | 7.9 s | full digest-auth/cookie/redirect f2p set red at base, green at gold over local httpbin; p2p 20/20 green. |

### pytest-dev/pytest — validated 2/2 (target met)

Pre-excluded per acquisition report (parametrized f2p): 10081, 5787, 7205, 7236, 7324, 7432.

| instance | result | duration | notes |
|---|---|---:|---|
| pytest-dev__pytest-5631 | **ok=True** | 5.3 s | p2p 15/15 effective. |
| pytest-dev__pytest-5809 | ok=False | 2.0 s | **env failure, since fixed.** Image lacked `six` (5.2-era `_pytest/assertion/__init__.py` imports it). After adding `six==1.12.0`, manual container re-checks (not harness runs, per skip-existing rule) confirm: base+test_patch → f2p genuinely red (assertion failure), base+gold+test_patch → f2p green. Would validate on a fresh run. |
| pytest-dev__pytest-7490 | **ok=True** | 6.1 s | p2p 16/20 effective (4 unresolvable dropped). |

### pylint-dev/pylint — validated 2/2 (target met; 7277 not attempted)

| instance | result | duration | notes |
|---|---|---:|---|
| pylint-dev__pylint-6903 | **ok=True** | 18.0 s | **FLAG: effective p2p set is EMPTY** — all 8 curated p2p ids are parametrized (`test_runner[run_epylint]` etc.), unresolvable → dropped; `p2p_green_at_gold` is vacuously true. f2p red→green is genuine. |
| pylint-dev__pylint-7080 | **ok=True** | 16.3 s | p2p 20/20 effective. |

### matplotlib/matplotlib — validated 1/1 (target met)

`matplotlib__matplotlib-24026` was pre-excluded (parametrized f2p per acquisition report) and never attempted — only 1 usable candidate exists.

| instance | result | duration | notes |
|---|---|---:|---|
| matplotlib__matplotlib-22719 | **ok=True** | 15.9 s | **FLAG: p2p shrunk to 3/20** — 17 curated p2p ids are parametrized (`test_unit[single]` etc.) and were dropped; p2p green verified over the remaining 3. f2p `test_no_deprecation_on_empty_data` red at base (exit=1), green at gold. Wheel-based image exercises the workspace checkout's pure-Python code (gold touches `lib/matplotlib/category.py` only); compiled extensions are version-matched (3.6.0 wheel vs 3.6-dev base, same series). |

## Failure classification summary

- **Task/dataset-class (1):** psf__requests-1724 — f2p cannot be red at base under py3.9 (py2-only bug; dataset f2p list inconsistent with the patch pair).
- **Env-class, fixed (1):** pytest-dev__pytest-5809 — missing `six` in image (fixed; manual re-check passes both phases; harness not re-run per skip-existing rule).
- **Resolution exclusions (2):** sympy__sympy-13551, sympy__sympy-13852 — f2p tests exist only after test.patch; resolver now runs against base+test_patch (batch-B lesson 2); both confirmed resolvable under the updated flow; not re-run per skip-existing rule.
- **Vacuous/shrunken p2p on validated tasks (2):** pylint-dev__pylint-6903 (0/8 effective — vacuous), matplotlib__matplotlib-22719 (3/20 effective).

## Resume / reproducibility

Per-task JSONs are written after every attempt; the driver skips any `<instance_id>.json` already present in `/tmp/selfdev2-dryrun/results/`. Image rebuild: `docker build -t <tag> -f /tmp/selfdev2-dryrun/images/<org>/<repo>.Dockerfile /tmp/selfdev2-dryrun/images/<org>` (builds have network; runs do not). Driver: `PYTHONPATH=".:src:packages/contracts/src:packages/os_core/src" .venv/bin/python /tmp/selfdev2-dryrun/driver.py [repo]` from the worktree root. Total wall time ≈ 1.5 h including image iteration; the 10 task runs themselves total ≈ 105 s.
