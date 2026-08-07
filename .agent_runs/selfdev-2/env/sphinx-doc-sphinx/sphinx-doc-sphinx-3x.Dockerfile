# SELFDEV-4 (batch S4) dry-run verifier image for sphinx-doc/sphinx 3.x-era
# candidates (ADR-0056 decision 2).
#
# Candidates: sphinx-doc__sphinx-7889 (base 2020-06-30, sphinx 3.2.dev) and
# sphinx-doc__sphinx-8459 (base 2020-11-21, sphinx 3.4.dev); env commit
# f92fa6443fe6 (2020-08-08, first candidate's environment_setup_commit).
# The batch-B 5.x-era image CANNOT run these: it pins Jinja2==3.1.2, and
# sphinx 3.x imports `from jinja2 import environmentfilter` (removed in
# Jinja2 3.1) in sphinx/util/rst.py — every phase fails at conftest import
# (verified empirically 2026-07-30; env-class failure, recorded in the
# batch-S4 report). This image pins the 2020-era dep set instead.
#
# Pure-Python repo: the site-packages sphinx installed here is shadowed by
# the /work checkout at runtime (sys.path[0] == cwd) — /repo only
# materializes the declared runtime deps. No settings shim or artifact
# overlay needed (same pattern as batch B).
FROM python:3.9-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Repo clone at the FIRST candidate's environment_setup_commit (sphinx
# 3.2.dev, 2020-08), pip-installed to materialize the project's declared
# runtime deps (both candidates' setup.py requires are identical).
RUN git clone --filter=blob:none https://github.com/sphinx-doc/sphinx.git /repo \
    && git -C /repo checkout -q f92fa6443fe6f457ab0c26d41eb229e825fda5e1 \
    && pip install --no-cache-dir /repo \
    && rm -rf /repo/.git

# Pinned verifier + era-correct deps. The era setup.py declares no upper
# caps, so the sensitive deps are pinned explicitly:
# - Jinja2 2.11.3: last series with environmentfilter (removed in 3.1);
#   MarkupSafe pinned 2.0.1 (2.1 removed soft_unicode, needed by Jinja2 2.11).
# - docutils 0.16: era release (sphinx 3.x predates the docutils 0.17+ API
#   changes; the 5.x image's 0.18.1 is too new).
# - sphinxcontrib-{htmlhelp,serializinghtml,qthelp} 1.x: era series; the
#   resolved 2.x series targets sphinx >=5.
# - sphinxcontrib-{applehelp,devhelp} 1.0.2: era series; the resolved 2.0.0
#   calls app.require_sphinx('5.0') at extension setup, which errors every
#   SphinxTestApp on a 3.x checkout (found probing sphinx-8459).
# - pytest 6.2.5: contemporary with the 2020-era conftest/testing plugins
#   (pluggy 0.13.1 pulled automatically).
RUN pip install --no-cache-dir \
    pytest==6.2.5 \
    html5lib==1.1 \
    docutils==0.16 \
    Jinja2==2.11.3 \
    MarkupSafe==2.0.1 \
    sphinxcontrib-applehelp==1.0.2 \
    sphinxcontrib-devhelp==1.0.2 \
    sphinxcontrib-htmlhelp==1.0.3 \
    sphinxcontrib-serializinghtml==1.1.4 \
    sphinxcontrib-qthelp==1.0.3 \
    sphinxcontrib-jsmath==1.0.1
