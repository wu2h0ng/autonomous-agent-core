# Batch-C dry-run verifier image for scikit-learn/scikit-learn (ADR-0056
# decision 2).
#
# The container runs `python -m pytest <node-id>...` with the task checkout
# bind-mounted at /work (rw). sklearn has Cython/C extensions: /repo is built
# IN-PLACE at the environment_setup_commit and KEPT in the image; the baked
# sitecustomize.py overlays the compiled *.so files into the /work checkout
# at interpreter startup, because the executor's restore (`git clean -fdx`)
# wipes untracked files from /work between phases (lesson 4). The /work
# source shadows site-packages (sys.path[0] == cwd), so the checked-out
# base_commit code plus the overlaid artifacts is what pytest imports.
#
# First-candidate group: env commit 7813f7efb5 (2019-05-24, sklearn 0.21.2);
# candidate bases span 2019-03..2019-06 (same 0.21 dev series). sklearn 0.21
# builds via numpy.distutils -> setuptools must stay <60.
# Base pinned to -bookworm (GCC 12): python:3.9-slim now points to trixie
# (GCC 14), which promotes old-C warnings to ERRORS; 2019-era sklearn C
# sources would not compile there.
FROM python:3.9-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Era build toolchain. setuptools<60 is required: sklearn 0.21 setup.py
# builds extensions through numpy.distutils, which setuptools>=60 breaks.
# numpy 1.23.5 = last series before np.int removal (1.24), cp39 aarch64
# wheel exists; scipy 1.9.3 = era-compatible with cp39 aarch64 wheel.
RUN pip install --no-cache-dir \
    setuptools==59.8.0 \
    wheel==0.41.2 \
    Cython==0.29.36 \
    numpy==1.23.5 \
    scipy==1.9.3

# Repo clone at the candidate group's environment_setup_commit. In-place
# extension build populates /repo/sklearn/*.so (overlay source); pip install
# then reuses the build tree for the site-packages copy. joblib 0.15.1:
# py3.9-compatible while still accepting sklearn 0.21's Memory(cachedir=...).
RUN git clone --filter=blob:none \
        https://github.com/scikit-learn/scikit-learn.git /repo \
    && git -C /repo checkout -q 7813f7efb5b2012412888b69e73d76f2df2b50b6 \
    && pip install --no-cache-dir joblib==0.15.1 \
    && cd /repo \
    && python setup.py build_ext --inplace -j 2 \
    && pip install --no-cache-dir --no-build-isolation . \
    && rm -rf /repo/.git

# Pinned verifier. No extra plugins: the base checkout's addopts
# (--disable-pytest-warnings, --doctest-modules) are pytest-core flags, and
# the root conftest only needs distutils + _pytest.doctest (pytest 7.4 OK).
RUN pip install --no-cache-dir \
    pytest==7.4.4

# sklearn 0.21's vendored joblib (sklearn/externals/joblib) ships a
# cloudpickle that predates the Python 3.8 CodeType change and cannot be
# imported on 3.9 ("an integer is required (got type bytes)"). Upstream's
# own escape hatch — honored by sklearn/utils/_joblib.py at every candidate
# base commit — routes to the site joblib (0.15.1, installed above) instead.
ENV SKLEARN_SITE_JOBLIB=1

# Build-artifact overlay (image-baked because untracked helper files in /work
# do not survive the executor's restore; lesson 4). Copies every compiled
# *.so from the in-place /repo build into the mounted /work checkout,
# preserving the package layout (includes sklearn/__check_build/_check_build).
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
