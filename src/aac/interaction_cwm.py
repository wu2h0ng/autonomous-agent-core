"""InteractionCWM — CWM-LEARN-3 representation-upgrade mechanism (RR-0039 gate 3, pure stdlib).

Extends LEARN-2's cross-environment sign-consistency invariance selection from RAW features to a DEGREE-2
CROSS-PRODUCT representation (no self-squares), so it can name a NON-ADDITIVE interaction Xc1*Xc2 that the
linear invariance filter (LEARN-2) provably cannot. Reuses LearnedCWM's pure-stdlib logistic primitives
(_fit_logistic / _standardize / _predict / _auc) by subclassing — LEARN-2's learned_cwm.py stays byte-frozen.

Honest framing (mandatory, per design packet §9): this is "invariance selection over a richer SUPPLIED
representation" (a hand-designed degree-2 cross basis), strictly weaker than a LEARNED representation. The
degree-2 basis has NAMED, identifiable coordinates -> selection is well-posed -> a NULL is informative.

Arms provided:
  mode="inv_interaction" — the causal arm: keep degree-2 coordinates whose per-env logistic coefficient is
                           SIGN-STABLE across all training envs AND clears a frozen magnitude floor, refit
                           pooled on survivors, score the held-out shifted env with no refit.
  mode="cap_pooled"      — the CAPACITY-MATCHED nonlinear baseline: identical degree-2 representation, pooled
                           fit over ALL coordinates, NO invariance filter and NO magnitude floor. Isolates
                           the win to the invariance criterion, not the function class (design packet C5).
Consumed OFFLINE, verify-only (returns a scalar AUC; never writes a control path — RR-0026 §5.1).
"""
from __future__ import annotations

import random

from aac.learned_cwm import LearnedCWM, _standardize


def phi(row: list[float]) -> list[float]:
    """Degree-2 CROSS-ONLY representation: the raw features followed by every pairwise product x_i*x_j
    (i<j). NO self-squares x_i^2 (they are the non-flipping spurious trap — design packet §2.3/§3.1)."""
    n = len(row)
    out = list(row)
    for i in range(n):
        for j in range(i + 1, n):
            out.append(row[i] * row[j])
    return out


def product_index(n_raw: int, i: int, j: int) -> int:
    """phi-coordinate index of the product x_i*x_j (i<j) in phi(): raw block is [0, n_raw), then i<j
    products in lexicographic order."""
    if i > j:
        i, j = j, i
    off = 0
    for a in range(n_raw):
        for b in range(a + 1, n_raw):
            if (a, b) == (i, j):
                return n_raw + off
            off += 1
    raise ValueError(f"no product coordinate for ({i},{j})")


class InteractionCWM(LearnedCWM):
    mag_floor: float = 0.15   # FROZEN magnitude-stability threshold on standardized phi (design packet §3.3)

    def invariant_interaction_auc(self, train_envs, test_rows, test_labels, seed,
                                  mode="inv_interaction", permute=False, return_kept=False,
                                  drop_coords=()):
        """Fit on multiple training envs over the degree-2 phi representation, score the held-out test env.

        mode="inv_interaction": per-env logistic on standardized phi; KEEP phi-coords whose coefficient sign
          is stable across ALL envs AND min_e|coef| >= mag_floor; (optionally remove `drop_coords` from the
          kept set for the C7 leave-one-out attribution); refit pooled on survivors; score test (no refit).
        mode="cap_pooled": pooled logistic on ALL phi-coords, no invariance filter, no mag_floor.
        permute=True shuffles labels within every env (confound negative control). return_kept -> also the
        kept phi-coordinate indices."""
        if not train_envs:
            return (0.5, []) if return_kept else 0.5
        n_phi = len(phi(train_envs[0][0][0]))
        coords = list(range(n_phi))

        pooled_rows = [phi(r) for rows, _ in train_envs for r in rows]
        cols = [[pr[j] for pr in pooled_rows] for j in coords]
        _, means, sds = _standardize(cols)

        def std_sub(pr, sub):
            return [(pr[sub[k]] - means[sub[k]]) / sds[sub[k]] for k in range(len(sub))]

        def pooled_xy(salt):
            allrows = [(phi(r), lab) for rows, labs in train_envs for r, lab in zip(rows, labs)]
            random.Random(seed + salt).shuffle(allrows)
            y = [lab for _, lab in allrows]
            if permute:
                random.Random(seed + 8000 + salt).shuffle(y)
            return allrows, y

        if mode == "inv_interaction":
            signs, mags = [], []
            for i, (rows, labs) in enumerate(train_envs):
                pairs = [(phi(r), lab) for r, lab in zip(rows, labs)]
                random.Random(seed + i + 1).shuffle(pairs)
                X = [std_sub(pr, coords) for pr, _ in pairs]
                y = [lab for _, lab in pairs]
                if permute:
                    random.Random(seed + 900 + i).shuffle(y)
                w = self._fit_logistic(X, y)
                signs.append([1 if w[k + 1] > 0 else (-1 if w[k + 1] < 0 else 0) for k in range(n_phi)])
                mags.append([abs(w[k + 1]) for k in range(n_phi)])
            keep = [k for k in range(n_phi)
                    if signs[0][k] != 0
                    and all(signs[e][k] == signs[0][k] for e in range(len(signs)))
                    and min(mags[e][k] for e in range(len(mags))) >= self.mag_floor]
            keep = [k for k in keep if k not in set(drop_coords)]
            if not keep:
                return (0.5, []) if return_kept else 0.5
            allrows, yp = pooled_xy(salt=7)
            Xp = [std_sub(pr, keep) for pr, _ in allrows]
            w = self._fit_logistic(Xp, yp)
            scores = [self._predict(w, std_sub(phi(r), keep)) for r in test_rows]
            auc = self._auc(scores, list(test_labels))
            return (auc, keep) if return_kept else auc

        # mode == "cap_pooled": all phi coords, no invariance filter, no mag_floor
        allrows, yp = pooled_xy(salt=7)
        Xp = [std_sub(pr, coords) for pr, _ in allrows]
        w = self._fit_logistic(Xp, yp)
        scores = [self._predict(w, std_sub(phi(r), coords)) for r in test_rows]
        return self._auc(scores, list(test_labels))
