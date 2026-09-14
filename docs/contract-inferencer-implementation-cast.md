# Contract Inferencer — Implementation Cast (技术可行性审查)

**Status**: DRAFT — implementation-cast, pre-implementation
**Spec**: `docs/contract-inferencer-spec.md` v0.3
**Reviewer**: implementation-cast (builder_id != reviewed_by per §13)
**Date**: 2026-08-21

---

## 0. Verdict

Spec v0.3 可实现。无架构性阻断。但有 **三个硬集成点** 比 spec §13 组件接口描述的更侵入：

1. **判定路径有三处 pytest 硬编码**，不止 `DeterministicOutcomeEvaluator` 一处——`expected_outcome_contract_error()` 和 `TaskService.record_outcome()` 的 VERIFIED 分支同样硬编码，必须一起改，否则 predicate outcome 无法持久化。
2. **证据收集面不够**——`_collect_evidence()` 只收 artifact IDs + exit code；TOOL_RESPONSE / STATE_DELTA / ARTIFACT_CONTENT 需要新的证据访问器，且 STATE_DELTA 需要 run 启动前的基线快照（当前不存在）。
3. **Provider 无 structured output 保证**——`OpenAICompatibleProvider` 不发 `response_format`，SemanticProposer 必须自己做防御性 JSON 解析 + Pydantic 校验，解析失败路径需在 spec 中明确（当前 spec 未覆盖 LLM 返回不可解析的情况）。

其余部分（类型定义、五阶段管线、澄清/确认状态机、freeze 门、append-only 历史）均为新增代码，不触碰现有执行路径，风险低。

---

## 1. 类型放置

### 1.1 新增合约类型

**位置**: `packages/contracts/src/agent_os_contracts/contract_inference.py`（新文件）

所有新类型遵循现有约定：`ContractModel`（frozen=True, extra="forbid", schema_version="1.0"），枚举用 `str, Enum`，ID 用 `NonEmptyStr`，时间用 `UtcDateTime`。

| 类型 | 说明 |
|---|---|
| `CheckType` | str Enum: TYPE/RANGE/ENUM/REGEX/CARDINALITY/FIELD_PRESENCE/STATE_DELTA/TOOL_RESPONSE/ARTIFACT_EXISTS/ARTIFACT_CONTENT/CROSS_CONSISTENCY/LLM_JUDGE |
| `PredicateKind` | str Enum: STRUCTURAL/SEMANTIC/CONFIRMED/PROMOTED |
| `SuccessPredicate` | predicate_id, check_type, target, check_params(dict), blocking(bool), kind, source, confidence, description, scope_tags |
| `PredicateConfirmation` | confirmation_id, predicate_id, decision(APPROVE/REJECT/ADJUST), adjusted_predicate(SuccessPredicate \| None), decided_by, decided_at, reason, pre_endorsed(bool) |
| `ClarificationQuestion` | question_id, question, options(tuple[str,...] \| None), default_answer, predicate_ids_affected |
| `ClarificationAnswer` | question_id, answer(str) |
| `PipelineState` | str Enum: QUESTIONS_PENDING/CONFIRMATION_PENDING/FROZEN/REJECTED |
| `InferenceStage` | str Enum: NORMALIZE/MECHANICAL_EXTRACT/SEMANTIC_PROPOSE/QUALITY_GATE |
| `ContractInferenceResult` | inference_id, mandate_digest, tool_schema_digests, predicates, questions, pipeline_state, stage, quality_gate_report, created_at |
| `PredicateEvaluationResult` | predicate_id, passed(bool \| None), evidence_refs, detail |

**导出**: 在 `packages/contracts/src/agent_os_contracts/__init__.py` 中导入并加入 `__all__`。

### 1.2 与现有类型的关系

- **不修改** `ExpectedOutcome`。freeze 时物化一个 `ExpectedOutcome` 实例：
  - `evaluator_type = "predicate:conjunction"`（spec §11.1）
  - `evaluator_version = "1"`
  - `evidence_requirements` = 从 blocking 谓词的 target/check_type 推导（如 `("tool-response", "artifact")`）
  - `failure_semantics = ("blocking predicate failed",)`
  - `threshold = 1.0`（合取语义：全过才 VERIFIED）
  - 谓词集合本身存在哪？见 §1.3。

