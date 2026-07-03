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
