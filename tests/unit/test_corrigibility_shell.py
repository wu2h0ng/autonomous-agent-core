"""P5.2a corrigibility shell guards.

The operator holds CorrigibilityShell; the runtime receives only ShellView. A pause
must block the Trusted Loop and land on the tamper-evident audit chain.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (
    ROOT / "packages" / "contracts" / "src",
    ROOT / "packages" / "os_core" / "src",
    ROOT / "action_connectors",
    ROOT / "apps" / "api_server" / "src",
):
    sys.path.insert(0, str(_p))

from agent_os_contracts import (  # noqa: E402
    ActionConnectorContract,
    BlockCode,
    MetricContract,
    ProviderContract,
    ProviderKind,
    SQLTemplate,
)
from agent_os_core import (  # noqa: E402
    CorrigibilityShell,
    ProviderRegistry,
    SemanticRegistry,
    TrustedLoopRuntime,
)
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402


def _connector_registry() -> ActionConnectorRegistry:
    registry = ActionConnectorRegistry()
    registry.register(
        ManualReviewConnector(),
        ActionConnectorContract(
            connector_name="manual_review",
            display_name="Manual Review",
            supported_action_types=("propose", "execute"),
            supports_snapshot=False,
            supports_rollback=False,
            compensating_action_description=None,
            risk_ceiling="R5",
            owner="system",
        ),
    )
    return registry


def _runtime(shell: CorrigibilityShell | None = None) -> TrustedLoopRuntime:
    metric = MetricContract(
        metric_name="gmv",
        display_name="GMV",
        definition="Gross merchandise value.",
        owner="revenue_ops",
        unit="CNY",
        allowed_schemas=("sales",),
    )
    template = SQLTemplate(
        template_id="gmv_daily",
        metric_name="gmv",
        sql="select 1 from sales.orders where order_date >= :start_date "
        "and order_date < :end_date limit :limit",
        required_parameters=("start_date", "end_date", "limit"),
    )
    return TrustedLoopRuntime(
        metric_contract=metric,
        sql_template=template,
        query_executor=StaticQueryExecutor([{"order_date": "2026-05-31", "gmv": 1.0}]),
        semantic_registry=SemanticRegistry(metric_contracts=(metric,)),
        provider_registry=ProviderRegistry(
            (
                ProviderContract(
                    provider_id="provider-sales",
                    kind=ProviderKind.WAREHOUSE,
                    name="sales",
                    owner="revenue_ops",
                    allowed_schemas=("sales",),
                ),
            )
        ),
        connector_registry=_connector_registry(),
        shell_view=shell.view() if shell is not None else None,
    )


class TestCorrigibilityShell(unittest.TestCase):
    def test_view_has_no_operator_surface(self) -> None:
        shell = CorrigibilityShell()
        view = shell.view()
        self.assertFalse(hasattr(view, "op_pause"))
        self.assertFalse(hasattr(view, "op_resume"))
        with self.assertRaises(AttributeError):
            view._paused = False  # type: ignore[attr-defined]

    def test_audit_chain_detects_tampering(self) -> None:
        shell = CorrigibilityShell()
        shell.observe({"event": "one"})
        shell.op_pause()
        self.assertTrue(shell.audit.verify())

        entry = shell.audit._entries[0]  # deliberate adversarial mutation for the guard
        entry.payload["event"] = "edited"
        self.assertFalse(shell.audit.verify())

    def test_paused_shell_blocks_runtime_and_audits_refusal(self) -> None:
        shell = CorrigibilityShell()
        runtime = _runtime(shell)
        shell.op_pause()

        outcome = runtime.evaluate(
            "GMV", {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}
        )

        self.assertTrue(outcome.blocked)
        self.assertEqual(outcome.block.code, BlockCode.PAUSED)
        self.assertEqual(outcome.block.stage, "corrigibility_pause")
        self.assertTrue(shell.audit.verify())
        events = [entry.payload["event"] for entry in shell.audit.entries()]
        self.assertEqual(events, ["pause", "run_refused_paused"])


class TestFactoryCorrigibilityWiring(unittest.TestCase):
    def test_factory_shell_is_shared_with_runtime_view(self) -> None:
        from agent_os_api.runtime_factory import ContentCommerceRuntimeFactory, RuntimeFactoryConfig

        factory = ContentCommerceRuntimeFactory(
            RuntimeFactoryConfig(domain_pack_path=ROOT / "domain_packs" / "content_commerce")
        )
        runtime = factory.build()
        shell = factory.corrigibility_shell()

        self.assertIs(runtime.shell_view._paused_getter(), False)
        self.assertFalse(hasattr(runtime.shell_view, "op_pause"))

        shell.op_pause()
        outcome = runtime.evaluate(
            "GMV", {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}
        )
        self.assertTrue(outcome.blocked)
        self.assertEqual(outcome.block.code, BlockCode.PAUSED)
        self.assertTrue(shell.audit.verify())


if __name__ == "__main__":
    unittest.main()