- **不修改** `Commitment.acceptance_criteria`（当前是 `tuple[NonEmptyStr, ...]` 自由文本）。推断器产出的结构化谓词不塞进这个字段——它是遗留自由文本字段，强行塞 JSON 会破坏类型语义。

### 1.3 谓词集合的持久化（已决策）

**决策：content-addressed digest 作为 evaluator_version + 专用 SQLite store。**

- 新建 `SQLitePredicateSetStore`（新文件 `predicate_set_store.py`），仿 `SQLiteMandateWorkspaceStore` 模式：同 SQLite 库新表 `predicate_sets`，键 `(tenant_id, workspace_id, predicate_set_digest)`，存 `canonical_json(PredicateSet)` + digest。写入在 freeze 时（assembly-time，pre-commit），读取在 verdict 时。
- `ExpectedOutcome` 不修改：
  - `evaluator_type = "predicate:conjunction"`
  - `evaluator_version = <PredicateSet content digest>`（digest 即版本号，content-addressed）
  - `evidence_requirements = ("predicate-set",)`
  - `failure_semantics = ("blocking predicate failed",)`
  - `threshold = 1.0`
- 判定时 `PredicateConjunctionEvaluator` 用 `expected.evaluator_version` 作 key 从 store 加载 PredicateSet。
- 不修改 `TaskConfigurationSnapshot`（严格类型化 frozen 模型，无 opaque bag，加字段需改全量校验）。
- 不修改 `Commitment.acceptance_criteria`（自由文本遗留字段，不塞 JSON）。

**为什么不走 TaskService.record_artifact()**：该路径（task_service.py L1393-1423）要求 active run + action receipt 绑定，是 run-time 专属；PredicateSet 是 assembly-time 工件，走它会污染 run 证据链。

**为什么不扩展 ExpectedOutcome 加字段**：加 `predicate_set_digest` 字段需迁移核心合约类型 + 全量回归；用 evaluator_version 承载 digest 是零修改方案，且语义正确（合取判定器的配置版本就是谓词集合的内容哈希）。

---

## 2. 判定路径——三处 pytest 硬编码（最硬集成点）

### 2.1 现状

pytest 假设散布在 **三个** 位置，spec §13 只提到了第一处：

**位置 1: `DeterministicOutcomeEvaluator.evaluate()`**
`packages/os_core/src/agent_os_core/execution.py` L83-187

- L99-100: 调 `expected_outcome_contract_error(expected)` 拒绝非 pytest
- L105-111: 只识别 `artifact:` 前缀证据
- L113-118: 解析 `ValidatedTestReport`，检查 exit code
- 整个方法体是 pytest 专属逻辑

**位置 2: `expected_outcome_contract_error()`**
`packages/os_core/src/agent_os_core/task_service.py` L83-97

```python
if (expected.evaluator_type, expected.evaluator_version) != PYTEST_EVALUATOR_IDENTITY:
    return "unsupported evaluator"
if tuple(expected.evidence_requirements) != PYTEST_EVIDENCE_REQUIREMENTS:
    return "unsupported evidence requirements"
if not set(expected.failure_semantics).issubset(PYTEST_FAILURE_SEMANTICS):
    return "unsupported failure semantics"
```

这是模块级函数，被两处调用（evaluate 内三次分支判断）：
- `DeterministicOutcomeEvaluator.evaluate()` (execution.py L121/125/130)
- `TaskService.record_outcome()` (task_service.py L1281)

**位置 3: `TaskService.record_outcome()` VERIFIED 分支**
`packages/os_core/src/agent_os_core/task_service.py` L1289-1339

- L1291: `score != 1.0` → "verified outcome score does not match the trusted pytest score"
- L1319: `self.validated_test_report(task_id, run.run_id)` 必须返回非 None
- L1324-1331: 证据必须包含 test report artifact，exit code 必须 0
- L1332-1338: 时间窗口检查（这部分是通用的，可保留）

此外 `TaskService.current_outcome()` (L274-320) 也调 `validated_test_report()` 做新鲜度检查。

### 2.2 改造方案：评估器注册表

引入评估器协议 + 注册表，替换硬编码分发：

