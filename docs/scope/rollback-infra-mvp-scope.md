# 回滚基础设施 MVP 工程范围文档

> Rollback Infrastructure MVP Scope Spec
> 版本: 1.0
> 日期: 2026-07-22
> 状态: Draft

---

## 1. 工程目标

交付从 `ActionProposal` 到受治理动作执行（含回滚准备）的完整可运行链路，使 data-agent-os 从"只 propose 的分析工具"升级为"可信执行的业务操作系统"。

---

## 2. 范围边界

### 2.1 P0 必须做

| # | 工作项 | 说明 |
|---|--------|------|
| 1 | 契约层扩展 | `OperationContract` 新增字段、`OperationState` 新增枚举、新增 `StateSnapshot` 契约、新增 `ActionConnectorContract` 契约 |
| 2 | `ActionProposal` 结构化 | `recommended_action` 从纯文本改为 `connector_name` + `action_type` + `parameters`，使动作可路由 |
| 3 | `ActionConnector` ABC | 定义 `take_snapshot` / `execute` / `rollback` / `can_rollback` / `compensating_action` 抽象接口 |
| 4 | `ActionConnectorRegistry` | 注册/查找 connector，按 `connector_name` 路由 |
| 5 | `manual_review` connector | 第一个真实 connector 实现——将 R4/R5 动作路由到人工审批队列，`execute` 返回 pending 状态 |
| 6 | `ActionGovernance` 增强 | 从硬编码升级为基于 `OperationContract` + `ActionConnectorContract` 的治理决策，输出 `snapshot_required` / `rollback_supported` |
| 7 | `OperationStateMachine` | 实现 `OperationState` 合法状态转移，拒绝非法转换 |
| 8 | `TrustedLoopRuntime` 集成 | 在 `action_proposal` 之后调用 `ActionGovernance` → `ActionConnectorRegistry` → `ApprovalLiteRuntime` → `OperationTraceBuilder`，贯通完整链路 |

### 2.2 P0 明确不做

| # | 不做项 | 原因 |
|---|--------|------|
| 1 | `SnapshotStore` 持久化实现 | MVP 阶段快照仅存内存，`StateSnapshot` 只定义契约 |
| 2 | `RollbackExecutor` 实现 | MVP 只铺设回滚准备路径（`can_rollback` / `compensating_action` 声明），不实现实际回滚执行 |
| 3 | 真实业务 connector（email / Slack / ERP） | 仅实现 `manual_review` connector 作为参考实现 |
| 4 | Saga 编排 / 分布式事务 | 超出 MVP 边界，后续迭代 |
| 5 | delta 快照 / reference 快照 | MVP 只支持 full snapshot 契约定义，不做差异计算 |
| 6 | API 层 / UI 层变更 | 本迭代聚焦核心链路贯通，不涉及 `api_server` 或 `workspace` |

---

## 3. 契约层变更需求

### 3.1 `OperationContract` 扩展字段

当前定义（`packages/contracts/src/agent_os_contracts/architecture.py`）:

```python
@dataclass(frozen=True)
class OperationContract:
    operation_id: str
    name: str
    target_connector: str
    risk_level: str
    approval_required: bool
    dry_run_required: bool = True
    rollback_supported: bool = False
```

需要新增以下字段（均有默认值，保持向后兼容）:

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `snapshot_required` | `bool` | `False` | 是否需要在执行前拍摄状态快照 |
| `snapshot_id` | `str \| None` | `None` | 已拍摄的快照 ID，执行前填充 |
| `compensating_action` | `str \| None` | `None` | 补偿动作描述，由 connector 声明 |
| `connector_name` | `str` | `"manual_review"` | 目标 connector 名称，从 `ActionProposal` 路由而来 |
| `action_type` | `str` | `"propose"` | 动作类型（propose / execute / compensate） |

变更后 `target_connector` 字段保留但标记为 deprecated，新增 `connector_name` 替代。迁移期两者共存。

### 3.2 `OperationState` 新增枚举

当前定义（`packages/contracts/src/agent_os_contracts/architecture.py`）:

```python
class OperationState(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    OBSERVED = "observed"
```

需要新增以下枚举值:

| 枚举值 | 说明 |
|--------|------|
| `SNAPSHOTTING` | 正在拍摄执行前状态快照 |
| `ROLLING_BACK` | 正在执行回滚 |
| `ROLLED_BACK` | 回滚已完成 |
| `COMPENSATING` | 正在执行补偿动作 |
| `FAILED` | 执行失败（区别于 REJECTED，REJECTED 是审批拒绝，FAILED 是执行异常） |

