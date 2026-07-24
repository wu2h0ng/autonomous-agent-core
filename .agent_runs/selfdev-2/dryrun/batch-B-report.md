# SELFDEV-2 Gold-Validation Dry-Run — Batch B Report

- **Date:** 2026-07-23 (local, UTC+8)
- **Worktree:** `autonomous-agent-core/.worktrees/canonical-convergence-20260715`
- **Docker:** colima up, client 29.6.0 / server 29.1.3 (linux/arm64, virtiofs)
- **Batch repos:** django/django, sphinx-doc/sphinx
- **Artifacts:**
  - results: `/tmp/selfdev2-dryrun/results/<instance_id>.json` (5 files)
  - images: `/tmp/selfdev2-dryrun/images/{django-django,sphinx-doc-sphinx}.Dockerfile` + `.pins.json`
  - mirrors: `/tmp/selfdev2-dryrun/mirrors/{django-django,sphinx-doc-sphinx}.git`
  - driver: `/tmp/selfdev2-dryrun/runner.py` (resumable; skips existing results)
  - workspaces: `/tmp/selfdev2-dryrun/ws` → symlink to
    `~/Documents/AI-Agent-Projects/.cache/selfdev2-dryrun-ws` (see INFRA-2)

## Outcome summary

| repo | tried | validated (ok) | target met |
|---|---:|---:|---|
| django/django | 3 | **2** | yes (2/2) |
| sphinx-doc/sphinx | 2 | **2** | yes (2/2) |

Validated tasks (all phases correct: base+test_patch F2P **red**;
base+gold+test_patch F2P and P2P **green**; verifier timeout 600 s/phase):

| instance_id | duration | evidence_digest (sha256, prefix) |
|---|---:|---|
| django__django-13670 | 13.6 s | cf2d561a212c… |
| django__django-14089 | 13.5 s | 518dfd85a58d… |
| sphinx-doc__sphinx-10449 | 10.3 s | 87aefc69785c… |
| sphinx-doc__sphinx-10466 | 9.5 s | b6b56f3bf1bd… |

**Multi-file test_patch flag:** none of the four validated tasks has a
multi-file test patch (all 1 file, 509–1175 bytes). Multi-file test patches
were excluded up front during candidate selection — the executor's
single-file fail-closed rule (`validate_unified_diff`, also the 64 KiB cap)
rejects them deterministically before any container run.

