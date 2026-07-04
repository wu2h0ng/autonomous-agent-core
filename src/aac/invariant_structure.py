"""InvariantStructureFilter — the CWM causal-generalisation component (production form of CWM-LEARN-2/3).

Consolidates the VALIDATED capability of the CWM-LEARN program (founder calibration 2026-07-04) into one
domain-agnostic, verify-only organ: given data from MULTIPLE environments that share a causal mechanism but
differ in nuisance, select the structure (over a SUPPLIED basis) whose per-environment logistic coefficient is
sign-stable and magnitude-floored across all environments, and refit a pooled classifier on the survivors.

Validated boundary this component lives inside (preregistered, four gates):
  - basis="raw"    : the LEARN-3 selection rule (sign-stability + magnitude floor) applied over the raw
                     basis — LEARN-2-ADJACENT, not the byte-gated LEARN-2 mechanism (that one is sign-only,
                     no floor: learned_cwm.invariant_predict_auc). On LEARN-2's gated SCM this variant keeps
                     the same causal set ([x0,x1], dropping the noise slip-ins the floor was built to drop)
                     at equal AUC — tested, but the "LEARN-2 MET" evidence label belongs to the original.
  - basis="cross2" : LEARN-3 MET — degree-2 CROSS-product basis (NO self-squares: a squared spurious channel
                     does not sign-flip and would survive selection — the red-team trap) beats both the linear
                     arm and a capacity-matched pooled baseline on interaction structure; transfers across an
                     isolated environment family (LEARN-4: supplied basis 0.89 vs learned-rep chance).
  - NOT in scope   : DISCOVERING the basis/representation from data (LEARN-4 NULL — V-REx/IRM representation
                     learning collapses on isolated families; industry-consistent, Rosenfeld et al.). The basis
                     is supplied by the caller (domain knowledge or an upstream proposer organ, e.g. an LLM
                     hypothesis generator whose output this component then VERIFIES — proposer/disposer form).

Consumption contract (RR-0026 §5.1): fit OFFLINE; the fitted model is frozen and returns scalars/structure
only; it never writes a control path, never mutates its inputs, and refuses to predict when no invariant
structure was found (fail-closed, not constant-return).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from aac.learned_cwm import LearnedCWM, _standardize


class NoInvariantStructure(Exception):
    """Raised when predict/score is called on a model that found no invariant structure (fail-closed)."""


class SchemaMismatch(ValueError):
    """Raised when a row's width differs from the width the model was fitted on (fail-closed: a width
    drift silently relocates every basis coordinate, so predicting would return well-formed garbage)."""


# ---- supplied bases (the caller chooses; discovery is out of validated scope) ----

def basis_raw(row: list[float]) -> list[float]:
    """Identity basis — LEARN-2 validated scope (linear invariant structure)."""
    return list(row)


def basis_cross2(row: list[float]) -> list[float]:
    """Raw + degree-2 CROSS products (i<j), NO self-squares — LEARN-3 validated scope."""
    n = len(row)
    out = list(row)
    for i in range(n):
        for j in range(i + 1, n):
            out.append(row[i] * row[j])
    return out


def basis_cross2_names(n_raw: int) -> list[str]:
    names = [f"x{i}" for i in range(n_raw)]
    for i in range(n_raw):
        for j in range(i + 1, n_raw):
            names.append(f"x{i}*x{j}")
    return names


_BASES = {"raw": basis_raw, "cross2": basis_cross2}


@dataclass
class InvariantModel:
    """Frozen fitted result. found=False models refuse to predict (fail-closed)."""
    found: bool
    basis: str
    kept: tuple[int, ...]                 # kept basis-coordinate indices
    kept_names: tuple[str, ...]           # human-readable structure (e.g. "x0*x1")
    n_envs: int
    seed: int
    n_raw: int = 0                        # raw-row width the model was fitted on (schema guard)
    _w: tuple[float, ...] = field(default=(), repr=False)
    _means: tuple[float, ...] = field(default=(), repr=False)
    _sds: tuple[float, ...] = field(default=(), repr=False)
    _basis_fn: object = field(default=None, repr=False)

    def predict_proba(self, row: list[float]) -> float:
        if not self.found:
            raise NoInvariantStructure(
                "no invariant structure was found at fit time; refusing to predict (fail-closed)")
        if len(row) != self.n_raw:
            raise SchemaMismatch(
                f"row width {len(row)} != fitted width {self.n_raw}; a width drift relocates basis "
                f"coordinates, so predicting would silently return garbage (fail-closed)")
        pr = self._basis_fn(row)
        x = [(pr[self.kept[k]] - self._means[k]) / self._sds[k] for k in range(len(self.kept))]
        return LearnedCWM._predict(list(self._w), x)

    def score_auc(self, rows: list[list[float]], labels: list[int]) -> float:
        if not self.found:
            raise NoInvariantStructure(
                "no invariant structure was found at fit time; refusing to score (fail-closed)")
        return LearnedCWM._auc([self.predict_proba(r) for r in rows], list(labels))


class InvariantStructureFilter:
    """fit(envs, seed) -> InvariantModel. envs: list of (rows, labels) sharing a causal mechanism but
    differing in nuisance. Selection = per-env logistic sign-stability AND per-env |coef| >= mag_floor
    (the LEARN-3 frozen threshold), then pooled refit on survivors."""

    def __init__(self, basis: str = "cross2", mag_floor: float = 0.15,
                 lr: float = 0.1, epochs: int = 200, l2: float = 1e-3):
        if basis not in _BASES:
            raise ValueError(f"unknown basis {basis!r}; validated bases: {sorted(_BASES)}")
        self.basis = basis
        self.mag_floor = mag_floor
        self._fitter = LearnedCWM(lr=lr, epochs=epochs, l2=l2)

    def fit(self, envs: list[tuple[list[list[float]], list[int]]], seed: int = 0) -> InvariantModel:
        if len(envs) < 2:
            raise ValueError("invariance selection requires >= 2 environments "
                             "(with one environment, nuisance and mechanism are indistinguishable)")
        n_raw = len(envs[0][0][0]) if envs[0][0] else 0
        for rows, labels in envs:
            if not rows or len(rows) != len(labels):
                raise ValueError("each environment needs non-empty rows with matching labels")
            for r in rows:
                if len(r) != n_raw:
                    raise ValueError(f"ragged rows: expected width {n_raw}, got {len(r)}")
        bfn = _BASES[self.basis]
        n_phi = len(bfn(envs[0][0][0]))
        names = (basis_cross2_names(len(envs[0][0][0])) if self.basis == "cross2"
                 else [f"x{i}" for i in range(n_phi)])

        pooled_rows = [bfn(r) for rows, _ in envs for r in rows]
        cols = [[pr[j] for pr in pooled_rows] for j in range(n_phi)]
        _, means, sds = _standardize(cols)

        def std_all(pr):
            return [(pr[k] - means[k]) / sds[k] for k in range(n_phi)]

        signs, mags = [], []
        for i, (rows, labels) in enumerate(envs):
            pairs = [(bfn(r), lab) for r, lab in zip(rows, labels)]
            random.Random(seed + i + 1).shuffle(pairs)
            w = self._fitter._fit_logistic([std_all(pr) for pr, _ in pairs], [lab for _, lab in pairs])
            signs.append([1 if w[k + 1] > 0 else (-1 if w[k + 1] < 0 else 0) for k in range(n_phi)])
            mags.append([abs(w[k + 1]) for k in range(n_phi)])
        keep = tuple(k for k in range(n_phi)
                     if signs[0][k] != 0
                     and all(signs[e][k] == signs[0][k] for e in range(len(envs)))
                     and min(m[k] for m in mags) >= self.mag_floor)
        if not keep:
            return InvariantModel(found=False, basis=self.basis, kept=(), kept_names=(),
                                  n_envs=len(envs), seed=seed, n_raw=n_raw)

        allrows = [(bfn(r), lab) for rows, labels in envs for r, lab in zip(rows, labels)]
        random.Random(seed + 7).shuffle(allrows)
        kept_means = [means[k] for k in keep]
        kept_sds = [sds[k] for k in keep]
        Xp = [[(pr[keep[k]] - kept_means[k]) / kept_sds[k] for k in range(len(keep))] for pr, _ in allrows]
        w = self._fitter._fit_logistic(Xp, [lab for _, lab in allrows])
        return InvariantModel(found=True, basis=self.basis, kept=keep,
                              kept_names=tuple(names[k] for k in keep), n_envs=len(envs), seed=seed,
                              n_raw=n_raw, _w=tuple(w), _means=tuple(kept_means), _sds=tuple(kept_sds),
                              _basis_fn=bfn)