### 3.3 新增 `StateSnapshot` 契约

```python
@dataclass(frozen=True)
class StateSnapshot:
    snapshot_id: str
    operation_id: str
    connector_name: str
    snapshot_type: str          # MVP: "full" | "reference"
    state_payload: dict[str, Any]  # 快照数据，MVP 阶段为内存字典
    created_at: str             # ISO 8601
    metadata: dict[str, Any] = field(default_factory=dict)
```

MVP 约束:
- `snapshot_type` 仅支持 `"full"`
- `state_payload` 由 connector 的 `take_snapshot()` 方法填充
- 不做持久化，不实现 `SnapshotStore`

### 3.4 新增 `ActionConnectorContract` 契约

```python
@dataclass(frozen=True)
class ActionConnectorContract:
    connector_name: str
    display_name: str
    supported_action_types: tuple[str, ...]  # 如 ("propose", "execute")
    supports_snapshot: bool
    supports_rollback: bool
    compensating_action_description: str | None
    risk_ceiling: str           # 该 connector 允许的最高风险级别
    owner: str
```

这是 connector 的自描述契约，注册到 `ActionConnectorRegistry` 时必须提供。

---

## 4. `ActionProposal` 结构化需求

### 当前问题

`ActionProposal.recommended_action` 是自由文本字符串:

```python
recommended_action: str  # 如 "Review the metric result and decide..."
```

无法路由到具体 connector，`ActionGovernance.build_operation_contract()` 只能硬编码 `target_connector="manual_review"`。

### 变更方案

将 `recommended_action: str` 拆解为结构化字段:

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `connector_name` | `str` | `"manual_review"` | 目标 connector 名称 |
| `action_type` | `str` | `"propose"` | 动作类型 |
| `action_parameters` | `dict[str, Any]` | `field(default_factory=dict)` | 动作参数 |
| `recommended_action` | `str` | 保留 | 人类可读描述，不删除字段以保持兼容 |

变更要点:
1. `connector_name` 必须在 `ActionConnectorRegistry` 中有对应注册，否则路由失败
2. `action_type` 必须在 `ActionConnectorContract.supported_action_types` 中，否则校验失败
3. `recommended_action` 保留作为人类可读摘要，不参与路由逻辑
4. `ActionProposalBuilder` 必须更新为输出结构化字段

### 路由逻辑

```
ActionProposal.connector_name
  → ActionConnectorRegistry.get(connector_name)
    → ActionConnector.execute(action_type, action_parameters)
```

---

## 5. `ActionConnector` 设计要求

### 5.1 ABC 定义

位置: `packages/os_core/src/agent_os_core/action_connectors/base.py`

```python
from abc import ABC, abstractmethod
from agent_os_contracts import StateSnapshot, OperationContract

class ActionConnector(ABC):
    @abstractmethod
    def connector_name(self) -> str: ...

    @abstractmethod
    def take_snapshot(self, operation: OperationContract) -> StateSnapshot | None:
        """拍摄执行前状态快照。不支持快照的 connector 返回 None。"""
        ...

    @abstractmethod
    def execute(self, operation: OperationContract, parameters: dict[str, Any]) -> dict[str, Any]:
        """执行动作。返回执行结果字典，必须包含 'status' 键。"""
        ...

    @abstractmethod
    def rollback(self, snapshot: StateSnapshot) -> dict[str, Any]:
        """基于快照回滚。返回回滚结果字典，必须包含 'status' 键。"""
        ...

    @abstractmethod
    def can_rollback(self) -> bool:
        """声明该 connector 是否支持回滚。"""
        ...

    @abstractmethod
    def compensating_action(self) -> str | None:
        """返回补偿动作描述。不支持则返回 None。"""
        ...
```

### 5.2 `ActionConnectorRegistry` 设计

位置: `packages/os_core/src/agent_os_core/action_connectors/registry.py`

```python
class ActionConnectorRegistry:
    def register(self, connector: ActionConnector) -> None: ...
    def get(self, connector_name: str) -> ActionConnector: ...  # 不存在时 raise KeyError
    def list_connectors(self) -> tuple[ActionConnectorContract, ...]: ...
```

要求:
- `register` 时校验 `connector.connector_name()` 与 `ActionConnectorContract.connector_name` 一致
- `get` 找不到时抛出 `KeyError`，不允许返回 None（失败必须显式）
- 默认注册 `ManualReviewConnector`

### 5.3 `ManualReviewConnector` 实现

