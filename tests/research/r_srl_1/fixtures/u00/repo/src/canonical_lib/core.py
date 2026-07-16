"""Core helpers for the canonical library fixture."""

from __future__ import annotations

import json
from typing import Any


def greet(name: str, greeting: str = "Hello") -> str:
    """Return a simple greeting string."""
    return f"{greeting}, {name}!"


def calculate(a: float, b: float, op: str = "add") -> float:
    """Perform a basic arithmetic operation on two numbers."""
    if op == "add":
        return a + b
    if op == "subtract":
        return a - b
    if op == "multiply":
        return a * b
    if op == "divide":
        if b == 0:
            raise ValueError("division by zero")
        return a / b
    raise ValueError(f"unsupported operation: {op}")


def parse_config(raw: str) -> dict[str, Any]:
    """Parse a JSON configuration string into a dictionary."""
    data: dict[str, Any] = json.loads(raw)
    return data