```python
# 新文件: packages/os_core/src/agent_os_core/outcome_evaluators.py

class OutcomeEvaluator(Protocol):
    evaluator_type: str
    evaluator_version: str

    def contract_error(self, expected: ExpectedOutcome) -> str | None:
        """验证 ExpectedOutcome 字段是否被此评估器支持。"""
        ...

    def evaluate(
        self,
        expected: ExpectedOutcome,
        *,
        task_id: str, run_id: str, tenant_id: str, workspace_id: str,
        evidence_refs: tuple[str, ...],
        evidence_accessor: EvidenceAccessor,  # 见 §3
        now: datetime,
    ) -> ObservedOutcome:
        ...

    def verify_verified_recording(
        self,
        expected: ExpectedOutcome,
        outcome: ObservedOutcome,
        *,
        tasks: TaskService,
        task_id: str,
        run_id: str,
    ) -> None:
        """record_outcome VERIFIED 分支的评估器专属校验。
        不通过抛 InvalidTransitionError。"""
        ...
```

- `PytestOutcomeEvaluator`：封装现有 `DeterministicOutcomeEvaluator` 逻辑（提取为类，保持行为不变）。
- `PredicateConjunctionEvaluator`：新增，从 artifact 读取 `PredicateSet`，逐个执行 check_type 对应的检查函数，合取判定。
- `DeterministicOutcomeEvaluator` 保留为门面（facade），内部持有注册表并按 `evaluator_type` 分发——保持现有构造函数签名 `DeterministicOutcomeEvaluator(evidence_resolver)` 不破坏现有测试。

**`expected_outcome_contract_error()` 改造**：

- 保留函数签名但改为查注册表：`registry.contract_error(expected)`。
- 或标记为 deprecated，让两个调用方改用注册表。建议直接改，因为只有两个调用点。

**`record_outcome()` 改造**：

- L1281 的 `expected_outcome_contract_error(expected)` 改为 `registry.contract_error(expected)`。
- L1289-1339 的 pytest 专属 VERIFIED 校验提取到 `PytestOutcomeEvaluator.verify_verified_recording()`。
- 通用检查（时间窗口 L1299-1318、scope 绑定 L1271-1280）留在 `record_outcome()`。
- `current_outcome()` 的新鲜度检查同理分发。

**风险**：这是改动面最大的部分，触碰核心持久化路径。但现有测试（`test_outcome_evaluator.py`、`test_long_horizon_task_service.py` 等）提供了安全网——改造后这些测试必须全绿，行为不变。

### 2.3 谓词检查函数注册表

`PredicateConjunctionEvaluator` 需要按 `CheckType` 分发到具体检查函数：

```python
class PredicateChecker(Protocol):
    def check(
        self,
        predicate: SuccessPredicate,
        *,
        evidence_accessor: EvidenceAccessor,
    ) -> tuple[bool | None, tuple[str, ...], str]:
        """返回 (passed, evidence_refs_used, detail)。
        passed=None 表示 UNRESOLVED（证据不足）。"""
        ...
```

MVP 实现的 checker：

| CheckType | 实现 |
|---|---|
| TYPE / RANGE / ENUM / REGEX / CARDINALITY / FIELD_PRESENCE | 纯函数，对 evidence_accessor 返回的 JSON 值做校验 |
| ARTIFACT_EXISTS | 检查 artifact ID 存在于 evidence_refs |
| ARTIFACT_CONTENT | 读取 artifact 内容，按 check_params 做 JSONPath/regex 匹配 |
| TOOL_RESPONSE | 从 evidence_accessor 取指定 tool_name 的最近一次调用结果，校验返回值 |
| CROSS_CONSISTENCY | 取多个证据值，按 check_params 中的一致性规则校验 |
| STATE_DELTA | 需要基线快照（见 §3.2）；MVP 无基线时返回 None (UNRESOLVED) |
| LLM_JUDGE | advisory only，不阻断；调用 cross-family judge 模型 |

---

## 3. 证据收集

### 3.1 现状

证据收集内联在 `RunCoordinator` 的执行循环中（execution.py L394-406，无具名方法）：

```python
                    result = self._actions.execute(
                        action, principal,
                        capability_spec=self.sandbox.specs().get(capability_id),
                        approval=aggregate.approval,
                    )
                    context[node.node_id] = result.output
                    context[capability_id or node.node_id] = result.output
                    evidence.extend(str(item) for item in result.receipt.output_artifact_ids)
                    context["evidence_refs"] = tuple(evidence)
                    if node.capability == "workspace.run_tests":
                        exit_code = _strict_exit_code(result.output)
                        if exit_code is not None:
                            test_exit_codes[node.node_id] = exit_code
```

