# Batch-C dry-run verifier image for astropy/astropy (ADR-0056 decision 2).
#
# The container runs `python -m pytest <node-id>...` with the task checkout
# bind-mounted at /work (rw). astropy has C extensions: /repo is built
# IN-PLACE at the environment_setup_commit and KEPT in the image; the baked
# sitecustomize.py overlays the compiled *.so files (and the generated
# astropy/_version.py) into the /work checkout at interpreter startup,
# because the executor's restore (`git clean -fdx`) wipes untracked files
# from /work between phases (lesson 4). The /work source shadows
# site-packages (sys.path[0] == cwd), so the checked-out base_commit code
# plus the overlaid artifacts is what pytest imports.
#
# First-candidate group: env commit cdf311e071 (2022-10-25, astropy 5.2.dev);
# candidate bases span 2022-07..2022-12 (same 5.2/5.3 dev series).
# Base pinned to -bookworm (GCC 12): python:3.9-slim now points to trixie
# (GCC 14), which promotes -Wincompatible-pointer-types/-Wint-conversion to
# ERRORS and fails this 2022-era C code (wcslib_celprm_wrap.c,
# fast_sigma_clip.c). Bookworm's GCC 12 keeps them as warnings.
FROM python:3.9-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Era build toolchain (pyproject build-system: setuptools, setuptools_scm,
# wheel, cython==0.29.x, extension-helpers; oldest-supported-numpy replaced by
# an explicit numpy pin because numpy 1.19.x has no cp39 aarch64 wheels).
RUN pip install --no-cache-dir \
    setuptools==65.6.3 \
    wheel==0.41.2 \
    setuptools_scm==7.1.0 \
    Cython==0.29.36 \
    extension-helpers==1.1.0 \
    numpy==1.23.5

# Declared runtime deps (setup.cfg install_requires: numpy>=1.18, pyerfa>=2.0,
# PyYAML>=3.13, packaging>=19.0).
RUN pip install --no-cache-dir \
    pyerfa==2.0.1.1 \
    PyYAML==6.0.1 \
    packaging==23.2

# Repo clone at the candidate group's environment_setup_commit. In-place
# extension build populates /repo/astropy/*.so (overlay source); pip install
# then reuses the build tree for the site-packages copy.
RUN git clone --filter=blob:none https://github.com/astropy/astropy.git /repo \
    && git -C /repo checkout -q cdf311e0714e611d48b0a31eb1f0e2cbffab7f23 \
    && cd /repo \
    && python setup.py build_ext --inplace -j 2 \
    && pip install --no-cache-dir --no-build-isolation . \
    && rm -rf /repo/.git

# Pinned verifier + plugins required by the base checkout's pytest config:
# --doctest-rst addopts (pytest-doctestplus), root conftest `import
# hypothesis`, astropy_header/remote_data ini keys (header/remotedata);
# beautifulsoup4+html5lib so io.ascii html tests run instead of skip.
RUN pip install --no-cache-dir \
    pytest==7.4.4 \
    pytest-doctestplus==1.0.0 \
    pytest-astropy-header==0.2.2 \
    pytest-remotedata==0.4.0 \
    hypothesis==6.88.4 \
    beautifulsoup4==4.12.2 \
    html5lib==1.1

# Build-artifact overlay (image-baked because untracked helper files in /work
# do not survive the executor's restore; lesson 4). Copies every compiled
# *.so and the setuptools_scm-generated _version.py from the in-place /repo
# build into the mounted /work checkout, preserving the package layout.
RUN printf '%s\n' \
    'import os' \
    'import shutil' \
    '' \
    '_SRC = "/repo/astropy"' \
    '_DST = "/work/astropy"' \
    'if os.path.isdir(_SRC) and os.path.isdir(_DST):' \
    '    for _dirpath, _dirnames, _filenames in os.walk(_SRC):' \
    '        _rel = os.path.relpath(_dirpath, _SRC)' \
    '        for _fn in _filenames:' \
    '            if _fn.endswith(".so") or _fn == "_version.py":' \
    '                _s = os.path.join(_dirpath, _fn)' \
    '                _d = os.path.join(_DST, _rel, _fn)' \
    '                os.makedirs(os.path.dirname(_d), exist_ok=True)' \
    '                shutil.copyfile(_s, _d)' \
    > /usr/local/lib/python3.9/site-packages/sitecustomize.py
