from __future__ import annotations

from pathlib import Path

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_ignore_collect(collection_path: Path) -> bool | None:
    """Prevent pytest from collecting fixture repository tests as suite tests."""
    return "fixtures" in collection_path.parts
