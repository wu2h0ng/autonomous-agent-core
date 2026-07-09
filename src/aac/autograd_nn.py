"""Autograd Engine + MLP — pure Python, zero external dependencies.

Self-developed differentiable programming substrate for the IGI organ side.
Per RR-0043 Ruler A: gradient learning is ARCHITECTURE-ALLOWED on the organ side.
Per Hard Boundary #7: 100% self-developed, no torch/tensorflow/jax.

Design: scalar-valued autograd (like micrograd) with a tape-based backward pass.
Sufficient for n ≤ 50 nodes and particle-based inference (CWM mechanisms).

Architecture:
  Value: scalar with gradient tracking, ops: + - * / tanh sin exp log pow relu sigmoid
  MLP: multi-layer perceptron with configurable hidden layers
  SGD: stochastic gradient descent with optional momentum
  NNMechanismOrgan: CWM organ wrapping MLP for nonlinear mechanism fitting
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable


class Value:
    """Scalar value with automatic differentiation.

    Operations build a computational graph; backward() propagates gradients
    from output to inputs via topological sort of the graph.
    """

    def __init__(self, data: float, _children: tuple = (), _op: str = ""):
        self.data = data
        self.grad = 0.0
        self._backward = lambda: None
        self._prev = set(_children)
        self._op = _op

    def __add__(self, other):
        other = other if isinstance(other, Value) else Value(other)
        out = Value(self.data + other.data, (self, other), "+")

        def _backward():
            self.grad += out.grad
            other.grad += out.grad
        out._backward = _backward
        return out

    def __radd__(self, other):
        return self + other

    def __neg__(self):
        return self * -1

    def __sub__(self, other):
        return self + (-other)

    def __rsub__(self, other):
        return other + (-self)

    def __mul__(self, other):
        other = other if isinstance(other, Value) else Value(other)
        out = Value(self.data * other.data, (self, other), "*")

        def _backward():
            self.grad += other.data * out.grad
            other.grad += self.data * out.grad
        out._backward = _backward
        return out

    def __rmul__(self, other):
        return self * other

    def __truediv__(self, other):
        return self * other ** -1

    def __rtruediv__(self, other):
        return other * self ** -1

    def __pow__(self, other):
        assert isinstance(other, (int, float)), "only int/float powers supported"
        out = Value(self.data ** other, (self,), f"**{other}")

        def _backward():
            self.grad += (other * self.data ** (other - 1)) * out.grad
        out._backward = _backward
        return out

    def tanh(self):
        t = math.tanh(self.data)
        out = Value(t, (self,), "tanh")

        def _backward():
            self.grad += (1 - t ** 2) * out.grad
        out._backward = _backward
        return out

    def sin(self):
        out = Value(math.sin(self.data), (self,), "sin")

        def _backward():
            self.grad += math.cos(self.data) * out.grad
        out._backward = _backward
        return out

    def exp(self):
        out = Value(math.exp(self.data), (self,), "exp")

        def _backward():
            self.grad += out.data * out.grad
        out._backward = _backward
        return out

    def log(self):
        v = max(self.data, 1e-12)
        out = Value(math.log(v), (self,), "log")

        def _backward():
            self.grad += (1.0 / v) * out.grad
        out._backward = _backward
        return out

    def relu(self):
        out = Value(self.data if self.data > 0 else 0, (self,), "relu")

        def _backward():
            self.grad += (1.0 if self.data > 0 else 0.0) * out.grad
        out._backward = _backward
        return out

    def sigmoid(self):
        s = 1.0 / (1.0 + math.exp(-self.data))
        out = Value(s, (self,), "sigmoid")

        def _backward():
            self.grad += s * (1 - s) * out.grad
        out._backward = _backward
        return out

    def backward(self):
        topo = []
        visited = set()

        def build_topo(v):
            if v not in visited:
                visited.add(v)
                for child in v._prev:
                    build_topo(child)
                topo.append(v)
        build_topo(self)
        self.grad = 1.0
        for v in reversed(topo):
            v._backward()


class MLP:
    """Multi-layer perceptron with configurable architecture.

    Args:
        n_in: input dimension.
        n_out: output dimension (typically 1 for regression).
        hidden_dims: list of hidden layer sizes.
        activation: "tanh" (default), "relu", "sigmoid", "sin".
        seed: RNG seed for weight initialization.
    """

    def __init__(self, n_in: int, n_out: int, hidden_dims: list[int] | None = None,
                 activation: str = "tanh", seed: int = 0):
        self.n_in = n_in
        self.n_out = n_out
        self.hidden_dims = hidden_dims or [n_in * 2]
        self.activation = activation
        self.rng = random.Random(seed)
        self.layers: list[list[list[Value]]] = []
        self.biases: list[list[Value]] = []
        dims = [n_in] + self.hidden_dims + [n_out]
        for i in range(len(dims) - 1):
            fan_in = dims[i]
            fan_out = dims[i + 1]
            bound = math.sqrt(2.0 / max(fan_in, 1))
            weights = []
            for _ in range(fan_out):
                row = [Value(self.rng.uniform(-bound, bound)) for _ in range(fan_in)]
                weights.append(row)
            self.layers.append(weights)
            bias_row = [Value(self.rng.uniform(-bound, bound)) for _ in range(fan_out)]
            self.biases.append(bias_row)

    def _activate(self, x: Value) -> Value:
        if self.activation == "relu":
            return x.relu()
        if self.activation == "sigmoid":
            return x.sigmoid()
        if self.activation == "sin":
            return x.sin()
        return x.tanh()

    def forward(self, inputs: list[float]) -> Value:
        """Forward pass: inputs → hidden layers → output."""
        activations = [Value(v) for v in inputs]
        for layer_idx in range(len(self.layers)):
            weights = self.layers[layer_idx]
            bias = self.biases[layer_idx]
            next_activations = []
            for neuron_idx in range(len(weights)):
                z = bias[neuron_idx]
                for inp_idx in range(len(activations)):
                    z = z + weights[neuron_idx][inp_idx] * activations[inp_idx]
                if layer_idx < len(self.layers) - 1:
                    next_activations.append(self._activate(z))
                else:
                    next_activations.append(z)
            activations = next_activations
        return activations[0] if len(activations) == 1 else activations[0]

    def parameters(self) -> list[Value]:
        params = []
        for w in self.layers:
            for row in w:
                params.extend(row)
        for b in self.biases:
            params.extend(b)
        return params

    def zero_grad(self):
        for p in self.parameters():
            p.grad = 0.0

    def save(self, path: str):
        import json
        data = {
            "n_in": self.n_in, "n_out": self.n_out,
            "hidden_dims": self.hidden_dims, "activation": self.activation,
            "weights": [[[w.data for w in row] for row in layer] for layer in self.layers],
            "biases": [[b.data for b in bias] for bias in self.biases],
        }
        with open(path, "w") as f:
            json.dump(data, f)

    @classmethod
    def load(cls, path: str) -> MLP:
        import json
        with open(path) as f:
            data = json.load(f)
        mlp = cls.__new__(cls)
        mlp.n_in = data["n_in"]; mlp.n_out = data["n_out"]
        mlp.hidden_dims = data["hidden_dims"]; mlp.activation = data["activation"]
        mlp.rng = random.Random(0)
        mlp.layers = [[[Value(w) for w in row] for row in layer] for layer in data["weights"]]
        mlp.biases = [[Value(b) for b in bias] for bias in data["biases"]]
        return mlp


class SGD:
    """Stochastic Gradient Descent with optional momentum."""

    def __init__(self, params: list[Value], lr: float = 0.01, momentum: float = 0.0):
        self.params = params
        self.lr = lr
        self.momentum = momentum
        self._velocity = [0.0] * len(params)

    def step(self):
        for i, p in enumerate(self.params):
            self._velocity[i] = self.momentum * self._velocity[i] + self.lr * p.grad
            p.data -= self._velocity[i]

    def zero_grad(self):
        for p in self.params:
            p.grad = 0.0


def fit_mlp(
    X: list[list[float]], y: list[float],
    hidden_dims: list[int] | None = None,
    activation: str = "tanh",
    lr: float = 0.01,
    n_epochs: int = 200,
    momentum: float = 0.9,
    seed: int = 0,
) -> MLP:
    """Fit an MLP to data using SGD + MSE loss.

    Args:
        X: design matrix [n_obs][n_features].
        y: target values [n_obs].
        hidden_dims: hidden layer sizes (default: [n_features * 2]).
        activation: "tanh", "relu", "sigmoid".
        lr: learning rate.
        n_epochs: training epochs.
        momentum: SGD momentum.
        seed: RNG seed.

    Returns:
        Trained MLP model.
    """
    n_in = len(X[0]) if X else 1
    mlp = MLP(n_in, 1, hidden_dims or [n_in * 2], activation, seed)
    opt = SGD(mlp.parameters(), lr=lr, momentum=momentum)
    for epoch in range(n_epochs):
        total_loss = 0.0
        for t in range(len(X)):
            pred = mlp.forward(X[t])
            loss = (pred - Value(y[t])) ** 2
            total_loss += loss.data
            opt.zero_grad()
            loss.backward()
            opt.step()
    return mlp