位置: `action_connectors/manual_review/connector.py`

| 方法 | 行为 |
|------|------|
| `connector_name` | 返回 `"manual_review"` |
| `take_snapshot` | 返回 `None`（人工审批无需快照） |
| `execute` | 返回 `{"status": "pending_approval", "assigned_to": operation.approver_role}` |
| `rollback` | 返回 `{"status": "not_applicable", "reason": "manual_review has no side effects to rollback"}` |
| `can_rollback` | 返回 `False` |
| `compensating_action` | 返回 `None` |

注意: `manual_review` connector 不在 `packages/os_core/` 下，遵守 AGENTS.md 边界规则（os_core 不导入 action_connectors）。

---

## 6. `ActionGovernance` 增强需求

### 当前问题

`ActionGovernance.build_operation_contract()` 中:
- `target_connector="manual_review"` 硬编码
- `rollback_supported=False` 硬编码
- 未被 `TrustedLoopRuntime` 调用

### 变更要求

1. `build_operation_contract` 接收 `ActionProposal` 后:
   - 从 `proposal.connector_name` 获取 `ActionConnectorContract`
   - 用 `connector_contract.supports_rollback` 填充 `rollback_supported`
   - 用 `connector_contract.supports_snapshot` 填充 `snapshot_required`
   - 用 `connector_contract.compensating_action_description` 填充 `compensating_action`
   - 用 `proposal.connector_name` 填充 `connector_name`
   - 用 `proposal.action_type` 填充 `action_type`

2. `can_auto_execute` 逻辑不变，但需额外校验:
   - `operation.connector_name` 必须在 registry 中存在
   - `operation.action_type` 必须在 connector 的 `supported_action_types` 中

3. 新增方法 `should_snapshot(operation: OperationContract) -> bool`:
   - 返回 `operation.snapshot_required and operation.risk_level not in {"R0", "R1"}`

---

## 7. `OperationStateMachine` 需求

位置: `packages/os_core/src/agent_os_core/operation_state_machine.py`

### 合法状态转移

```
PROPOSED ──→ APPROVED ──→ SNAPSHOTTING ──→ EXECUTED ──→ OBSERVED
   │            │                              │
   │            │                              ├──→ FAILED
   │            │                              ├──→ ROLLING_BACK ──→ ROLLED_BACK
   │            │                              └──→ COMPENSATING ──→ OBSERVED
   │            │
   └──→ REJECTED                              ROLLED_BACK ──→ OBSERVED
```

### 接口

```python
class OperationStateMachine:
    def transition(self, current: OperationState, target: OperationState) -> OperationState:
        """校验状态转移合法性。合法则返回 target，非法则 raise InvalidStateTransition。"""
        ...

    def allowed_transitions(self, current: OperationState) -> tuple[OperationState, ...]:
        """返回当前状态允许的下一状态列表。"""
        ...
```

要求:
- `InvalidStateTransition` 为自定义异常，包含 `current` / `target` / `message` 信息
- 必须有针对非法转移的测试用例

---

## 8. `TrustedLoopRuntime` 集成需求

### 当前链路

```
BusinessIntent → IntentParser → SemanticRegistry → QueryPlan → SQLSafety → QueryResult
  → DataProductCompiler → EvidenceChainBuilder → ActionProposalBuilder → 返回
```

链路在 `ActionProposal` 处断开。

### 目标链路

```
BusinessIntent → IntentParser → SemanticRegistry → QueryPlan → SQLSafety → QueryResult
  → DataProductCompiler → EvidenceChainBuilder → ActionProposalBuilder
  → ActionGovernance.build_operation_contract()
  → [ActionGovernance.should_snapshot() → connector.take_snapshot() if needed]
  → ActionConnectorRegistry.get(connector_name)
  → [ApprovalLiteRuntime.create_pending() if approval_required]
  → connector.execute()
  → OperationTraceBuilder (open + update)
  → 返回 TrustedLoopResult
```

### 具体变更

1. `TrustedLoopRuntime.__init__` 新增参数:
   - `action_governance: ActionGovernance | None = None`
   - `connector_registry: ActionConnectorRegistry | None = None`
   - `approval_runtime: ApprovalLiteRuntime | None = None`
   - `operation_trace_builder: OperationTraceBuilder | None = None`
   - `state_machine: OperationStateMachine | None = None`

