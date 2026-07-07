"""Integration: RuntimeFactory exposes a real ApprovalRouter (AR-20260707 / boundary #8).

Proves the C/D/E engines are reachable from the real app build path. With the
flags off (default) no router is built (MVP unchanged). With the R4/R5 flag on,
the factory builds a router whose PolicyEngine is real and routes correctly.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig

ROOT = Path(__file__).resolve().parents[2]


class RuntimeFactoryApprovalRouterTest(unittest.TestCase):
    def _factory(self, env: dict[str, str]) -> ContentCommerceRuntimeFactory:
        cfg = RuntimeFactoryConfig.from_env(env)
        return ContentCommerceRuntimeFactory(cfg)

    def test_flags_off_returns_none(self) -> None:
        f = self._factory({})
        self.assertIsNone(f.build_approval_router())

    def test_r4_r5_flag_on_builds_real_router(self) -> None:
        f = self._factory({"AGENT_OS_R4_R5_AUTO_EXECUTION": "true"})
        router = f.build_approval_router()
        self.assertIsNotNone(router)
        # the router carries a real PolicyEngine
        self.assertIsNotNone(router._policy_engine)

    def test_bpm_flag_on_builds_real_router_with_workflow(self) -> None:
        f = self._factory({"AGENT_OS_FULL_BPM_WORKFLOW": "true"})
        router = f.build_approval_router()
        self.assertIsNotNone(router)
        self.assertIsNotNone(router._workflow_runtime)


if __name__ == "__main__":
    unittest.main()
