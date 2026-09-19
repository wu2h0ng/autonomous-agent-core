"""Keep the operator's persisted provider out of every eval run.

``AgentOSApplication.__init__`` re-installs a previously configured provider
from ``~/.agent-os/provider.json`` when no provider comes from the environment,
and that re-installation performs a live connection test (``configure_provider``
→ ``provider.complete``). An eval that constructs the application therefore
reaches into the operator's own state and can issue a real, billable provider
call before the eval has run a single task — which is exactly what happened
once, against this repository's default state directory.

``isolated_provider_config`` removes that path: ``AGENT_OS_PROVIDER_CONFIG`` is
pointed at a file inside the eval's own workspace that never exists, so
``load_provider_config()`` returns None and the application stays on its
in-process deterministic provider. The eval therefore starts from its own
workspace and nothing else.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

PROVIDER_CONFIG_ENV = "AGENT_OS_PROVIDER_CONFIG"


class _ConfiguredApplication(Protocol):
    @property
    def provider_configured(self) -> bool: ...


class ProviderIsolationError(Exception):
    """Raised when a run would have used a provider other than its own."""


@contextmanager
def isolated_provider_config(workspace_root: Path) -> Iterator[None]:
    """Point the persisted-provider lookup inside `workspace_root` for the block."""
    previous = os.environ.get(PROVIDER_CONFIG_ENV)
    os.environ[PROVIDER_CONFIG_ENV] = str(workspace_root / "no-provider.json")
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(PROVIDER_CONFIG_ENV, None)
        else:
            os.environ[PROVIDER_CONFIG_ENV] = previous


def assert_env_provider_absent(app: _ConfiguredApplication, *, arm: str) -> None:
    """Fail closed when an offline arm finds a provider configured from the env.

    With ``isolated_provider_config`` active this can only mean the ambient
    environment (``AGENT_OS_PROVIDER_*``, ``OPENAI_*``, a profile's
    ``<PROFILE>_BASE_URL``/``_API_KEY``) supplies one. An offline arm must not
    run then: its provider is the plan, and a live connection test would have
    happened behind its back.
    """
    if app.provider_configured:
        raise ProviderIsolationError(
            f"the {arm} arm refuses to run with a provider configured from the "
            "environment: unset AGENT_OS_PROVIDER_* / OPENAI_* / <PROFILE>_* "
            "provider variables for an offline run"
        )
