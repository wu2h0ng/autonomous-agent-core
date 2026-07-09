"""Tests for the self-developed autograd engine and MLP."""
from __future__ import annotations

import math
import random
import unittest

from aac.autograd_nn import Value, MLP, SGD, fit_mlp


class TestValueAutograd(unittest.TestCase):
    def test_add_gradient(self):
        a = Value(2); b = Value(3); c = a + b; c.backward()
        self.assertEqual(a.grad, 1); self.assertEqual(b.grad, 1)

    def test_mul_gradient(self):
        a = Value(3); b = Value(4); c = a * b; c.backward()
        self.assertEqual(a.grad, 4); self.assertEqual(b.grad, 3)

    def test_composite_gradient(self):
        a = Value(2); b = Value(3); c = a * b + a; c.backward()
        self.assertEqual(a.grad, 4); self.assertEqual(b.grad, 2)

    def test_tanh_gradient(self):
        x = Value(0.5); y = x.tanh(); y.backward()
        self.assertAlmostEqual(x.grad, 1 - math.tanh(0.5) ** 2)

    def test_relu_positive(self):
        x = Value(2); y = x.relu(); y.backward()
        self.assertEqual(x.grad, 1)

    def test_relu_negative(self):
        x = Value(-1); y = x.relu(); y.backward()
        self.assertEqual(x.grad, 0)

    def test_pow_gradient(self):
        x = Value(3); y = x ** 2; y.backward()
        self.assertEqual(x.grad, 6)

    def test_division(self):
        a = Value(6); b = Value(2); c = a / b; c.backward()
        self.assertAlmostEqual(a.grad, 0.5); self.assertAlmostEqual(b.grad, -1.5)

    def test_chain_rule(self):
        a = Value(2); b = a * a + a.tanh(); b.backward()
        expected = 4 + (1 - math.tanh(2)**2)
        self.assertAlmostEqual(a.grad, expected)


class TestMLP(unittest.TestCase):
    def test_forward_produces_scalar(self):
        mlp = MLP(3, 1, [6], "tanh", seed=0)
        out = mlp.forward([0.5, -0.3, 1.0])
        self.assertIsInstance(out, Value)
        self.assertIsInstance(out.data, float)

    def test_zero_grad_clears(self):
        mlp = MLP(2, 1, [4], seed=1)
        out = mlp.forward([1.0, -1.0])
        out.backward()
        for p in mlp.parameters():
            self.assertNotEqual(p.grad, 0)
        mlp.zero_grad()
        for p in mlp.parameters():
            self.assertEqual(p.grad, 0)

    def test_parameters_count(self):
        mlp = MLP(3, 1, [5, 4])
        n_params = len(mlp.parameters())
        expected = (3 * 5 + 5) + (5 * 4 + 4) + (4 * 1 + 1)
        self.assertEqual(n_params, expected)

    def test_train_on_xor(self):
        rng = random.Random(42)
        X = []; y = []
        for _ in range(100):
            a = rng.choice([0.0, 1.0]); b = rng.choice([0.0, 1.0])
            X.append([a, b]); y.append(1.0 if a != b else 0.0)
        model = fit_mlp(X, y, [8, 4], "tanh", 0.03, 300, 0.9, seed=0)
        correct = 0
        for t in range(len(X)):
            pred = model.forward(X[t]).data
            label = 1 if pred > 0.5 else 0
            if label == y[t]: correct += 1
        self.assertGreater(correct / len(X), 0.85)


class TestSGD(unittest.TestCase):
    def test_sgd_reduces_loss(self):
        rng = random.Random(0)
        X = [[rng.uniform(-1, 1)] for _ in range(80)]
        y = [2.0 * x[0] + 0.5 for x in X]
        mlp = MLP(1, 1, [4], "tanh", seed=0)
        opt = SGD(mlp.parameters(), lr=0.02, momentum=0.9)
        losses = []
        for _ in range(200):
            total = 0.0
            for t in range(len(X)):
                pred = mlp.forward(X[t])
                loss = (pred - Value(y[t])) ** 2
                total += loss.data
                opt.zero_grad(); loss.backward(); opt.step()
            losses.append(total / len(X))
        self.assertLess(losses[-1], losses[0] * 0.3)

    def test_momentum_effect(self):
        rng = random.Random(1)
        X = [[rng.uniform(-1, 1)] for _ in range(50)]
        y = [3.0 * x[0] - 1.0 for x in X]

        def train_with_momentum(mom):
            mlp = MLP(1, 1, [4], seed=0)
            opt = SGD(mlp.parameters(), lr=0.01, momentum=mom)
            for _ in range(100):
                for t in range(len(X)):
                    pred = mlp.forward(X[t]); loss = (pred - Value(y[t])) ** 2
                    opt.zero_grad(); loss.backward(); opt.step()
            return mlp.forward([0.5]).data

        with_mom = train_with_momentum(0.9)
        without_mom = train_with_momentum(0.0)
        self.assertAlmostEqual(with_mom, 0.5, delta=0.5)
        self.assertAlmostEqual(without_mom, 0.5, delta=1.0)


if __name__ == "__main__":
    unittest.main()