**Failed candidate:** `django__django-13343` — `TASK_INVALID
BENCHMARK_NODE_ID_UNRESOLVED`: its **P2P** list contains the prose id
`Regression test for #9610.`. The acquisition report's style classification
only inspected F2P ids (13343's f2p is clean unittest style); prose ids also
occur in P2P lists. Recommendation: extend the pool's style sweep to p2p
ids. Resolution correctly failed closed.

**Exclusions honored:** parametrized sphinx 8265/8621/9367 not tried; the 8
django `mixed`-style entries not tried; candidates picked with small f2p
sets, single-file test patches, django 3.2a/4.0a and sphinx 5.x base eras.

## django/django

- **Image:** `selfdev2-dryrun-django:py39` (`python:3.9-slim`)
- **Repo in image:** cloned to `/repo` @ `65dfb06a1ab56c…` (first candidate's
  `environment_setup_commit`, django 3.2a), `pip install /repo` (installed as
  `Django @ file:///repo`, 3.2.1) — at runtime shadowed by the `/work`
  checkout (sys.path[0]=cwd), so the checked-out base_commit code is what
  pytest imports.
- **Pinned deps** (`images/django-django.pins.json`): asgiref==3.7.2,
  sqlparse==0.4.4, pytz==2024.1, pytest==7.4.4, pytest-django==4.5.2
  (+ transitive exceptiongroup, iniconfig, packaging, pluggy, tomli,
  typing_extensions).
- **Settings solution (recorded per instructions):** django's own
  `tests/test_sqlite.py` defines no `INSTALLED_APPS` — `tests/runtests.py`
  builds it dynamically. The image bakes
  `/usr/local/lib/python3.9/site-packages/sitecustomize.py` which, only when
  a django checkout is mounted at `/work`: prepends `/work` and
  `/work/tests` to `sys.path`, sets `DJANGO_SETTINGS_MODULE=test_sqlite` and
  `RUNNING_DJANGOS_TEST_SUITE=true`, then replicates `runtests.py:setup()` —
  ALWAYS_INSTALLED_APPS, `ROOT_URLCONF='urls'`, TEMPLATES (APP_DIRS +
  `/work/tests/templates`), ALWAYS_MIDDLEWARE, `LANGUAGE_CODE='en'`,
  `SITE_ID=1`, `MIGRATION_MODULES={'auth':None,'contenttypes':None,
  'sessions':None}`, `SILENCED_SYSTEM_CHECKS` — **and appends the test
  packages named by the pytest node-id argv** (e.g. `tests/utils_tests/…` →
  `utils_tests`), mirroring `runtests.get_apps_to_install` so test-package
  models register — then calls `django.setup()`. `pytest-django` (4.5.2)
  reads the env var and creates in-memory sqlite test DBs for
  `django.test.TestCase` classes. A conftest.py in `/work` was not an option:
  the executor's restore (`git clean -fdx`) wipes untracked files every
  phase. Verified: `pytest --collect-only` of a resolved f2p id collects 1
  item; both validated tasks pass all phases.
- Candidates tried: 13670 (ok), 13343 (failed, above), 14089 (ok). 4th slot
  unused (target reached).

## sphinx-doc/sphinx

- **Image:** `selfdev2-dryrun-sphinx:py39` (`python:3.9-slim`)
- **Repo in image:** cloned to `/repo` @ `571b55328d40…` (first candidate's
  env commit, sphinx 5.1.0+), `pip install /repo`; runtime uses the `/work`
  checkout (bases 5.1.0+ / 5.0.0b1, both `docutils<0.19` era).
- **Pinned deps** (`images/sphinx-doc-sphinx.pins.json`): pytest==7.4.4,
  html5lib==1.1, docutils==0.18.1, Jinja2==3.1.2,
  importlib-metadata==4.13.0 (pinned <5: sphinx 5.x is incompatible with the
  importlib-metadata ≥5 entry-points API) + resolved runtime deps
  (Pygments, babel, alabaster, imagesize, requests, snowballstemmer,
  packaging, sphinxcontrib-*, …).
- No settings shim needed: pytest-style ids, repo `tests/conftest.py` +
  `setup.cfg [tool:pytest]` come with the checkout. `--network none` is fine
  (no linkcheck/network tests among candidates).
- Candidates tried: 10449 (ok), 10466 (ok). 3rd/4th slots unused.

## Infra / executor findings (must-fix before the real round)

- **EXECUTOR-BUG-1 (blocker):** `benchmark_container.ContainerRunner` builds
  `--mount type=bind,src=…,dst=/work,rw=true`. Docker's `--mount` grammar
  (verified client 29.6.0 / server 29.1.3) rejects the `rw` key:
  `unknown option 'rw' in 'rw=true'` — every verifier run would fail closed
  with exit 125 → `BENCHMARK_CONTAINER_RUN_FAILED`. Bind mounts are rw by
  default; the `,rw=true` token must be dropped (or replaced by the
  `readonly`/`ro` key) in `benchmark_container.py`. For this dry run the
  token was stripped in an **injected `DockerRunner` wrapper** in
  `runner.py` (semantics-preserving; no repo code modified, per batch
  instructions). All security flags (`--network none`, `--read-only`,
  tmpfs, limits, single mount, argv-list discipline) were exercised
  unchanged.
- **INFRA-2 (environment):** this colima profile exports only `/Users` into
  the VM (`mounts: []`); `/tmp` resolves to `/private/tmp` **on the host
  only** — the VM has its own unrelated `/private/tmp`, so bind sources
  under `/tmp/...` fail with `bind source path does not exist`. Workaround
  used: workspaces live under
  `~/Documents/AI-Agent-Projects/.cache/selfdev2-dryrun-ws` (gitignored),
  with `/tmp/selfdev2-dryrun/ws` as a symlink; the executor's
  `work_dir.resolve()` maps the mount source into the VM-visible path, so
  the production code path works unmodified. For the real round, either keep
  workspaces under `/Users` or add `/private/tmp` to colima mounts.
- **Node-id resolution must run against base+test_patch**: F2P tests are
  typically added by the hidden test patch, so resolving against pristine
  base fails closed (`method not found`). `runner.py` applies
  `test.patch` (fail-closed single-file `apply_unified_diff`) before
  `resolve_benchmark_node_ids`; `run_gold_validation` then restores the
  workspace itself. This ordering should be documented in the admission
  pipeline.
- **Harmless observations:** pytest plugin header shows `typeguard-4.3.0`
  (vendored inside setuptools 79.0.1's `_vendor`, auto-discovered via
  `distutils-precedence.pth`); present during all passing runs, no effect.
  git on macOS prints `failed to encode … wrongenc.inc` warnings when
  checking out sphinx (intentionally mis-encoded test fixtures); irrelevant
  to the validated tasks, may matter for `test-warnings`-root tasks.
- **Shared directory note:** `/tmp/selfdev2-dryrun` is concurrently used by
  another batch (their `driver.py`, mirrors, logs). Result filenames are
  per-instance and repo-scoped filtering avoids interference.

## Procedure compliance

- One docker build/run at a time within batch B; network only at
  mirror-clone and image-build time (verifier containers run `--network
  none`); no repo code changed; no git commits anywhere.
- `results/*.json` written after every task (pass or fail); resume skips
  existing results (verified via rerun flow).
- Per task: `instance_id, repo, ok, f2p_red_at_base, f2p_green_at_gold,
  p2p_green_at_gold, detail, evidence_digest, image_tag, python_version,
  duration_s` — all present.