只收集：artifact IDs（`evidence` 列表）+ test exit codes（`test_exit_codes` dict）。

`OutcomePipeline.evaluate()` 签名只传 `evidence: tuple[str, ...]` 和 `test_exit_code: int | None`。

`DeterministicOutcomeEvaluator` 通过 `evidence_resolver: Callable[[str, str], ValidatedTestReport | None]` 回调访问 task event store，解析 test report。

### 3.2 需要的新证据访问器

谓词检查需要访问的不只是 artifact ID 和 exit code：

| 证据类型 | 来源 | 谓词 check_type |
|---|---|---|
| artifact 内容 | `artifact_reader(artifact_id) -> bytes \| None`（已有，TaskService 持有） | ARTIFACT_CONTENT, TYPE/RANGE/ENUM/REGEX on artifact JSON |
| tool 调用参数+结果 | NODE_COMPLETED 事件的 `output` dict（execution.py L399: `context[node.node_id] = result.output`，持久化在事件中）+ ACTION_PROPOSED 事件的 `action.arguments_json` | TOOL_RESPONSE, CROSS_CONSISTENCY |
| env 状态快照 | 需要新机制：run 启动前捕获 + run 结束后捕获 | STATE_DELTA |
| test exit code | 已有 | （pytest 专属，谓词不需要） |

**已确认**：tool 输出在 NODE_COMPLETED 事件的 `payload["output"]` 中持久化（dict，含 `artifact_ids`/`exit_code`/`path` 等 tool-specific 字段）。`EvidenceAccessor.tool_result(tool_name)` 通过读 event store 实现：找到 capability 匹配的 TOOL 节点的 NODE_COMPLETED 事件，返回其 output dict + 对应 ACTION_PROPOSED 的 arguments。**无需新持久化路径。** ActionReceipt 只存 `output_artifact_ids`（不内联输出内容），但 NODE_COMPLETED output 已覆盖。

**设计**: 引入 `EvidenceAccessor` 协议，替代当前的 `evidence_resolver` 窄回调：

```python
class EvidenceAccessor(Protocol):
    def artifact_content(self, artifact_id: str) -> bytes | None: ...
    def tool_result(self, tool_name: str, *, latest: bool = True) -> ToolCallEvidence | None: ...
    def state_snapshot(self, label: str) -> dict | None: ...
```

实现由 `RunCoordinator` 在 EVALUATION 节点构造，包装 `TaskService`（读 event store）+ `artifact_reader` + 基线快照存储。

**`OutcomePipeline.evaluate()` 签名扩展**：

当前签名传 `evidence: tuple[str, ...]` + `test_exit_code: int | None`。改为传 `evidence_accessor: EvidenceAccessor`（或两者并存，pytest 路径保持旧签名，predicate 路径用 accessor）。

建议：`OutcomePipeline` 构造时注入 `EvidenceAccessor` 工厂，evaluate 时构造 accessor 传给 evaluator。旧的 `evidence` + `test_exit_code` 参数保留给 pytest evaluator 使用。

### 3.3 STATE_DELTA 基线快照（新机制）

当前没有 run 启动前的环境快照机制。MVP 方案（与 spec §16 开放问题 2 一致）：

- STATE_DELTA 谓词可被提案和确认，但判定时若无基线快照 → 返回 UNRESOLVED（不 FAIL 不 PASS）。
- 基线快照作为后续工作项：在 workflow 的第一个节点前插入一个 `SNAPSHOT` 节点类型，或在 `start_run` 时捕获。
- 这意味着 MVP 中 STATE_DELTA 谓词实际上不阻断（因为总是 UNRESOLVED），但不会错误地 FAIL。

---

## 4. LLM 调用面

### 4.1 ProviderPort

`packages/os_core/src/agent_os_core/provider.py`

- `ProviderPort.complete(ProviderRequest) -> ProviderResponse | ProviderFailure`：SemanticProposer 用这个。
- `ProviderPort.decide(ProviderDecisionRequest)`：用于 capability-bound 决策（校验 invocation binding digest），**推断器不用这个**——推断是 pre-commit 装配，不是 capability 执行。
- `DeterministicProvider`：hermetic 测试用，支持 `scripted: tuple[tuple[str, tuple[ProviderToolProposal, ...]], ...]` 按调用顺序返回预设响应。SemanticProposer 的测试用这个。

