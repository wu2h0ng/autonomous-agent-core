# SELFDEV-4 (batch S4) dry-run verifier image for scikit-learn 1.3.dev-era
# candidate scikit-learn__scikit-learn-25973 (base 2023-03-27), built AT THE
# CANDIDATE BASE COMMIT (ADR-0056 decision 2).
#
# Why not the env-commit image (scikit-learn-scikit-learn-1.3.Dockerfile,
# built at env commit 1e8a5b833d1b, 2023-06-12): between 2023-03 and 2023-06
# sklearn removed the UNSUFFIXED `METRIC_MAPPING` alias from
# metrics/_dist_metrics (June sources import METRIC_MAPPING64; March sources
# import METRIC_MAPPING). The June-built *.so overlay therefore cannot serve a
# March checkout — sklearn.metrics imports fail in every phase (verified
# empirically 2026-07-30; recorded in the batch-S4 report). Building /repo at
# the candidate's own base eliminates the skew. The March base of 25747
# (2023-03-02) already validated against the June image, so it keeps that
# image; this -1.3mar image serves only 25973.
#
# Same pattern as the 0.21 image: /repo is built IN-PLACE and KEPT; the baked
# sitecustomize.py overlays the compiled *.so files into the /work checkout at
# interpreter startup (the executor's `git clean -fdx` wipes untracked
# artifacts between phases). /work source shadows site-packages.
#
# sklearn 1.3 still builds via numpy.distutils (pyproject [build-system]
# requires setuptools + Cython>=0.29.33 + numpy + scipy>=1.5.0), so
# setuptools must stay <60. Base pinned to -bookworm (GCC 12), consistent
# with the batch-C finding for era C sources.
# Unlike the 0.21 image there is NO vendored joblib in 1.3 (sklearn/externals
# was removed in 0.23) -> no SKLEARN_SITE_JOBLIB escape hatch needed.
# pandas is kept from the 1.3 image pins (set_output tests in this era import
# it; harmless for 25973).
FROM python:3.9-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Era build toolchain (setuptools<60 for numpy.distutils; Cython 0.29.36
# satisfies >=0.29.33; numpy 1.23.5 has cp39 manylinux_aarch64 wheels and
# predates the 1.24 alias removals; scipy 1.10.1 is the era release with a
# cp39 aarch64 wheel).
RUN pip install --no-cache-dir \
    setuptools==59.8.0 \
    wheel==0.41.2 \
    Cython==0.29.36 \
    numpy==1.23.5 \
    scipy==1.10.1

# Repo clone at the candidate group's environment_setup_commit. In-place
# extension build populates /repo/sklearn/*.so (overlay source); pip install
# then reuses the build tree for the site-packages copy. joblib 1.2.0 /
# threadpoolctl 3.1.0 satisfy sklearn 1.3's minimums (>=1.1.1 / >=2.0.0) and
# are imported unconditionally by sklearn/conftest.py.
RUN git clone --filter=blob:none \
        https://github.com/scikit-learn/scikit-learn.git /repo \
    && git -C /repo checkout -q 10dbc142bd17ccf7bd38eec2ac04b52ce0d1009e \
    && pip install --no-cache-dir joblib==1.2.0 threadpoolctl==3.1.0 \
    && cd /repo \
    && python setup.py build_ext --inplace -j 2 \
    && pip install --no-cache-dir --no-build-isolation . \
    && rm -rf /repo/.git

# Pinned verifier + pandas (see header; era pandas with cp39 aarch64 wheel).
# No extra pytest plugins: setup.cfg addopts (--doctest-modules,
# --disable-pytest-warnings, --color=yes) are pytest-core flags.
RUN pip install --no-cache-dir \
    pytest==7.4.4 \
    pandas==2.0.2

# Build-artifact overlay (image-baked because untracked helper files in /work
# do not survive the executor's restore). Copies every compiled *.so from the
# in-place /repo build into the mounted /work checkout, preserving the
# package layout (includes sklearn/__check_build/_check_build).
RUN printf '%s\n' \
    'import os' \
    'import shutil' \
    '' \
    '_SRC = "/repo/sklearn"' \
    '_DST = "/work/sklearn"' \
    'if os.path.isdir(_SRC) and os.path.isdir(_DST):' \
    '    for _dirpath, _dirnames, _filenames in os.walk(_SRC):' \
    '        _rel = os.path.relpath(_dirpath, _SRC)' \
    '        for _fn in _filenames:' \
    '            if _fn.endswith(".so"):' \
    '                _s = os.path.join(_dirpath, _fn)' \
    '                _d = os.path.join(_DST, _rel, _fn)' \
    '                os.makedirs(os.path.dirname(_d), exist_ok=True)' \
    '                shutil.copyfile(_s, _d)' \
    > /usr/local/lib/python3.9/site-packages/sitecustomize.py
