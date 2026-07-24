# Batch-C dry-run verifier image for pydata/xarray (ADR-0056 decision 2).
#
# The container runs `python -m pytest <node-id>...` with the task checkout
# bind-mounted at /work (rw); the site-packages xarray copy installed here is
# shadowed by /work at runtime (sys.path[0] == cwd). xarray is pure Python, so
# no artifact overlay is needed (same pattern as batch-B django/sphinx).
# Candidate pydata__xarray-4075: base 2020-05 (xarray 0.16.1.dev), env commit
# 2021-05 (xarray 0.18.1.dev) — era pins: numpy 1.21.6 + pandas 1.2.5
# (pandas 1.1.x has no cp39 manylinux_aarch64 wheel; 1.2.5 is the closest
# era wheel available).
FROM python:3.9-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Build/era toolchain + pinned runtime deps BEFORE /repo install so pip keeps
# the pins (install_requires numpy>=1.15, pandas>=0.25 are satisfied).
RUN pip install --no-cache-dir \
    setuptools==65.6.3 \
    wheel==0.41.2 \
    setuptools_scm==6.4.2 \
    numpy==1.21.6 \
    pandas==1.2.5

# Repo clone at the candidate's environment_setup_commit, pip-installed to
# materialize declared runtime deps + xarray dist metadata (xarray/__init__
# resolves __version__ via pkg_resources at the base commit).
RUN git clone --filter=blob:none https://github.com/pydata/xarray.git /repo \
    && git -C /repo checkout -q 1c198a191127c601d091213c4b3292a8bb3054e1 \
    && pip install --no-cache-dir --no-build-isolation /repo \
    && rm -rf /repo/.git

# Pinned verifier + plugins. pytest-env provides the `env` ini key used by
# the base checkout's setup.cfg [tool:pytest] (harmless if absent, baked for
# fidelity).
RUN pip install --no-cache-dir \
    pytest==7.4.4 \
    pytest-env==1.1.3
