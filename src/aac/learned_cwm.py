"""LearnedCWM — a learned causal-mechanism organ (S1b; our own built model).

Formal model / prereg: docs/pre_spec/S1B-CWM-LEARN-1.PREREG-2026-07-03.md (f6ab589).

For a target T and an intervenable node X, LearnedCWM fits an OFFLINE logistic classifier
that learns the MECHANISM SIGNATURE of do(X): P(sample came from the do(X) regime | the values
of all proteins except T). If intervening on X leaves a learnable multivariate signature that a
held-out split can detect above chance, X is judged a causal ancestor of T. This is a genuinely
learned model (multivariate, fit by gradient descent) contrasted with the marginal effect-size
baseline — it may capture mediated structure the marginal misses, or it may tie.

Pure-stdlib logistic regression (no third-party deps, ENGINEERING.md). The model is fit offline
and frozen; it never runs inference in the control path (verify-only consumption, RR-0026 §5.1).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass


def _standardize(cols: list[list[float]]) -> tuple[list[list[float]], list[float], list[float]]:
    n = len(cols[0]) if cols else 0
    means, sds = [], []
    for c in cols:
        m = sum(c) / len(c)
        sd = (sum((x - m) ** 2 for x in c) / len(c)) ** 0.5 or 1.0
        means.append(m)
        sds.append(sd)
    std = [[(cols[j][i] - means[j]) / sds[j] for j in range(len(cols))] for i in range(n)]
    return std, means, sds


@dataclass
class LearnedCWM:
    lr: float = 0.1
    epochs: int = 200
    l2: float = 1e-3

    def _fit_logistic(self, X: list[list[float]], y: list[int]) -> list[float]:
        d = len(X[0])
        w = [0.0] * (d + 1)  # + bias
        for _ in range(self.epochs):
            grad = [0.0] * (d + 1)
            for xi, yi in zip(X, y):
                z = w[0] + sum(w[k + 1] * xi[k] for k in range(d))
                p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
                err = p - yi
                grad[0] += err
                for k in range(d):
                    grad[k + 1] += err * xi[k]
            w[0] -= self.lr * grad[0] / len(X)
            for k in range(d):
                w[k + 1] -= self.lr * (grad[k + 1] / len(X) + self.l2 * w[k + 1])
        return w

    @staticmethod
    def _predict(w: list[float], x: list[float]) -> float:
        z = w[0] + sum(w[k + 1] * x[k] for k in range(len(x)))
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))

    @staticmethod
    def _auc(scores: list[float], labels: list[int]) -> float:
        # rank-based Mann-Whitney AUC, O(n log n) (ties get average ranks)
        n_pos = sum(labels)
        n_neg = len(labels) - n_pos
        if n_pos == 0 or n_neg == 0:
            return 0.5
        order = sorted(range(len(scores)), key=lambda i: scores[i])
        ranks = [0.0] * len(scores)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0  # 1-based average rank over the tie block
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        sum_pos_ranks = sum(ranks[i] for i in range(len(labels)) if labels[i] == 1)
        return (sum_pos_ranks - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)

    def ancestry_auc(self, do_rows: list[list[float]], base_rows: list[list[float]],
                     target_idx: int, seed: int, train_frac: float = 0.6,
                     permute: bool = False, exclude: tuple = ()) -> float:
        """Held-out AUC of distinguishing do(X) from baseline using features except target AND
        the excluded set (v2: exclude the intervened node's own clamped value — see prereg §7).
        permute=True shuffles the do/base labels within train (confound negative control)."""
        drop = {target_idx, *exclude}
        feat_idx = [j for j in range(len(do_rows[0])) if j not in drop]
        rows = [(r, 1) for r in do_rows] + [(r, 0) for r in base_rows]
        random.Random(seed).shuffle(rows)
        cut = int(len(rows) * train_frac)
        train, test = rows[:cut], rows[cut:]
        if len(train) < 8 or len(test) < 4:
            return 0.5
        cols = [[r[j] for r, _ in train] for j in feat_idx]
        std, means, sds = _standardize(cols)
        ytr = [lab for _, lab in train]
        if permute:
            random.Random(seed + 1).shuffle(ytr)
        w = self._fit_logistic(std, ytr)
        te_scores, te_labels = [], []
        for r, lab in test:
            x = [(r[feat_idx[k]] - means[k]) / sds[k] for k in range(len(feat_idx))]
            te_scores.append(self._predict(w, x))
            te_labels.append(lab)
        return self._auc(te_scores, te_labels)

    def transfer_auc(self, train_do: list[list[float]], train_base: list[list[float]],
                     test_do: list[list[float]], test_base: list[list[float]],
                     target_idx: int, seed: int, exclude: tuple = (),
                     permute: bool = False) -> float:
        """CWM-LEARN-2: fit the mechanism-signature classifier on the TRAIN regime and score the
        TEST regime WITHOUT refit (standardize on train). Features exclude the target and the
        `exclude` set (the intervened node's own clamped value — the S1b v2 leak fix). permute=True
        shuffles train labels (confound negative control). Returns held-out TEST AUC."""
        drop = {target_idx, *exclude}
        feat = [j for j in range(len(train_do[0])) if j not in drop]
        tr = [(r, 1) for r in train_do] + [(r, 0) for r in train_base]
        random.Random(seed).shuffle(tr)
        if len(tr) < 8:
            return 0.5
        cols = [[r[j] for r, _ in tr] for j in feat]
        std, means, sds = _standardize(cols)
        ytr = [lab for _, lab in tr]
        if permute:
            random.Random(seed + 1).shuffle(ytr)
        w = self._fit_logistic(std, ytr)
        te = [(r, 1) for r in test_do] + [(r, 0) for r in test_base]
        scores = [self._predict(w, [(r[feat[k]] - means[k]) / sds[k] for k in range(len(feat))])
                  for r, _ in te]
        labels = [lab for _, lab in te]
        return self._auc(scores, labels)

    def invariant_predict_auc(self, train_envs, test_rows, test_labels, seed,
                              mode="invariant", permute=False, return_kept=False):
        """CWM-LEARN-2 environment-axis gate (invariant prediction under distribution shift, RR-0039 §5).

        Fit on MULTIPLE training environments (each a (rows, labels) pair that shares the invariant
        causal mechanism but differs in a sign-flipping spurious proxy), then predict the held-out TEST
        environment's labels WITHOUT refit. Returns the held-out TEST AUC.

        mode:
          "invariant" — ICP-lite: fit a per-env logistic, KEEP only features whose coefficient sign is
                        consistent across ALL training envs (the spurious proxy flips sign and is dropped;
                        the invariant causal features survive), then refit pooled on the kept features.
                        This is the CAUSAL arm — the ONLY difference from the baselines is the filter.
          "pooled"    — multivariate statistical baseline: pool all envs, fit on ALL features (keeps the
                        spurious proxy, which negative-transfers when its coupling flips OOD).
          "marginal"  — marginal statistical baseline: the single feature with the largest pooled
                        |standardized class mean-shift|, 1-feature logistic (keys hardest on the proxy).

        permute=True shuffles labels within every env (confound negative control: all arms -> chance).
        return_kept=True (invariant mode) also returns the list of kept feature indices (for the capacity
        positive control: confirm the invariant causal features ARE kept)."""
        if not train_envs:
            return (0.5, []) if return_kept else 0.5
        n_cols = len(train_envs[0][0][0])
        feat = list(range(n_cols))

        pooled_rows = [r for rows, _ in train_envs for r in rows]
        cols = [[r[j] for r in pooled_rows] for j in feat]
        _, means, sds = _standardize(cols)

        def std_sub(r, sub, keep_idx):
            return [(r[sub[k]] - means[keep_idx[k]]) / sds[keep_idx[k]] for k in range(len(sub))]

        def std_row(r):
            return [(r[feat[k]] - means[k]) / sds[k] for k in range(len(feat))]

        def pooled_xy(salt):
            allrows = [(r, lab) for rows, labs in train_envs for r, lab in zip(rows, labs)]
            random.Random(seed + salt).shuffle(allrows)
            y = [lab for _, lab in allrows]
            if permute:
                random.Random(seed + 8000 + salt).shuffle(y)
            return allrows, y

        if mode == "invariant":
            signs = []
            for i, (rows, labs) in enumerate(train_envs):
                pairs = list(zip(rows, labs))
                random.Random(seed + i + 1).shuffle(pairs)
                X = [std_row(r) for r, _ in pairs]
                y = [lab for _, lab in pairs]
                if permute:
                    random.Random(seed + 900 + i).shuffle(y)
                w = self._fit_logistic(X, y)
                signs.append([1 if w[k + 1] > 0 else (-1 if w[k + 1] < 0 else 0) for k in range(len(feat))])
            keep = [k for k in range(len(feat))
                    if all(signs[e][k] == signs[0][k] and signs[e][k] != 0 for e in range(len(signs)))]
            if not keep:
                return (0.5, []) if return_kept else 0.5
            sub = [feat[k] for k in keep]
            allrows, yp = pooled_xy(salt=7)
            Xp = [std_sub(r, sub, keep) for r, _ in allrows]
            w = self._fit_logistic(Xp, yp)
            scores = [self._predict(w, std_sub(r, sub, keep)) for r in test_rows]
            auc = self._auc(scores, list(test_labels))
            return (auc, sub) if return_kept else auc

        allrows, yp = pooled_xy(salt=7)
        if mode == "marginal":
            best_k, best_shift = 0, -1.0
            for k in range(len(feat)):
                # select on the SAME labels used to fit (yp) so the permute control is leak-free
                a = [std_row(r)[k] for (r, _), lab in zip(allrows, yp) if lab == 1]
                b = [std_row(r)[k] for (r, _), lab in zip(allrows, yp) if lab == 0]
                if not a or not b:
                    continue
                shift = abs(sum(a) / len(a) - sum(b) / len(b))
                if shift > best_shift:
                    best_shift, best_k = shift, k
            Xp = [[std_row(r)[best_k]] for r, _ in allrows]
            w = self._fit_logistic(Xp, yp)
            scores = [self._predict(w, [std_row(r)[best_k]]) for r in test_rows]
            return self._auc(scores, list(test_labels))

        # mode == "pooled"
        Xp = [std_row(r) for r, _ in allrows]
        w = self._fit_logistic(Xp, yp)
        scores = [self._predict(w, std_row(r)) for r in test_rows]
        return self._auc(scores, list(test_labels))
