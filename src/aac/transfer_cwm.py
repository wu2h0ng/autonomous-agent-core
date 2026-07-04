"""TransferCWM — CWM-LEARN-4 LEARNED invariant-representation mechanism (RR-0039 gate 4, pure stdlib).

A 2-layer tanh MLP trained with a V-REx invariance penalty (Krueger et al.): the total loss is the mean
per-environment risk PLUS lam * variance-across-environments of the per-env risk, which pushes the LEARNED
representation toward one on which the SAME classifier is (near-)optimal in every training environment — i.e.
it should discard family-specific nuisance and keep the invariant mechanism, and so transfer to a held-out
family. lam=0 recovers the capacity-matched ERM baseline (same architecture, no invariance penalty).

V-REx is chosen over IRMv1 because its penalty is a smooth function of scalar per-env risks (no gradient-of-
gradient), so it is numerically stable in pure stdlib and a NULL is informative (not an IRM-optimisation
artifact). The representation is LEARNED (not a supplied basis) and the invariance criterion is a TRAINING
penalty, not hidden-unit SELECTION — so it avoids the permutation/sign identifiability fragility that made
LEARN-3 demote its MLP arm. Fit OFFLINE, consumed verify-only (scalar AUC out; never a control path).
"""
from __future__ import annotations

import math
import random

from aac.learned_cwm import LearnedCWM

_auc = LearnedCWM._auc   # reuse the rank-based AUC (staticmethod -> plain function)


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


class TransferMLP:
    """2-layer tanh MLP; trained by V-REx (lam>0) or ERM (lam=0). Pure stdlib, full-batch per environment."""

    def __init__(self, n_in: int, n_hid: int = 8, lr: float = 0.2, epochs: int = 250,
                 l2: float = 1e-4, lam: float = 0.0, seed: int = 0):
        r = random.Random(f"T4-mlp|{seed}|{n_in}|{n_hid}")
        self.W1 = [[r.gauss(0, 0.7) for _ in range(n_in)] for _ in range(n_hid)]
        self.b1 = [0.0] * n_hid
        self.W2 = [r.gauss(0, 0.7) for _ in range(n_hid)]
        self.b2 = 0.0
        self.nh, self.ni, self.lr, self.epochs, self.l2, self.lam = n_hid, n_in, lr, epochs, l2, lam

    def _logit(self, x):
        h = [math.tanh(sum(self.W1[j][k] * x[k] for k in range(self.ni)) + self.b1[j]) for j in range(self.nh)]
        return sum(self.W2[j] * h[j] for j in range(self.nh)) + self.b2, h

    def prob(self, x):
        return _sigmoid(self._logit(x)[0])

    def fit(self, envs):
        """envs: list of (X, y). V-REx: total = mean_e risk_e + lam*Var_e(risk_e); env gradient weight is
        1/E + lam*(2/E)(risk_e - mean_risk) (the exact gradient of that objective w.r.t. each env's risk)."""
        E = len(envs)
        for _ in range(self.epochs):
            risks = []
            for (X, Y) in envs:
                s = 0.0
                for x, y in zip(X, Y):
                    p = self.prob(x)
                    s += -(y * math.log(p + 1e-9) + (1 - y) * math.log(1 - p + 1e-9))
                risks.append(s / len(X))
            mean_r = sum(risks) / E
            gW1 = [[0.0] * self.ni for _ in range(self.nh)]
            gb1 = [0.0] * self.nh
            gW2 = [0.0] * self.nh
            gb2 = 0.0
            for e, (X, Y) in enumerate(envs):
                w_env = (1.0 / E) + self.lam * (2.0 / E) * (risks[e] - mean_r)
                for x, y in zip(X, Y):
                    z, h = self._logit(x)
                    err = (_sigmoid(z) - y) / len(X) * w_env
                    gb2 += err
                    for j in range(self.nh):
                        gW2[j] += err * h[j]
                        dh = err * self.W2[j] * (1 - h[j] * h[j])
                        for k in range(self.ni):
                            gW1[j][k] += dh * x[k]
                        gb1[j] += dh
            self.b2 -= self.lr * gb2
            for j in range(self.nh):
                self.W2[j] -= self.lr * (gW2[j] + self.l2 * self.W2[j])
                for k in range(self.ni):
                    self.W1[j][k] -= self.lr * (gW1[j][k] + self.l2 * self.W1[j][k])
                self.b1[j] -= self.lr * gb1[j]
        return self


def mlp_transfer_auc(train_envs, test_rows, test_labels, lam, seed, n_hid=8, epochs=250, permute=False):
    """Train a TransferMLP (V-REx if lam>0, ERM if lam=0) on the training family, score the held-out family.
    permute=True shuffles labels within every training env (confound negative control)."""
    envs = train_envs
    if permute:
        envs = []
        for i, (X, Y) in enumerate(train_envs):
            Yp = list(Y)
            random.Random(f"T4-perm|{seed}|{i}").shuffle(Yp)
            envs.append((X, Yp))
    n_in = len(train_envs[0][0][0])
    m = TransferMLP(n_in, n_hid=n_hid, epochs=epochs, lam=lam, seed=seed).fit(envs)
    return _auc([m.prob(x) for x in test_rows], list(test_labels))