2. `TrustedLoopRuntime.run` 在 `action_builder.build()` 之后:
   - 调用 `self.action_governance.build_operation_contract(proposal)` 获得 `OperationContract`
   - 如果 `action_governance.should_snapshot(operation)`，调用 `connector.take_snapshot(operation)`
   - 通过 `self.connector_registry.get(proposal.connector_name)` 获取 connector
   - 如果 `operation.approval_required`，调用 `self.approval_runtime.create_pending()`
   - 调用 `connector.execute(operation, proposal.action_parameters)`
   - 调用 `self.operation_trace_builder` 记录完整生命周期
   - 将 `OperationContract` / `StateSnapshot` / 执行结果加入 `TrustedLoopResult`

3. `TrustedLoopResult` 新增字段:
   - `operation_contract: OperationContract | None = None`
   - `state_snapshot: StateSnapshot | None = None`
   - `action_result: dict[str, Any] | None = None`
   - `approval_record: ApprovalRecord | None = None`

4. 所有新字段有默认值 `None`，现有测试无需修改即可通过。

### 默认实例化

当外部不传入新依赖时:
- `action_governance` 默认 `ActionGovernance()`
- `connector_registry` 默认含 `ManualReviewConnector` 的 registry
- `approval_runtime` 默认 `ApprovalLiteRuntime()`
- `operation_trace_builder` 默认 `OperationTraceBuilder()`
- `state_machine` 默认 `OperationStateMachine()`

---

## 9. 向后兼容要求

| 约束 | 说明 |
|------|------|
| 现有测试全部通过 | `test_trusted_loop.py`、`test_contracts.py`、`test_architecture_contracts.py`、`test_sql_safety.py`、`test_observability.py` 不做任何修改即可通过 |
| 新字段有默认值 | `OperationContract` / `ActionProposal` / `TrustedLoopResult` 新增字段必须有默认值 |
| `recommended_action` 保留 | 不删除 `ActionProposal.recommended_action` 字段，仅新增 `connector_name` / `action_type` / `action_parameters` |
| `target_connector` 保留 | `OperationContract.target_connector` 保留，内部取值与 `connector_name` 同步，标记为 deprecated |
| `OperationState` 原有枚举不变 | PROPOSED / APPROVED / REJECTED / EXECUTED / OBSERVED 的值和顺序不变 |
| 导入路径不变 | `from agent_os_contracts import ...` 的公开 API 不变 |
| `ActionProposalBuilder` 输出兼容 | 新字段默认值使旧代码无需修改 |

---

## 10. 验收标准

### 10.1 链路贯通

- [ ] `TrustedLoopRuntime.run()` 从 `BusinessIntent` 到 connector `execute()` 的完整链路可运行
- [ ] trace_events 中包含 `operation_contract` / `action_governance` / `connector_execute` 步骤
- [ ] `TrustedLoopResult` 包含 `operation_contract` / `action_result` 非空值

### 10.2 路由能力

- [ ] `ActionProposal.connector_name = "manual_review"` 可正确路由到 `ManualReviewConnector`
- [ ] `ActionProposal.connector_name = "nonexistent"` 导致 `KeyError`，不静默失败
- [ ] `ActionProposal.action_type` 不在 connector 的 `supported_action_types` 中时校验失败

### 10.3 治理能力

- [ ] `ActionGovernance.build_operation_contract()` 输出 `snapshot_required` / `rollback_supported` / `compensating_action` 基于 connector 契约动态填充
- [ ] `ActionGovernance.should_snapshot()` 对 R0/R1 返回 `False`，对 R4/R5 且 `snapshot_required=True` 返回 `True`
- [ ] `OperationStateMachine.transition()` 对合法转移返回目标状态，对非法转移抛出 `InvalidStateTransition`

### 10.4 失败路径

- [ ] connector 未注册时，链路抛出明确异常（非 `None` 访问）
- [ ] 审批拒绝场景: `approval_required=True` 且审批记录为 rejected 时，不执行 connector
- [ ] 非法状态转移: `EXECUTED → PROPOSED` 抛出 `InvalidStateTransition`
- [ ] 快照失败: `take_snapshot()` 抛出异常时，operation 进入 `FAILED` 状态

### 10.5 向后兼容

- [ ] 所有现有测试（5 个测试文件）不做修改即可通过
- [ ] 不传新依赖时，`TrustedLoopRuntime` 仍可运行（使用默认实例）

### 10.6 禁止伪实现

- [ ] 每个新方法有真实逻辑，不是 `pass` / `return None` / 硬编码成功
- [ ] 每个新能力有对应测试，且测试断言非平凡（不是仅断言 fixture 值）
- [ ] `ManualReviewConnector.execute()` 返回真实 pending 状态，不是空操作

