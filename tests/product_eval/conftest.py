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


# --------------------------------------------------------------------------- #
# Quarantine mechanism (shard D, 2026-09-19)
# --------------------------------------------------------------------------- #
# A `quarantine(reason=...)` mark is the ONLY sanctioned way to suppress an offline
# deterministic test in this suite. It is converted here into a skip that always carries
# its reason, so:
#   * there is no silent `@pytest.mark.skip` (a reason is mandatory),
#   * no test is deleted (the mark sits on the test and runs when the asset lands),
#   * every quarantined item appears, with its reason, in `-rs` and in the report below.
# Lift a quarantine only when the named asset is available and the test re-confirms green
# in this repo (not just on the author's machine).
def pytest_collection_modifyitems(config, items):  # type: ignore[no-untyped-def]
    """Convert every quarantined item into a reason-bearing skip.

    Two sources, one rule:
      * an in-file ``@pytest.mark.quarantine(reason=...)`` on the item itself;
      * the central manifest ``_quarantine.QUARANTINE_BUCKETS`` (exact nodeids).

    Both require a non-empty reason. A reasonless quarantine is a silent skip and is
    rejected here rather than silently suppressing a test. The resulting skips print their
    reason under ``-rs`` and are tallied below.
    """
    from tests.product_eval._quarantine import QUARANTINE_BUCKETS

    manifest = {}
    for bucket in QUARANTINE_BUCKETS.values():
        reason = bucket["reason"]
        for nodeid in bucket["nodeids"]:
            manifest[nodeid] = reason

    quarantined: list[str] = []
    for item in items:
        reasons: list[str] = []
        for mark in item.iter_markers(name="quarantine"):
            reason = mark.kwargs.get("reason")
            if not reason:
                raise RuntimeError(
                    f"quarantine mark on {item.nodeid!r} must carry a reason= explaining "
                    "what asset is missing, why it cannot run in this repo, and when it "
                    "can be lifted. A reasonless quarantine is a silent skip and is rejected."
                )
            reasons.append(reason)
        # Central manifest match (exact nodeid).
        if item.nodeid in manifest:
            reasons.append(manifest[item.nodeid])
        for reason in reasons:
            item.add_marker(pytest.mark.skip(reason=f"[quarantine] {reason}"))
        if reasons:
            quarantined.append(f"{item.nodeid} :: {reasons[0]}")
    if quarantined:
        print(
            "\n".join(
                ["", "=== QUARANTINED product_eval tests (asset-gated, not silent skips) ==="]
                + [f"  - {line}" for line in quarantined]
            )
        )
