"""LH-RECOVERY-1A D1-F immutable fixed baseline DAG.

This module defines the strongest *one-size-fits-all* immutable workflow DAG
that an honest non-adaptive agent can pre-commit to for every regime
(``R0_DIRECT_REFRESH``, ``R1_DEPENDENCY_BEFORE_PROVIDER``,
``R2_RELEASE_BEFORE_APPLY``) under the frozen public runtime semantics and the
exact D1-E budget ceiling.

Design rationale (bound to public semantics only)
-------------------------------------------------
* The executor (``agent_os_core.execution.RunCoordinator``) runs **every** node
  in a single topological order (``_ordered_nodes``); edge ``condition`` fields
  are *declared but not consumed*.  There is therefore no in-graph branching:
  a committed node is always executed.
* A ``wait_event`` node parks the run until its concrete ``(signal_name,
  correlation_key)`` arrives, and ``TaskService.register_wait`` /
  ``expire_wait`` fail the run when the signal never arrives before the
  deadline.
* The environment emits **only the events that belong to the instance's own
  regime**.  Across all three regimes the sole universally-emitted change
  signal is ``requirement.changed`` (the ``wait_change`` node).  The secondary
  waits ``dependency.ready`` (R1) and ``release.ready`` (R2) are regime-local.

Consequently a "superset" DAG that embeds either secondary wait would park and
time out (RUN -> FAILED) on every regime that does not emit that signal.  Public
semantics do **not** permit a robust superset.  The strongest honest universal
graph is the maximal common linear path that depends only on the universally
emitted ``requirement.changed`` signal and never waits on a missing-regime
event.  With ``max_replans == 0`` the committed graph is structurally immutable
(``TaskService.replan_task`` rejects every replan once the budget is zero).

This module is the sole writer's artifact for D1-F.  It reuses the frozen
contract types so the same runtime validator that governs the candidate also
governs this baseline, and it adds a fail-closed structural/budget validator
suitable for mechanical review and skeptic reduction.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from agent_os_contracts import NodeKind, WorkflowGraph
from agent_os_contracts.workflow import EdgeSpec, NodeSpec

# Frozen D1-E authorities are imported directly (never hand-copied) so this
# baseline cannot drift from the environment it is measured against.
from product_evals.lh_recovery_1a.regimes import (
    CHANGE_SIGNAL_NAME,
    REGIME_SPECS,
    REGIMES,
)
from product_evals.lh_recovery_1a.templates import (
    SYNTHETIC_RATE_UNITS,
    BudgetUsage,
    CASE_PLACEHOLDER,
    COMPLETED_PREFIX,
    CREATED_AT,
    EVALUATOR_REFS,
    FIXED_CEILING,
    NODE_TEMPLATES,
    POLICY_VERSION,
    REGIME_SUFFIXES,
    budget_disposition,
    synthetic_cost_units,
)

__all__ = [
    "FIXED_BASELINE_BUDGET",
    "FIXED_BASELINE_WORKFLOW_ID",
    "FIXED_BASELINE_NODE_ORDER",
    "FROZEN_NODE_SNAPSHOT",
    "REGIMES",
    "UNIVERSAL_WAIT_SIGNAL",
    "FORBIDDEN_REGIME_LOCAL_SIGNALS",
    "FixedBudget",
    "FixedBaselineDag",
    "NodeRetryUsage",
    "FixedRuntimeUsageReceipt",
    "build_fixed_baseline_dag",
    "instantiate_fixed_baseline_dag",
    "validate_fixed_baseline_dag",
    "validate_fixed_runtime_usage",
    "FixedBaselineValidationError",
]


# --- D1-F-local identity -------------------------------------------------------

# Only the workflow id and authoring identity are D1-F-specific; every other
# workflow-level constant is bound from the frozen D1-E templates above.
FIXED_BASELINE_WORKFLOW_ID = "lh1a-fixed-baseline"
CREATED_BY = "lh1a-d1f-fixed-baseline"
# tenant/workspace are frozen environment identifiers; source them from an
# actual frozen candidate workflow rather than re-typing the literals.
from product_evals.lh_recovery_1a.templates import (  # noqa: E402
    candidate_template_for,
)

_REFERENCE_WORKFLOW = candidate_template_for("R0_DIRECT_REFRESH").workflow
TENANT_ID = _REFERENCE_WORKFLOW.tenant_id
WORKSPACE_ID = _REFERENCE_WORKFLOW.workspace_id


# --- Signals derived from frozen regime data -----------------------------------

# The only change signal emitted for every regime instance.
UNIVERSAL_WAIT_SIGNAL = CHANGE_SIGNAL_NAME
# Every regime declares the same universal change signal; assert that invariant
# so a frozen-data change would fail loudly rather than silently.
if {spec.change_signal_name for spec in REGIME_SPECS.values()} != {
    UNIVERSAL_WAIT_SIGNAL
}:
    raise RuntimeError("frozen regimes disagree on the universal change signal")

# Regime-local secondary signals (dependency.ready / release.ready) would
# deadlock a universal DAG in non-matching regimes; derive them from frozen
# regime specs so they are never guessed or hand-copied.
FORBIDDEN_REGIME_LOCAL_SIGNALS = tuple(
    sorted(
        spec.secondary_signal_name
        for spec in REGIME_SPECS.values()
        if spec.secondary_signal_name is not None
    )
)

# Immutable single DAG node order (10 nodes, within the max_nodes=11 ceiling):
# the frozen completed prefix followed by the frozen R0 recovery suffix.  This
# is the maximal common linear path that never waits on a regime-local signal.
FIXED_BASELINE_NODE_ORDER = tuple(COMPLETED_PREFIX) + tuple(
    REGIME_SUFFIXES["R0_DIRECT_REFRESH"]
)


# --- Budget --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FixedBudget:
    """Exact D1-E budget ceiling declared for the fixed baseline arm.

    The declaration is not caller-configurable: the six ceiling fields must
    equal the frozen ``FIXED_CEILING`` values and ``max_replans`` must be
    exactly zero.  Any smaller, larger, missing, bool, or otherwise different
    value raises ``FixedBaselineValidationError``.
    """

    max_nodes: int
    max_retries_per_node: int
    max_context_tokens: int
    max_provider_tokens: int
    max_tool_calls: int
    max_synthetic_cost_units: int
    max_replans: int

    def __post_init__(self) -> None:
        # bool is an int subclass; reject it explicitly (True == 1 would slip
        # through the equality check below otherwise).
        for field_name in (
            "max_nodes",
            "max_retries_per_node",
            "max_context_tokens",
            "max_provider_tokens",
            "max_tool_calls",
            "max_synthetic_cost_units",
            "max_replans",
        ):
            value = getattr(self, field_name)
            if type(value) is not int:
                raise FixedBaselineValidationError(
                    f"{field_name} must be a plain int (bool/other rejected)"
                )
        expected = {
            "max_nodes": FIXED_CEILING.max_nodes,
            "max_retries_per_node": FIXED_CEILING.max_retries_per_node,
            "max_context_tokens": FIXED_CEILING.max_context_tokens,
            "max_provider_tokens": FIXED_CEILING.max_provider_tokens,
            "max_tool_calls": FIXED_CEILING.max_tool_calls,
            "max_synthetic_cost_units": FIXED_CEILING.max_synthetic_cost_units,
            "max_replans": 0,
        }
        for field_name, want in expected.items():
            got = getattr(self, field_name)
            if got != want:
                raise FixedBaselineValidationError(
                    f"{field_name} must equal the frozen ceiling value {want!r}, "
                    f"got {got!r}"
                )


# Values are bound from the frozen D1-E FIXED_CEILING; only max_replans=0 is
# the D1-F-specific immutability constraint.
FIXED_BASELINE_BUDGET = FixedBudget(
    max_nodes=FIXED_CEILING.max_nodes,
    max_retries_per_node=FIXED_CEILING.max_retries_per_node,
    max_context_tokens=FIXED_CEILING.max_context_tokens,
    max_provider_tokens=FIXED_CEILING.max_provider_tokens,
    max_tool_calls=FIXED_CEILING.max_tool_calls,
    max_synthetic_cost_units=FIXED_CEILING.max_synthetic_cost_units,
    max_replans=0,
)


# --- Errors --------------------------------------------------------------------


class FixedBaselineValidationError(ValueError):
    """Raised when the fixed baseline DAG or budget fails a closed check."""


# --- Immutable frozen node snapshot --------------------------------------------

# Snapshot exactly the selected frozen NodeSpec objects (identity-preserving) at
# import time.  Construction and validation both bind to this snapshot, so a
# later monkeypatch of templates.NODE_TEMPLATES cannot swap node semantics and
# still pass validation.
FROZEN_NODE_SNAPSHOT: MappingProxyType[str, NodeSpec] = MappingProxyType(
    {node_id: NODE_TEMPLATES[node_id] for node_id in FIXED_BASELINE_NODE_ORDER}
)


# --- Immutable DAG representation ---------------------------------------------


@dataclass(frozen=True, slots=True)
class FixedBaselineDag:
    """Typed immutable wrapper around the single fixed baseline workflow.

    ``workflow`` is the frozen ``WorkflowGraph`` (validated acyclic, terminal
    reachable) that is committed identically for every regime.  ``budget`` is
    the exact declared ceiling.  ``regimes`` records that this one graph is the
    plan for all three regimes.
    """

    workflow: WorkflowGraph
    budget: FixedBudget
    node_order: tuple[str, ...]
    regimes: tuple[str, ...]

    @property
    def node_ids(self) -> tuple[str, ...]:
        return tuple(node.node_id for node in self.workflow.nodes)

    @property
    def edge_pairs(self) -> tuple[tuple[str, str], ...]:
        return tuple((edge.source, edge.target) for edge in self.workflow.edges)

    @property
    def tool_node_ids(self) -> tuple[str, ...]:
        return tuple(
            node.node_id for node in self.workflow.nodes if node.kind is NodeKind.TOOL
        )

    @property
    def wait_signals(self) -> tuple[str, ...]:
        return tuple(
            node.wait_signal_name
            for node in self.workflow.nodes
            if node.kind is NodeKind.WAIT_EVENT and node.wait_signal_name is not None
        )

    def canonical_digest(self) -> str:
        return self.workflow.canonical_digest()


# --- Construction --------------------------------------------------------------


def _sequential_edges(node_ids: tuple[str, ...]) -> tuple[EdgeSpec, ...]:
    return tuple(
        EdgeSpec(source=source, target=target)
        for source, target in zip(node_ids, node_ids[1:])
    )


def _instantiate_nodes(
    node_ids: tuple[str, ...], case_id: str | None
) -> tuple[NodeSpec, ...]:
    nodes: list[NodeSpec] = []
    for node_id in node_ids:
        node = FROZEN_NODE_SNAPSHOT[node_id]
        if (
            case_id is not None
            and node.kind is NodeKind.WAIT_EVENT
            and node.wait_correlation_key is not None
        ):
            node = node.model_copy(
                update={
                    "wait_correlation_key": node.wait_correlation_key.replace(
                        CASE_PLACEHOLDER, case_id
                    )
                }
            )
        nodes.append(node)
    return tuple(nodes)


def _build_workflow(
    node_ids: tuple[str, ...],
    *,
    case_id: str | None,
) -> WorkflowGraph:
    # max_replans is not caller-controlled: the committed graph is always
    # immutable (exact zero) so no replan is ever admissible.
    return WorkflowGraph(
        workflow_id=FIXED_BASELINE_WORKFLOW_ID,
        version=1,
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        created_by=CREATED_BY,
        created_at=CREATED_AT,
        policy_version=POLICY_VERSION,
        evaluator_refs=EVALUATOR_REFS,
        nodes=_instantiate_nodes(node_ids, case_id),
        edges=_sequential_edges(node_ids),
        max_replans=0,
    )


def build_fixed_baseline_dag(*, case_id: str | None = None) -> FixedBaselineDag:
    """Construct and validate the single immutable fixed baseline DAG.

    The budget is never caller-configurable: the DAG always carries the exact
    frozen ``FIXED_BASELINE_BUDGET``.  The same graph is returned for every
    regime.  ``case_id`` optionally resolves the ``wait_change`` correlation
    placeholder; when ``None`` the placeholder is retained for template
    inspection.  The result is validated fail-closed before it is returned.

    Boundary: this validates graph shape and the declared ceiling only.  It
    does NOT assert a runtime ``budget_matches`` claim -- that claim is
    forbidden without a passing ``validate_fixed_runtime_usage`` receipt.
    """

    workflow = _build_workflow(FIXED_BASELINE_NODE_ORDER, case_id=case_id)
    dag = FixedBaselineDag(
        workflow=workflow,
        budget=FIXED_BASELINE_BUDGET,
        node_order=FIXED_BASELINE_NODE_ORDER,
        regimes=REGIMES,
    )
    validate_fixed_baseline_dag(dag)
    return dag


def instantiate_fixed_baseline_dag(case_id: str) -> FixedBaselineDag:
    """Return the fixed baseline DAG with the change wait bound to ``case_id``."""

    if not isinstance(case_id, str) or not case_id.strip():
        raise FixedBaselineValidationError("case_id must be a non-blank string")
    return build_fixed_baseline_dag(case_id=case_id)


# --- Fail-closed validation ----------------------------------------------------


def _node_matches_frozen(node: NodeSpec) -> bool:
    """Exact match against the frozen snapshot template for ``node.node_id``.

    The only permitted deviation is the case-specific wait-correlation-key
    substitution on the single ``wait_event`` node: ``{case_id}`` may be
    replaced by a concrete, non-blank case identifier.  Every other field
    (kind, capability, contracts, timeouts, idempotency, risk tier, signal
    name) must be byte-for-byte identical to the frozen template, so no caller
    or monkeypatch can substitute provider capability or other node semantics
    and still validate.
    """

    frozen = FROZEN_NODE_SNAPSHOT.get(node.node_id)
    if frozen is None:
        return False
    if node == frozen:
        return True
    template_key = frozen.wait_correlation_key
    if (
        frozen.kind is not NodeKind.WAIT_EVENT
        or template_key is None
        or CASE_PLACEHOLDER not in template_key
    ):
        return False
    observed_key = node.wait_correlation_key or ""
    if "{" in observed_key or "}" in observed_key:
        return False
    prefix, _, suffix = template_key.partition(CASE_PLACEHOLDER)
    if not observed_key.startswith(prefix) or not observed_key.endswith(suffix):
        return False
    case_id = observed_key[len(prefix) : len(observed_key) - len(suffix) or None]
    if not case_id.strip():
        return False
    rebuilt = frozen.model_copy(
        update={"wait_correlation_key": template_key.replace(CASE_PLACEHOLDER, case_id)}
    )
    return node == rebuilt


def validate_fixed_baseline_dag(dag: FixedBaselineDag) -> None:
    """Fail-closed structural and budget validation of the fixed baseline.

    Raises ``FixedBaselineValidationError`` on any violation.  The underlying
    ``WorkflowGraph`` model validator has already enforced acyclicity, a single
    reachable terminal, and edge integrity; this adds the D1-F invariants:
    single immutable DAG, zero replans, node/tool budget ceilings, exactly one
    universally-emitted wait, and no regime-local wait signal.

    Boundary: this asserts graph shape and the declared ceiling only.  It never
    asserts actual runtime usage; a ``budget_matches`` claim requires a passing
    ``validate_fixed_runtime_usage`` receipt.
    """

    if not isinstance(dag, FixedBaselineDag):
        raise FixedBaselineValidationError("expected a FixedBaselineDag")

    workflow = dag.workflow
    budget = dag.budget

    # --- Budget is the exact frozen ceiling, not caller-configurable ---
    if budget != FIXED_BASELINE_BUDGET:
        raise FixedBaselineValidationError(
            "fixed baseline budget must equal the frozen FIXED_BASELINE_BUDGET"
        )

    # --- Immutability / replan ceiling ---
    if budget.max_replans != 0:
        raise FixedBaselineValidationError("fixed baseline requires max_replans == 0")
    if workflow.max_replans != 0:
        raise FixedBaselineValidationError(
            "committed workflow must set max_replans == 0"
        )

    # --- One single DAG for all regimes ---
    if tuple(dag.regimes) != REGIMES:
        raise FixedBaselineValidationError(
            "fixed baseline must declare all three regimes for one DAG"
        )
    if dag.node_ids != tuple(dag.node_order):
        raise FixedBaselineValidationError(
            "committed node order does not match the declared node order"
        )
    if dag.node_order != FIXED_BASELINE_NODE_ORDER:
        raise FixedBaselineValidationError("node order drifted from the frozen order")

    # --- Every committed node must equal its exact frozen snapshot template ---
    for node in workflow.nodes:
        if not _node_matches_frozen(node):
            raise FixedBaselineValidationError(
                f"node {node.node_id} does not match its frozen D1-E template "
                "(only the case-specific wait correlation key may differ)"
            )

    # --- Node-count budget (fail closed on shape) ---
    node_count = len(workflow.nodes)
    if node_count < 1:
        raise FixedBaselineValidationError("workflow must contain at least one node")
    if node_count > budget.max_nodes:
        raise FixedBaselineValidationError(
            f"node count {node_count} exceeds max_nodes {budget.max_nodes}"
        )

    # --- Per-node retry ceiling ---
    for node in workflow.nodes:
        retries = node.max_attempts - 1
        if retries < 0 or retries > budget.max_retries_per_node:
            raise FixedBaselineValidationError(
                f"node {node.node_id} retries {retries} exceed "
                f"max_retries_per_node {budget.max_retries_per_node}"
            )

    # --- Structural primary-tool-node ceiling ---
    # This bounds the number of TOOL *nodes* in the graph, i.e. the count of
    # primary tool invocations a fully-completed episode would make.  It is a
    # graph-shape bound only and is NOT the real runtime tool-invocation count
    # (retries and compensation are counted solely by the runtime-usage
    # receipt; see validate_fixed_runtime_usage).
    tool_node_ids = dag.tool_node_ids
    if len(tool_node_ids) > budget.max_tool_calls:
        raise FixedBaselineValidationError(
            f"primary tool-node count {len(tool_node_ids)} exceeds structural "
            f"max_tool_calls {budget.max_tool_calls}"
        )

    # --- Edges must form the immutable linear chain over the node order ---
    expected_edges = tuple(
        (source, target) for source, target in zip(dag.node_order, dag.node_order[1:])
    )
    if dag.edge_pairs != expected_edges:
        raise FixedBaselineValidationError(
            "fixed baseline edges must be the immutable sequential chain"
        )

    # --- Terminal integrity ---
    terminals = [
        node.node_id for node in workflow.nodes if node.kind is NodeKind.TERMINAL
    ]
    if len(terminals) != 1:
        raise FixedBaselineValidationError(
            "fixed baseline requires exactly one terminal node"
        )

    # --- Wait-event universality: exactly one wait, only the universal signal ---
    wait_nodes = [node for node in workflow.nodes if node.kind is NodeKind.WAIT_EVENT]
    if len(wait_nodes) != 1:
        raise FixedBaselineValidationError(
            "fixed baseline must contain exactly one (universal) wait_event node"
        )
    wait_node = wait_nodes[0]
    if wait_node.wait_signal_name != UNIVERSAL_WAIT_SIGNAL:
        raise FixedBaselineValidationError(
            "the only wait must bind the universally-emitted requirement.changed signal"
        )
    for node in workflow.nodes:
        if node.kind is NodeKind.WAIT_EVENT and (
            node.wait_signal_name in FORBIDDEN_REGIME_LOCAL_SIGNALS
        ):
            raise FixedBaselineValidationError(
                "fixed baseline must never wait on a regime-local signal "
                f"({node.wait_signal_name})"
            )

    # --- No dynamic-graph primitives (no model/provider graph creation) ---
    forbidden_kinds = {
        NodeKind.LOOP,
        NodeKind.PARALLEL_MAP,
        NodeKind.SUBWORKFLOW,
        NodeKind.DECISION,
    }
    for node in workflow.nodes:
        if node.kind in forbidden_kinds:
            raise FixedBaselineValidationError(
                f"fixed baseline forbids dynamic node kind {node.kind.value}"
            )
        if node.failure_edge is not None:
            raise FixedBaselineValidationError(
                "fixed baseline forbids failure_edge routing"
            )


# --- Runtime usage receipt (actual invocation accounting) ----------------------


@dataclass(frozen=True, slots=True)
class NodeRetryUsage:
    """Observed retry count for a single committed DAG node."""

    node_id: str
    retries: int


@dataclass(frozen=True, slots=True)
class FixedRuntimeUsageReceipt:
    """Immutable record of what a single episode actually consumed.

    This is deliberately separate from graph-shape validation: node counts on
    the static DAG bound *primary* tool nodes only, whereas real tool
    invocations also include retries and compensation.  A ``budget_matches``
    claim is valid only after ``validate_fixed_runtime_usage`` accepts this
    receipt against the frozen ceiling.
    """

    context_tokens: int
    provider_tokens: int
    primary_tool_calls: int
    retry_tool_calls: int
    compensation_tool_calls: int
    total_tool_calls: int
    synthetic_cost_units: int
    per_node_retries: tuple[NodeRetryUsage, ...]


def _require_plain_nonneg_int(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise FixedBaselineValidationError(
            f"{field_name} must be a plain int (bool/other rejected)"
        )
    if value < 0:
        raise FixedBaselineValidationError(f"{field_name} must be non-negative")
    return value


def validate_fixed_runtime_usage(
    dag: FixedBaselineDag,
    receipt: FixedRuntimeUsageReceipt,
) -> BudgetUsage:
    """Fail-closed validation of an episode's actual runtime usage.

    Returns the normalized frozen D1-E ``BudgetUsage`` ONLY after every check
    passes; any missing, malformed, inconsistent, or over-ceiling receipt
    raises ``FixedBaselineValidationError``.  This is the sole gate behind
    which a runtime ``budget_matches`` claim is admissible.
    """

    # The receipt is meaningless unless it is paired with a valid graph.
    validate_fixed_baseline_dag(dag)

    if not isinstance(receipt, FixedRuntimeUsageReceipt):
        raise FixedBaselineValidationError("expected a FixedRuntimeUsageReceipt")

    context_tokens = _require_plain_nonneg_int(receipt.context_tokens, "context_tokens")
    provider_tokens = _require_plain_nonneg_int(
        receipt.provider_tokens, "provider_tokens"
    )
    primary_tool_calls = _require_plain_nonneg_int(
        receipt.primary_tool_calls, "primary_tool_calls"
    )
    retry_tool_calls = _require_plain_nonneg_int(
        receipt.retry_tool_calls, "retry_tool_calls"
    )
    compensation_tool_calls = _require_plain_nonneg_int(
        receipt.compensation_tool_calls, "compensation_tool_calls"
    )
    total_tool_calls = _require_plain_nonneg_int(
        receipt.total_tool_calls, "total_tool_calls"
    )
    claimed_cost = _require_plain_nonneg_int(
        receipt.synthetic_cost_units, "synthetic_cost_units"
    )

    # --- Exactly one retry row per DAG node, in DAG node order ---
    if not isinstance(receipt.per_node_retries, tuple):
        raise FixedBaselineValidationError("per_node_retries must be a tuple")
    rows = receipt.per_node_retries
    expected_order = dag.node_ids
    if len(rows) != len(expected_order):
        raise FixedBaselineValidationError(
            f"per_node_retries must have exactly {len(expected_order)} rows "
            f"(one per DAG node), got {len(rows)}"
        )
    global_retries_ceiling = FIXED_CEILING.max_retries_per_node
    nodes_by_id = {node.node_id: node for node in dag.workflow.nodes}
    tool_node_ids = set(dag.tool_node_ids)
    retry_over_tool_nodes = 0
    max_observed_retries = 0
    for row, expected_node_id in zip(rows, expected_order):
        if not isinstance(row, NodeRetryUsage):
            raise FixedBaselineValidationError(
                "per_node_retries entries must be NodeRetryUsage"
            )
        if row.node_id != expected_node_id:
            raise FixedBaselineValidationError(
                "per_node_retries must be in DAG node order with no unknown, "
                f"duplicate, or missing node (expected {expected_node_id!r}, "
                f"got {row.node_id!r})"
            )
        retries = _require_plain_nonneg_int(row.retries, f"retries[{row.node_id}]")
        # Stricter of the frozen global ceiling and this exact committed node's
        # own max_attempts - 1 (current frozen nodes have max_attempts=1, so any
        # observed retry must fail even though the global ceiling is 1).
        node_retries_ceiling = min(
            global_retries_ceiling, nodes_by_id[row.node_id].max_attempts - 1
        )
        if retries > node_retries_ceiling:
            raise FixedBaselineValidationError(
                f"node {row.node_id} retries {retries} exceed its per-node retry "
                f"ceiling {node_retries_ceiling} (min of frozen "
                f"max_retries_per_node {global_retries_ceiling} and node "
                f"max_attempts-1 {nodes_by_id[row.node_id].max_attempts - 1})"
            )
        max_observed_retries = max(max_observed_retries, retries)
        if row.node_id in tool_node_ids:
            retry_over_tool_nodes += retries

    # --- Primary/retry/compensation/total consistency ---
    if primary_tool_calls != len(tool_node_ids):
        raise FixedBaselineValidationError(
            "primary_tool_calls must equal the number of primary TOOL nodes "
            f"({len(tool_node_ids)}) for a completed/recovered episode, got "
            f"{primary_tool_calls}"
        )
    if retry_tool_calls != retry_over_tool_nodes:
        raise FixedBaselineValidationError(
            "retry_tool_calls must equal retries summed over TOOL nodes "
            f"({retry_over_tool_nodes}), got {retry_tool_calls}"
        )
    recomputed_total = primary_tool_calls + retry_tool_calls + compensation_tool_calls
    if total_tool_calls != recomputed_total:
        raise FixedBaselineValidationError(
            "total_tool_calls must equal primary + retry + compensation "
            f"({recomputed_total}), got {total_tool_calls}"
        )

    # --- Recompute synthetic cost from frozen D1-E rates ---
    recomputed_cost = synthetic_cost_units(
        provider_tokens, total_tool_calls, rates=SYNTHETIC_RATE_UNITS
    )
    if claimed_cost != recomputed_cost:
        raise FixedBaselineValidationError(
            f"synthetic_cost_units must equal the frozen-rate recomputation "
            f"({recomputed_cost}), got {claimed_cost}"
        )

    # --- Bind all six budget dimensions and require ALLOW ---
    usage = BudgetUsage(
        node_count=len(dag.workflow.nodes),
        retries_per_node=max_observed_retries,
        context_tokens=context_tokens,
        provider_tokens=provider_tokens,
        tool_calls=total_tool_calls,
        synthetic_cost_units=recomputed_cost,
    )
    if budget_disposition(usage, FIXED_CEILING) != "ALLOW":
        raise FixedBaselineValidationError(
            "runtime usage exceeds the frozen budget ceiling (budget_disposition "
            "DENY): context/provider tokens, total tool calls, or synthetic cost "
            "over ceiling"
        )
    return usage
