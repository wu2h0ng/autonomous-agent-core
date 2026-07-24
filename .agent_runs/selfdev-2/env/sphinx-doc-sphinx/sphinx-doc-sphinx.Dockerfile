# Batch-B dry-run verifier image for sphinx-doc/sphinx (ADR-0056 decision 2).
#
# The container runs `python -m pytest <node-id>...` with the task checkout
# bind-mounted at /work (rw); the site-packages sphinx copy installed here is
# shadowed by /work at runtime (sys.path[0] == cwd). Candidate bases span
# sphinx 5.0b1..5.1 (docutils <0.19).
FROM python:3.9-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Repo clone at the FIRST candidate's environment_setup_commit (sphinx 5.1.0+),
# pip-installed to materialize the project's declared runtime deps.
RUN git clone --filter=blob:none https://github.com/sphinx-doc/sphinx.git /repo \
    && git -C /repo checkout -q 571b55328d401a6e1d50e37407df56586065a7be \
    && pip install --no-cache-dir /repo \
    && rm -rf /repo/.git

# Pinned verifier + era-correct deps (importlib-metadata pinned <5: sphinx
# 5.x is incompatible with the importlib-metadata >=5 entry-points API).
RUN pip install --no-cache-dir \
    pytest==7.4.4 \
    html5lib==1.1 \
    docutils==0.18.1 \
    Jinja2==3.1.2 \
    importlib-metadata==4.13.0
