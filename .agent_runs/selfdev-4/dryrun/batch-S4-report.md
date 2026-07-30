# SELFDEV-4 Dry-Run Acquisition Report (2026-07-28)

## Scope

- Pool: .agent_runs/selfdev-2/dataset/candidate-pool.json minus 17 SELFDEV-2 main-subset tasks, minus parametrized f2p ids (130 candidates, 8 repos).
- Procedure: per candidate — clone --shared from local mirrors, checkout base_commit, resolve f2p/p2p node ids against base+test_patch (per-id, drop unresolvable), then ADR-0056 Decision-5 gold validation in per-repo container images (base+test_patch red, base+gold+test_patch green).
- Evidence: per-task result JSONs in this directory (incl. evidence_digest bound into .agent_runs/selfdev-4/selection.json).

## Validated into the subset (13 new)

- django__django-9296 (django/django)
- django__django-10880 (django/django)
- django__django-10999 (django/django)
- django__django-11066 (django/django)
- sympy__sympy-13551 (sympy/sympy)
- sympy__sympy-13852 (sympy/sympy)
- sphinx-doc__sphinx-7889 (sphinx-doc/sphinx)
- sphinx-doc__sphinx-8459 (sphinx-doc/sphinx)
- sphinx-doc__sphinx-9658 (sphinx-doc/sphinx)
- astropy__astropy-13579 (astropy/astropy)
- scikit-learn__scikit-learn-25747 (scikit-learn/scikit-learn)
- pytest-dev__pytest-5809 (pytest-dev/pytest)
- pylint-dev__pylint-7277 (pylint-dev/pylint)

## Carried from SELFDEV-2 reserve (unconsumed, previously validated)

- sympy__sympy-12419, astropy__astropy-14182, scikit-learn__scikit-learn-13328, pytest-dev__pytest-5631 (pytest-dev__pytest-7490 dropped by the declared pytest cap).
- Their gold-validation evidence is committed in the SELFDEV-2 dry-run reports (.agent_runs/selfdev-2/dryrun/batch-A-report.md for sympy-12419/pytest-5631/pytest-7490, batch-C-report.md for astropy-14182/sklearn-13328) and their evidence digests are pinned in .agent_runs/selfdev-2/selection.json (both committed at 5bd618b).

## Notable exclusions / dead tasks

- psf__requests-1724: f2p NOT red at base (gold bug is Python-2-only; no-op on py3.9) — dead task, recorded.
- astropy__astropy-7671: f2p red at gold. astropy__astropy-13033: p2p red at gold.
- scikit-learn__scikit-learn-25973: f2p collection error (exit=4) in both phases.
- django__django-7530: f2p red at gold. django__django-10973: prose f2p id.
- sympy__sympy-15017 / 15345: unresolvable bare f2p names.
- sphinx 7910/7985/8269/8475/8721/9230, sklearn-13142, sympy-14976: multi-file test or gold patch (executor single-file fail-closed).

## Environment incidents (documented, corrected)

- 3 mirror stubs (sympy/requests/pytest) found invalid (hooks/info/objects only) — rebuilt from GitHub, verified bare.
- mirror_for originally matched org directories (mirrors/sympy) before real repos — fixed to require HEAD presence.
- sklearn-25747 required a new 1.3-era image (selfdev2-dryrun-sklearn13:py39); Dockerfile + pins committed at .agent_runs/selfdev-2/env/scikit-learn-scikit-learn/.