---

## 11. 待确认问题

| # | 问题 | 影响 | 建议 |
|---|------|------|------|
| 1 | `OperationContract.target_connector` 是否在本迭代直接删除，还是保留为 deprecated？ | 向后兼容 vs 代码清洁度 | 建议 MVP 保留为 deprecated，由 `connector_name` 驱动实际路由，后续迭代删除 |
| 2 | `ActionProposal.action_parameters` 的 schema 是否需要 connector 级别校验？ | 路由安全 | 建议 MVP 不做参数 schema 校验，由 connector 内部自行校验并抛异常 |
| 3 | `OperationStateMachine` 是否需要持久化？ | MVP 后续扩展 | 建议 MVP 仅内存实现，不持久化 |
| 4 | `manual_review` connector 的 `execute()` 是否需要阻塞等待审批结果？ | 运行时行为 | 建议 MVP 不阻塞，`execute()` 返回 pending 状态后由外部轮询或 webhook 驱动后续流程 |
| 5 | `StateSnapshot.state_payload` 的最大体积是否需要限制？ | 内存安全 | 建议 MVP 不限制，但 `StateSnapshot` 契约预留 `metadata.size_bytes` 字段用于后续治理 |
| 6 | `ApprovalLiteRuntime` 是否需要从"仅 create_pending"扩展为支持 approve/reject？ | 治理完整性 | 建议 MVP 扩展 `approve()` / `reject()` 方法，否则审批环节是死路，链路无法真正贯通 |
| 7 | connector 路由失败（`KeyError`）时，`TrustedLoopRuntime.run()` 应该抛异常还是返回带错误信息的 result？ | 调用方体验 | 建议抛异常，与现有 `ValueError("SQL safety check failed")` 模式一致 |

---

## 附录 A: 变更文件清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `packages/contracts/src/agent_os_contracts/architecture.py` | 修改 | `OperationContract` 新增字段、`OperationState` 新增枚举、新增 `StateSnapshot`、新增 `ActionConnectorContract` |
| `packages/contracts/src/agent_os_contracts/trusted_loop.py` | 修改 | `ActionProposal` 新增字段、`TrustedLoopResult` 新增字段 |
| `packages/contracts/src/agent_os_contracts/__init__.py` | 修改 | 导出新契约 |
| `packages/os_core/src/agent_os_core/action_connectors/base.py` | 新增 | `ActionConnector` ABC |
| `packages/os_core/src/agent_os_core/action_connectors/registry.py` | 新增 | `ActionConnectorRegistry` |
| `packages/os_core/src/agent_os_core/action_connectors/__init__.py` | 新增 | 导出 |
| `packages/os_core/src/agent_os_core/action_governance/__init__.py` | 修改 | 增强逻辑 |
| `packages/os_core/src/agent_os_core/approval_lite/__init__.py` | 修改 | 新增 `approve()` / `reject()` |
| `packages/os_core/src/agent_os_core/operation_trace/__init__.py` | 修改 | 增强 trace 生命周期记录 |
| `packages/os_core/src/agent_os_core/operation_state_machine.py` | 新增 | `OperationStateMachine` + `InvalidStateTransition` |
| `packages/os_core/src/agent_os_core/trusted_loop.py` | 修改 | 集成新依赖 |
| `packages/os_core/src/agent_os_core/action_proposal/__init__.py` | 修改 | 输出结构化字段 |
| `packages/os_core/src/agent_os_core/__init__.py` | 修改 | 导出新模块 |
| `action_connectors/manual_review/connector.py` | 新增 | `ManualReviewConnector` |
| `action_connectors/manual_review/__init__.py` | 新增 | 导出 |
| `tests/unit/test_operation_state_machine.py` | 新增 | 状态机测试 |
| `tests/unit/test_action_connector.py` | 新增 | connector ABC + registry 测试 |
| `tests/unit/test_manual_review_connector.py` | 新增 | manual_review connector 测试 |
| `tests/unit/test_trusted_loop.py` | 修改 | 新增贯通测试（不破坏现有测试） |

## 附录 B: 架构约束引用

本文档遵循 `AGENTS.md` 中的硬边界:

- OS Core 不导入 `action_connectors/`（connector 通过 registry 注入）
- R4/R5 业务动作在 MVP 中仍为 proposal-only（通过 `manual_review` connector 路由到人工审批）
- 所有新增能力必须有真实调用路径 + 失败路径
- 禁止伪实现（空壳、硬编码成功、仅断言 fixture 值的测试）