### 4.2 ProviderRequest / ProviderResponse 结构

- `ProviderRequest.messages: tuple[ProviderMessage, ...]`——每个 message 有 role（SYSTEM/USER/ASSISTANT/TOOL）、content、tool_calls。
- `ProviderResponse.text: str`——LLM 返回的文本。
- `ProviderResponse.tool_proposals`——function calling 返回。推断器不用 tool calling，用 text 中的 JSON。

### 4.3 无 structured output 保证

`OpenAICompatibleProvider._invoke()` (L366-378) 构造 body 时只发 model/messages/temperature/tools/tool_choice，**不发 `response_format`**。

这意味着：
- SemanticProposer 必须在 prompt 中要求 JSON 输出，然后防御性解析 `response.text`。
- 解析失败（非 JSON / schema 不匹配）的处理路径：
  1. 重试一次（带错误反馈）；
  2. 仍失败 → pipeline 进入 REJECTED 或返回 `quality_gate_report` 标记 LLM_FAILURE，不产出谓词。
- **建议 spec 补充**：§6 Quality Gate 应增加 "LLM response unparseable after 1 retry → fatal, no predicates proposed" 的失败路径。这与 §8.2 "零谓词过 Q1-Q3" 的 fatal 一致，但原因不同（LLM 失败 vs 全部被过滤）。

### 4.4 judge 模型 cross-family

spec §16 开放问题 6：LLM_JUDGE 的 judge 模型应与 proposer 不同家族。实现上 `SemanticProposer` 和 `JudgeClient` 各自接收独立的 `ProviderPort` 实例（可配置不同 model/base_url）。MVP 中 LLM_JUDGE 是 advisory only，不阻断，所以 judge 不可用时 verdict 返回 UNRESOLVED 即可。

---

## 5. 推断器位置——pre-commit 组件

### 5.1 不在 workflow 内

推断器在 `TaskService.commit_task()` **之前**运行，与 `mandate_steward.py`、`task_configuration.py` 同层（装配时组件，非运行时节点）。

调用流程：

```
Mandate + tool schemas
    → ContractInferencer.infer()                    # Stage 0-3, 一次 LLM
    → ContractInferencer.apply_clarification()      # 纯变换
    → ContractInferencer.apply_confirmation()       # 纯变换 + freeze
    → 产出: ExpectedOutcome + PredicateSet artifact + WorkflowGraph
    → TaskService.commit_task(commitment, workflow, expected_outcome)
```

### 5.2 与现有 Mandate 接收路径的关系

`MandateSteward` / `mandate_steward.py` 负责 Mandate 的持久接收、重放、冲突 fail-closed（已实现）。推断器消费已接收的 Mandate，不重复实现接收逻辑。

### 5.3 WorkflowGraph 产出

freeze 后推断器还需产出一个 `WorkflowGraph`（当前 `commit_task` 要求手写）。MVP 方案：
- 推断器产出一个最小 workflow：PROVIDER 节点（执行任务）→ EVALUATION 节点（判定）。
- 工具选择：从 Mandate + tool schemas 推导 allowed capability IDs（这本身是一个简化的规划问题，MVP 可让 LLM 在 Stage 2 同时提案工具选择，或简单地把所有传入的 tool schemas 都 allow）。

---

## 6. 文件级变更清单

### 6.1 新增文件

