from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_pyproject(path: Path) -> dict[str, Any]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_root_distribution_does_not_co_ship_product_packages() -> None:
    config = _load_pyproject(REPO_ROOT / "pyproject.toml")

    assert config["tool"]["setuptools"]["packages"]["find"]["where"] == ["src", "."]
    assert config["tool"]["setuptools"]["packages"]["find"]["include"] == [
        "aac*",
        "envs*",
        "apps*",
        "domain_packs*",
    ]
    excluded = config["tool"]["setuptools"]["packages"]["find"]["exclude"]
    assert "packages*" in excluded


def test_contracts_distribution_declares_pydantic_runtime_dependency() -> None:
    config = _load_pyproject(REPO_ROOT / "packages" / "contracts" / "pyproject.toml")

    assert config["project"]["name"] == "agent-os-contracts"
    assert any(
        dependency.startswith("pydantic")
        for dependency in config["project"]["dependencies"]
    )
    assert config["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]


def test_core_distribution_declares_contracts_runtime_dependency() -> None:
    config = _load_pyproject(REPO_ROOT / "packages" / "os_core" / "pyproject.toml")

    assert config["project"]["name"] == "agent-os-core"
    assert "agent-os-contracts==0.1.0" in config["project"]["dependencies"]
    assert config["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]
