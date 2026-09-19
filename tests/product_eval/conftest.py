"""Session isolation for the product-evaluation suite.

The frozen SPINE arms take their provider configuration from the process
environment, because that is where ``AgentOSApplication`` reads it. A test (or a
harness entry point it drives) that writes those variables and does not undo the
write leaves every later test in the same pytest process pointed at a loopback
endpoint that has already been closed -- so the suite's result depends on the
order the files happen to be collected in.

The scoped helper ``provider_environment`` is the fix; this fixture is the
backstop that keeps the guarantee true for callers that have not been converted
yet, and it is why a new leak cannot silently change another test's meaning.
The whole environment is restored rather than only the provider variables: the
provider surface is not the only thing a test can write, and a leak of anything
else is the same defect. Measured 2026-09-18 against the suite with this fixture
in place and without it: identical tallies, so the restore changes no legitimate
cross-test dependency.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _restore_process_environment() -> None:
    snapshot = dict(os.environ)
    try:
        yield
    finally:
        for name in [name for name in os.environ if name not in snapshot]:
            del os.environ[name]
        os.environ.update(snapshot)