| 文件 | 内容 |
|---|---|
| `packages/contracts/src/agent_os_contracts/contract_inference.py` | §1.1 全部新类型 |
| `packages/os_core/src/agent_os_core/contract_inferencer.py` | `ContractInferencer` 五阶段管线、三段 API、状态机 |
| `packages/os_core/src/agent_os_core/contract_inference_llm.py` | `SemanticProposer`（LLM 调用 + JSON 解析）、`MechanicalExtractor`（schema 推导） |
| `packages/os_core/src/agent_os_core/outcome_evaluators.py` | `OutcomeEvaluator` 协议、`OutcomeEvaluatorRegistry`、`PytestOutcomeEvaluator`（从 execution.py 提取）、`PredicateConjunctionEvaluator` |
| `packages/os_core/src/agent_os_core/predicate_checkers.py` | 各 CheckType 的 checker 实现 |
| `packages/os_core/src/agent_os_core/evidence_accessor.py` | `EvidenceAccessor` 协议 + run 时实现 |
| `packages/os_core/src/agent_os_core/predicate_set_store.py` | `SQLitePredicateSetStore`（assembly-time 谓词集合持久化，仿 `SQLiteMandateWorkspaceStore`） |
| `tests/product/test_contract_inferencer.py` | 管线、状态机、澄清/确认/freeze 测试 |
| `tests/product/test_predicate_evaluator.py` | 判定 dispatch、各 checker、合取语义测试 |

### 6.2 修改文件

| 文件 | 变更 |
|---|---|
| `packages/contracts/src/agent_os_contracts/__init__.py` | 导出新类型 |
| `packages/os_core/src/agent_os_core/__init__.py` | 导出 `ContractInferencer`、`OutcomeEvaluatorRegistry` 等 |
| `packages/os_core/src/agent_os_core/execution.py` | `DeterministicOutcomeEvaluator` 改为门面，内部分发到注册表；TOOL 节点证据收集内联逻辑（L394-406）扩展收集 tool results |
| `packages/os_core/src/agent_os_core/task_service.py` | `expected_outcome_contract_error()` 改为注册表查询；`record_outcome()` VERIFIED 分支分发到 evaluator.verify_verified_recording()；`current_outcome()` 同理 |
| `packages/os_core/src/agent_os_core/outcome_pipeline.py` | `evaluate()` 支持传入 EvidenceAccessor |

### 6.3 不修改的文件

- `governance.py`（PolicyKernel/CorrectionAuthority）——推断器不触碰授权逻辑
- `provider.py`——不扩展 ProviderPort，SemanticProposer 用现有 complete()
- `mandate.py`、`task.py`、`outcome.py`、`evaluator.py`（contracts 包）——不修改现有合约类型
- `graph_scheduler.py`、`node_handlers.py`——EVALUATION 节点已有，不改调度

---

## 7. 实现顺序（依赖序）

按宪法 §7.9 separated status，每步独立可测：

1. **合约类型**（specified → implemented → tested）
   - `contract_inference.py` 新类型 + Pydantic 校验
   - 单元测试：类型构造、ID 内容派生、frozen 不可变、extra forbid

2. **MechanicalExtractor**（纯函数，无 LLM）
   - 从 JSON Schema 推导 TYPE/FIELD_PRESENCE/ENUM/RANGE/CARDINALITY 结构谓词
   - 单元测试：给定 schema 产出预期谓词

3. **评估器注册表 + Pytest 提取**（重构，行为不变）
   - 提取 `PytestOutcomeEvaluator`，建注册表
   - `DeterministicOutcomeEvaluator` 改为门面
   - `expected_outcome_contract_error()` 改注册表
   - **全量现有测试必须绿**——这是重构安全网

4. **PredicateConjunctionEvaluator + 基础 checker**
   - TYPE/RANGE/ENUM/REGEX/CARDINALITY/FIELD_PRESENCE/ARTIFACT_EXISTS/ARTIFACT_CONTENT
   - 合取语义、UNRESOLVED 传播
   - 单元测试：全过→VERIFIED、一个 FAIL→NOT_MET、证据不足→UNRESOLVED

5. **EvidenceAccessor + 证据收集扩展**
   - artifact_content、tool_result
   - `_collect_evidence` 扩展
   - OutcomePipeline 签名扩展

6. **SemanticProposer**（LLM 调用）
   - prompt 构造、JSON 防御解析、schema 校验、重试
   - 用 DeterministicProvider scripted 测试

7. **ContractInferencer 五阶段 + 三段 API**
   - infer() / apply_clarification() / apply_confirmation()
   - 状态机、Q1-Q3 质量门、双 freeze 门、E-7 绕过检测
   - 单元测试：spec §15 全部测试用例（Q-1..Q-7, C-1..C-8, E-1..E-8）

8. **record_outcome 分发**
   - VERIFIED 分支分发到 evaluator.verify_verified_recording()
   - current_outcome() 分发
   - 集成测试：predicate outcome 可持久化、可重放

