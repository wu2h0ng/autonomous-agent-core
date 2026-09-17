"""One wall-clock anchor shared by the situated fixtures.

Provider credentials are validated against the real clock (``agent_os_core.provider``),
so a frozen anchor rots: the 2026-07-17 literal plus a 30-day credential window started
failing on 2026-08-16. Situated fixtures import ``NOW`` from here instead of each
declaring their own literal.
"""

from __future__ import annotations

from datetime import datetime, timezone

NOW = datetime.now(timezone.utc).replace(microsecond=0)
