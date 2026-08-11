"""S3 (RR-0048 Option 2): integrated real execution across a real PROCESS BOUNDARY.

Boots the OS-side reference governed-decision seam service (examples/reference_seam_service.py) as a
SEPARATE PROCESS and drives the FULL TrustedLoopRuntime through RemoteGovernanceDecisionClient — real
socket, real JSON, real subprocess — so a real reversible R0-R3 action is governed end-to-end by a brain
that lives in another process (no in-process shortcut, no cross-repo import #19). The production research
brain (autonomous-agent-core aac.seam_service) is a drop-in for the same wire; that live rehearsal is
examples/m4_live_seam_rehearsal.py (skips without AAC_REPO). This test is self-contained and always runs.

Proven here:
  1. verified cohort effect -> the OS verifies locally, ships VerifiedCandidates over the wire, the remote
     brain governs -> ALLOW -> OS approval -> ADR-0005 execution-time recheck (re-consulted OVER THE WIRE,
     still ALLOW) -> connector.execute -> a REAL ledger write. Reversible via rollback.
  2. corrigibility (C7) is absolute even with a remote brain: an operator pause after approval halts the
     action before any connector side-effect (0 records) — enforced OS-side, never delegated to the remote.
  3. resilience: when the remote brain is DOWN, FallbackGovernanceDecisionClient degrades SAFE — the loop
     never blocks and never auto-allows (the action is forced to approval), so 'brain unreachable' resolves
     to escalate-to-human, not silent execution (ADR-0047 never-block-on-the-organ).
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "os_core" / "src"))
sys.path.insert(0, str(ROOT / "action_connectors"))

from agent_os_contracts import (  # noqa: E402
    ActionConnectorContract,
    BlockCode,
    ConnectorExecutionSemantics,
    MetricContract,
    ProviderContract,
    ProviderKind,
    QueryResult,
    SQLTemplate,
)
from agent_os_core import (  # noqa: E402
    CorrigibilityShell,
    ProviderRegistry,
    SemanticRegistry,
    TrustedLoopRuntime,
)
from agent_os_core.action_connectors import ActionConnectorRegistry  # noqa: E402
from agent_os_core.governance_decision_seam import (  # noqa: E402
    FallbackGovernanceDecisionClient,
    LocalGovernanceDecisionClient,
    MetricCohortABVerifier,
    RemoteGovernanceDecisionClient,
    http_transport,
)
from agent_os_core.query_runtime import StaticQueryExecutor  # noqa: E402
from agent_os_core.trusted_loop import TrustedLoopBlocked  # noqa: E402
from action_record import ActionRecordConnector, ActionRecordStore  # noqa: E402
from manual_review import ManualReviewConnector  # noqa: E402

_ACTION_INTENT = "记录行动：基于最近7天GMV创建一个跟进行动"
_PARAMS = {"start_date": "2026-05-25", "end_date": "2026-06-01", "limit": 100}
_SERVICE = ROOT / "examples" / "reference_seam_service.py"


def _cohort(effect: bool) -> QueryResult:
    if not effect:
        return QueryResult(rows=(), row_count=0)
    rows = tuple(
        [{"cohort": "A", "metric": v} for v in (120.0, 132.0, 128.0, 141.0)]
        + [{"cohort": "B", "metric": v} for v in (88.0, 91.0, 84.0, 90.0)]
    )
    return QueryResult(rows=rows, row_count=len(rows))


def _remote_client(url: str, effect: bool = True) -> RemoteGovernanceDecisionClient:
    # RemoteGovernanceDecisionClient VERIFIES locally (OS owns the data) then ships VerifiedCandidates
    # over the wire; the remote reference brain only GOVERNS them.
    return RemoteGovernanceDecisionClient(
        transport=http_transport(url, timeout_seconds=5.0),
        verifier=MetricCohortABVerifier(lambda action: _cohort(effect)),
    )


def _connector_registry(store: ActionRecordStore) -> ActionConnectorRegistry:
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
    registry.register(
        ActionRecordConnector(store=store),
        ActionConnectorContract(
            connector_name="action_record",
            display_name="Action Record",
            supported_action_types=("execute",),
            supports_snapshot=True,
            supports_rollback=True,
            compensating_action_description="Restore the action record store to the pre-execution snapshot",
            risk_ceiling="R3",
            owner="system",
            execution_semantics=ConnectorExecutionSemantics(
                durability_scope="connector_local_ledger",
                external_ack_status="not_applicable",
                ledger_status="recorded",
                supports_idempotency=True,
                supports_reconciliation=True,
            ),
        ),
    )
    return registry


def _runtime(store, *, shell_view=None, client=None) -> TrustedLoopRuntime:
    metric = MetricContract(
        metric_name="gmv",
        display_name="GMV",
        definition="Gross merchandise value over paid orders.",
        owner="revenue_ops",
        unit="CNY",
        allowed_schemas=("sales",),
    )
    template = SQLTemplate(
        template_id="gmv_daily",
        metric_name="gmv",
        sql=(
            "select order_date, sum(paid_amount) as gmv from sales.orders "
            "where order_date >= :start_date and order_date < :end_date group by order_date limit :limit"
        ),
        required_parameters=("start_date", "end_date", "limit"),
    )
    return TrustedLoopRuntime(
        metric_contract=metric,
        sql_template=template,
        query_executor=StaticQueryExecutor([{"order_date": "2026-05-31", "gmv": 128800.0}]),
        semantic_registry=SemanticRegistry(metric_contracts=(metric,)),
        provider_registry=ProviderRegistry(
            (
                ProviderContract(
                    provider_id="provider-sales",
                    kind=ProviderKind.WAREHOUSE,
                    name="sales warehouse",
                    owner="revenue_ops",
                    allowed_schemas=("sales",),
                ),
            )
        ),
        connector_registry=_connector_registry(store),
        shell_view=shell_view,
        governance_decision_client=client,
    )


def _run_to_approved(runtime):
    result = runtime.run(_ACTION_INTENT, _PARAMS)
    assert result.action_proposal.approval_required is True
    assert result.action_result["status"] == "awaiting_approval"
    approval_id = result.approval_record.approval_id
    runtime.approval_runtime.approve(approval_id, reason="approved by operator")
    return result, approval_id


def _execute(runtime, result, approval_id):
    return runtime.execute_approved_operation(
        approval_id=approval_id,
        operation=result.operation_contract,
        action_parameters=result.action_proposal.action_parameters,
        evidence_chain=result.evidence_chain,
        proposal_id=result.action_proposal.proposal_id,
    )


def _snapshot_id_from_trace_events(events) -> str:
    for event in events:
        if event.get("step") == "state_snapshot":
            snapshot_id = event.get("snapshot_id")
            if isinstance(snapshot_id, str):
                return snapshot_id
    raise AssertionError("operation trace did not include a state_snapshot event")


def _verdicts(shell, event_name):
    return [
        entry.payload.get("verdict")
        for entry in shell.audit.entries()
        if entry.payload.get("event") == event_name
    ]


class CrossProcessSeamRealAction(unittest.TestCase):
    server: subprocess.Popen

    @classmethod
    def setUpClass(cls):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(ROOT / "packages" / "contracts" / "src")
        cls.server = subprocess.Popen(
            [sys.executable, str(_SERVICE), "--port", "0"],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        assert cls.server.stdout is not None
        line = cls.server.stdout.readline().strip()
        if not line.startswith("READY http://"):
            cls.server.terminate()
            raise unittest.SkipTest(f"reference seam service did not boot: {line!r}")
        cls.url = line.split("READY ", 1)[1]  # http://127.0.0.1:<port>/decide

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()

    def test_verified_effect_executes_across_process_boundary(self):
        store = ActionRecordStore()
        shell = CorrigibilityShell()
        runtime = _runtime(
            store, shell_view=shell.view(), client=_remote_client(self.url, effect=True)
        )
        result, approval_id = _run_to_approved(runtime)

        trace = _execute(runtime, result, approval_id)

        self.assertEqual(trace.state.value, "executed")
        self.assertEqual(len(store.records()), 1)  # a REAL reversible write, governed over the wire
        # the REMOTE brain governed the ACTUAL execution (ADR-0005 recheck re-consulted over the socket)
        self.assertEqual(_verdicts(shell, "execution_governed_decision"), ["ALLOW"])

        rollback_result = runtime.rollback(_snapshot_id_from_trace_events(trace.events))
        self.assertEqual(rollback_result["status"], "rolled_back")
        self.assertEqual(store.records(), ())  # fully reversible

    def test_corrigibility_pause_halts_even_with_remote_brain(self):
        store = ActionRecordStore()
        shell = CorrigibilityShell()
        runtime = _runtime(
            store, shell_view=shell.view(), client=_remote_client(self.url, effect=True)
        )
        result, approval_id = _run_to_approved(runtime)

        shell.op_pause()  # operator pauses AFTER approval — enforced OS-side, before consulting the remote

        with self.assertRaises(TrustedLoopBlocked) as ctx:
            _execute(runtime, result, approval_id)
        self.assertEqual(ctx.exception.block.code, BlockCode.PAUSED)
        self.assertEqual(store.records(), ())  # the real reversible connector NEVER ran


class RemoteBrainDownDegradesSafe(unittest.TestCase):
    def test_service_down_never_blocks_and_never_auto_allows(self):
        # Point the remote client at a closed port; wrap it so 'brain unreachable' degrades to a SAFE
        # local escalate (an empty-cohort verifier => never verified => never ALLOW). The loop must not
        # crash, must not block, and must not auto-execute — the action is forced to human approval.
        dead = RemoteGovernanceDecisionClient(
            transport=http_transport("http://127.0.0.1:9/decide", timeout_seconds=1.0),
            verifier=MetricCohortABVerifier(lambda a: _cohort(True)),
        )
        safe_fallback = LocalGovernanceDecisionClient(
            MetricCohortABVerifier(lambda a: QueryResult(rows=(), row_count=0)),
            approval_required_at_or_above="R4",
        )
        client = FallbackGovernanceDecisionClient(primary=dead, fallback=safe_fallback)

        store = ActionRecordStore()
        shell = CorrigibilityShell()
        runtime = _runtime(store, shell_view=shell.view(), client=client)

        result = runtime.run(_ACTION_INTENT, _PARAMS)

        self.assertTrue(result.action_proposal.approval_required)
        self.assertEqual(result.action_result["status"], "awaiting_approval")
        self.assertEqual(
            store.records(), ()
        )  # nothing auto-executed when the brain was unreachable
        self.assertIn("ESCALATE", _verdicts(shell, "governed_decision"))


if __name__ == "__main__":
    unittest.main()