9. **LLM_JUDGE checker**（advisory）
   - cross-family judge client
   - advisory 不阻断

10. **端到端冒烟**
    - 一个简单 Mandate（如"创建文件 X 包含内容 Y"）→ infer → clarify → confirm → freeze → commit → run → verdict

---

## 8. 风险与需决策项

### 8.1 高风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| `record_outcome()` 改造破坏 pytest 路径 | 现有 SPINE-0 和所有 outcome 持久化中断 | 步骤 3 先做纯重构，全量测试绿后再动；pytest 路径行为逐字节不变 |
| LLM 返回不可解析 | infer() 无法产出谓词 | spec 补充失败路径（§4.3）；1 次重试后 fatal；不静默空过 |
| STATE_DELTA 无基线 | 该类谓词永远 UNRESOLVED | MVP 接受；spec §16 已记录为开放问题；不在 MVP 承诺 STATE_DELTA 阻断能力 |

### 8.2 中风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| PredicateSet artifact 写入时机 | ~~需决策~~ **已决策（§1.3）**：新建 `SQLitePredicateSetStore`，digest 作 evaluator_version，不修改 ExpectedOutcome/TaskConfigurationSnapshot | 新建一张 SQLite 表 + 读写接口，仿现有 `SQLiteMandateWorkspaceStore` 模式，风险低 |
| 置信度阈值 0.7 无数据依据 | Q1 过滤过松或过紧 | spec §16 已记录；MVP 硬编码，held-out 校准 |
| NODE_COMPLETED output 无 schema 约束 | 不同 tool 的 output dict 结构不同，checker 需防御性解析 | checker 对缺失字段返回 UNRESOLVED 而非 FAIL；MVP 只支持 workspace.* 工具的已知 output 形状 |

### 8.3 需 spec 补充

1. **LLM 不可解析响应的失败路径**（§4.3）——1 次重试后 fatal，pipeline_state=REJECTED，quality_gate_report 记录 LLM_PARSE_FAILURE。
2. **PredicateSet 持久化方式**（§1.3）——推荐选项 A（freeze artifact），需确认 assembly-time artifact 存储机制是否存在，或需要新建。
3. ~~tool_result 证据可用性~~ **已确认**：NODE_COMPLETED 事件的 `payload["output"]` 持久化了 tool 输出 dict（execution.py L399），ACTION_PROPOSED 事件持久化了 `arguments_json`。EvidenceAccessor 通过 event store 读取，无需新持久化。

### 8.4 不在 MVP 范围（明确排除）

- 自动 WorkflowGraph 规划（MVP 产出最小固定形状 graph）
- STATE_DELTA 基线快照（MVP UNRESOLVED）
- promotion 闭环（纠偏→条款进库）——spec §12 correction hook 是接口预留，不接 ADM-P1..P4
- 跨域条款检索/继承（spec §5.4 第四层供给源，MVP 只做机械抽取 + LLM 提案）
- LLM_JUDGE 阻断能力（永远 advisory）

---

## 9. 与宪法的对齐检查

| 宪法条款 | 对齐情况 |
|---|---|
| C7（模型不持有最终执行权） | Stage 4.5 确认门是唯一种 CONFIRMED/blocking 的地方；LLM 提案默认 PENDING/advisory；语义 predicate_id 内容派生并去重（模型不能选择/碰撞 id，避免一次确认复用覆盖多个谓词）；E-7 双点绕过检测（放行显式确认、operator adjust 与 operator 预背书） |
| §7.4（typed contract + 失败路径） | 所有新类型 ContractModel；每个 check_type 有 UNRESOLVED/FAIL 路径；非法 evaluator fail-closed |
| §7.9（separated status） | 本文档 §7 按 specified/implemented/tested 分步；实现时每步独立提交 |
| §13（builder_id != reviewed_by） | 本审查由 implementation-cast 角色完成，与 spec 作者不同 |
| RR-0024（主张纪律） | MVP 不主张自治；M-1 kill criterion（省时间）是可证伪指标 |
| ADR-0033 L4（运行时自修改关闭） | 推断器在 commit 前运行，freeze 后谓词不可变；不涉及运行时自修改 |
| ADR-0037 SD4（禁止） | 推断器产出有界子目标（谓词），不自治执行；执行仍由 RunCoordinator + PolicyKernel 门控 |
