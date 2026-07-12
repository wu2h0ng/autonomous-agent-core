# Agent OS E0/E1/E2 长程任务收敛设计

> Date: 2026-07-12
> Track: Product
> Status: Founder-authorized design; implementation approved, research experiment run not authorized by this document
> Implementation branch: `codex/agent-os-e2e-long-horizon-20260712`
> Baseline checkpoint: `065ff8b` (`96 passed, 1 skipped`; Ruff/Pyright clean)

## 0. 决策

本轮不建设第二套 agent runtime，也不把 CWM 等研究器官直接接入产品。实施对象是现有
Agent OS Product Track 的一个受限长程闭环：

```text
Goal -> Commitment -> WorkflowGraph(vN) -> AgentRun
  -> completed dependency prefix
  -> WAIT_EVENT -> ExternalSignal -> resume
  -> bounded human-authorized WorkflowGraph(vN+1) rebind
  -> typed Action -> Evidence -> ObservedOutcome
  -> failure/NOT_MET -> governed durable compensation
```

它把现有 SPINE-0 从“可恢复的单次开发者链”推进为“可等待、可过期、可受限改计划、
可验证回滚的本地持久任务链”。它仍然只证明一个 Product Track local slice：不证明完全
自治、长期能力收益、通用智能或 `LH-RECOVERY-1` 已通过。

## 1. E0 / E1 / E2 边界

| 层级 | 本轮定义 | 完成条件 | 明确不声称 |
|---|---|---|---|
| E0 状态收敛 | 把已验证但未提交的 SPINE-0 产品基线固定为独立 checkpoint，并隔离研究脏改动 | 产品基线有独立 commit、干净 worktree、权威状态与测试一致 | 不改变 Research Track verdict，不执行 SPINE-1 |
| E1 有效产品仪器 | 一条 canonical event stream 同时驱动 API/CLI/Task Workspace 投影，并可计算恢复投影 | wait/signal/replan/compensation/outcome 全部有类型化事件、重放和负路径 | 不把测试次数当长程收益，不运行未冻结研究实验 |
| E2 受限长程闭环 | 外部事件等待、双层期限、DAG 阻塞、一次受限重规划、失败补偿、进程重启恢复 | 真实 SQLite + 真实工作区副作用的端到端测试通过 | 不实现后台调度集群、任意循环、自动 LLM 重规划、自我修改 |

`docs/research/AGENT-OS-PRODUCT-GROUNDED-EXPERIMENT-MATRIX.yaml` 中的
`LH-RECOVERY-1` 仍是未预注册、未冻结、未运行的 translational experiment。本轮只完成其
产品前置件和本地接受测试。

## 2. 复用资产，而不是重建

本轮直接消费以下已存在资产：

- `WorkflowGraph` 的 DAG、terminal-reachability 与 canonical digest；
- `NodeKind.WAIT_EVENT`、`NodeSpec.timeout_seconds`、`IdempotencyMode.COMPENSATABLE`；
- `TaskAggregate.rehydrate()` 和 append-only `TaskEvent`；
- SQLite optimistic sequence、idempotency key、lease/fence 与 correction epoch；
- `RunCoordinator` 的恢复上下文、已完成节点跳过和单一 API/CLI 执行路径；
- `PolicyKernel -> ActionPermit -> CapabilityBroker -> ActionReceipt` 权限脊柱；
- `WorkspaceSandbox` 的 path confinement、apply snapshot 原语与真实 pytest 能力；
- `ExpectedOutcome -> DeterministicOutcomeEvaluator -> ObservedOutcome`；
- `T-P-OS-SPINE-0-ARCHITECTURE-PACKET.md` 的 D3、D5、D8、D9、D13、D14。

OpenCode 的只读代码审查确认上述四个缝已有真实占位：WAIT_EVENT、timeout、DAG、
compensation primitive；其输出保存在 run-local
`agent_streams/sess-opencode-codepath-audit.jsonl`。本设计采纳其竞态与重放风险，但拒绝
三项扩大复杂度的建议：不新增 `WAITING_SIGNAL`（复用 `WAITING_EVENT`）、不新增第二张
signal 真相表（事件流即权威）、不允许引擎或 LLM 自动选择新计划。

Kimi 的对抗审查初始结论是 `REVISE`，指出三个恢复缺口：C7 可能阻断自动补偿、没有
durable snapshot 的 patch 会留下脏状态、wait deadline 可能随 Commitment 更新漂移。
本设计据此冻结三条修订：snapshot 必须先持久化成功才能写目标文件；C7 继续阻断自动
补偿，但外部 principal 可在显式恢复 correction epoch 后请求同一 governed compensation；
Commitment 没有更新路径，wait deadline 登记即冻结，replan 也不能修改 Commitment。

## 3. 非目标

- 不实现 `LOOP`、`PARALLEL_MAP`、`SUBWORKFLOW`；它们继续显式 `UnsupportedNodeError`。
- 不实现 Cron、分布式 scheduler、Kafka、Temporal 或 worker 集群。
- 不实现一般 shell、任意外部 API 补偿或跨系统 exactly-once。
- 不实现 BeliefLedger、AgentSelfModel、CWM、G10、LearnedProcedure 或 subagent swarm。
- 不修改 `src/aac`、`experiments`、Research Track gate 或负结果。
- 不把 `GraphPatch.operations_json` 直接解释执行；本轮只接收完整、已验证的新
  `WorkflowGraph`。
- 不允许延长已接受的 `Commitment.expires_at`；过期承诺只能失败、取消或由新任务取代。
- 不允许把普通 run resume 当作 correction resume；两条 authority transition 必须分离。

## 4. Canonical contracts

### 4.1 WAIT_EVENT 声明

`NodeSpec` 增加：

```python
wait_signal_name: NonEmptyStr | None = None
wait_correlation_key: NonEmptyStr | None = None
```

约束：

- `WAIT_EVENT` 必须同时声明两者；
- 非 `WAIT_EVENT` 不得声明两者；
- 复用既有 `timeout_seconds`，不再造第二个 timeout 字段；
- signal 名称与 correlation key 是已提交 WorkflowGraph 的数据，不由模型在运行时解释。

### 4.2 WaitCondition

```python
class WaitCondition(ContractModel):
    node_id: NonEmptyStr
    signal_name: NonEmptyStr
    correlation_key: NonEmptyStr
    registered_at: UtcDateTime
    deadline: UtcDateTime
```

`AgentRun.wait_condition: WaitCondition | None` 是重放后的当前等待投影。期限固定为：

```text
min(registered_at + NodeSpec.timeout_seconds, Commitment.expires_at)
```

### 4.3 ExternalSignal

```python
class ExternalSignal(ContractModel):
    signal_id: NonEmptyStr
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    tenant_id: NonEmptyStr
    workspace_id: NonEmptyStr
    signal_name: NonEmptyStr
    correlation_key: NonEmptyStr
    payload_json: NonEmptyStr
    evidence_refs: tuple[NonEmptyStr, ...] = ()
    occurred_at: UtcDateTime
```

`payload_json` 必须是 canonical JSON object。signal 必须同时匹配 task、run、tenant、
workspace、name、correlation key；任何一项不匹配都在持久化前拒绝。

### 4.4 受限重规划

`WorkflowGraph.max_replans: int = 1`，允许范围 `0..3`。`AgentRun.replan_count` 从 0
开始，只由 append-only rebind event 增长。

```python
class RunPlanRebound(ContractModel):
    rebound_id: NonEmptyStr
    task_id: NonEmptyStr
    run_id: NonEmptyStr
    previous_workflow_version: int
    previous_workflow_digest: NonEmptyStr
    new_workflow_version: int
    new_workflow_digest: NonEmptyStr
    preserved_node_ids: tuple[NonEmptyStr, ...]
    invalidated_node_ids: tuple[NonEmptyStr, ...]
    new_node_ids: tuple[NonEmptyStr, ...]
    requested_by: NonEmptyStr
    reason: NonEmptyStr
    created_at: UtcDateTime
```

重规划命令只接受一个完整的新 `WorkflowGraph`。它必须：

1. 在 `WAITING_EVENT`、`PAUSED` 或 `FAILED` 状态发起；
2. 保持 workflow id、tenant、workspace、policy version、evaluator refs；
3. 版本严格 `+1`，不得提高 `max_replans`；
4. 保留所有已完成 node 的完整 `NodeSpec` 和进入这些 node 的边；
5. 不清除任何既有 action、receipt、artifact、outcome 或补偿历史；
6. 清除旧 approval 和当前 wait，run 进入 `PAUSED`；
7. 由显式 API/CLI principal 发起。模型只能产出候选，不能调用 rebind 权限。

### 4.5 恢复投影

`RunRecoverySnapshot` 从事件流计算，不成为第二真相源：

```python
task_id, run_id, event_sequence,
run_resumed_count, wait_registered_count, signal_satisfied_count,
replan_count, compensation_count, action_receipt_count,
unique_logical_action_count, outcome_status
```

它是 E1 仪器输出，不是 `LH-RECOVERY-1` verdict。

## 5. Event model 与原子性

新增 `TaskEventType`：

- `WAIT_REGISTERED`
- `EXTERNAL_SIGNAL_RECORDED`
- `WAIT_SATISFIED`
- `WAIT_TIMED_OUT`
- `COMMITMENT_EXPIRED`
- `RUN_PLAN_REBOUND`
- `COMPENSATION_STARTED`
- `ACTION_COMPENSATED`
- `COMPENSATION_FAILED`
- `COMPENSATION_BLOCKED`

### 5.1 wait 注册

Coordinator 在执行到 WAIT_EVENT 时：

1. 已经写入 `NODE_STARTED`；
2. `TaskService.register_wait()` 写 `WAIT_REGISTERED`，payload 带新 run 投影；
3. run 进入 `WAITING_EVENT`，Task 进入 `WAITING`；
4. 释放 lease 并返回；下游节点没有任何事件。

如果 run 已在同一 wait 上，再次调用 `run()` 是无副作用 no-op；它不会用普通
`RUN_RESUMED` 绕过 signal。

### 5.2 signal 满足

`TaskService.record_signal()` 在一次 optimistic append 中写三条事件：

```text
EXTERNAL_SIGNAL_RECORDED
WAIT_SATISFIED (run=RUNNING, wait_condition=None)
NODE_COMPLETED (wait node output = signal payload/evidence refs)
```

同一 `signal_id` + 同一 canonical payload 重放返回当前 aggregate；不同 signal 或错误匹配
失败且零持久化。并发 signal 由 sequence CAS 决胜，败者重读后按重复或冲突处理。

### 5.3 期限

- `TaskService.start_run()` 在创建 run 前拒绝已过期 Commitment；
- WAITING_EVENT 在 `record_signal()` 或后续 `run()` 时检查 deadline；
- 到期写 `WAIT_TIMED_OUT`，run/task 进入 FAILED；迟到 signal 不得复活任务；
- 任意 resume 也不能改变 Commitment 或 WaitCondition 的 deadline；
- Commitment 合同不可更新，replan payload 也不包含 Commitment，因此登记后的 deadline
  不存在随合同延长/缩短而漂移的通道。

本轮不承诺无人调用时主动唤醒；后台 scheduler 是后续部署能力。它承诺任何进入
run/signal 公共入口的调用都不能越过已过期边界。

## 6. Durable compensation

### 6.0 correction-boundary prerequisite

Restart-safe compensation is not allowed to rely on the current process-local correction cache.
For persisted deployments, correction state is live-read on every policy and connector boundary,
and `correct/resume` advances its epoch atomically in the backing store. The final connector check
rejects expired permits, any halted task/run/capability scope, or an epoch mismatch before both
idempotency replay and side effects. This is a prerequisite, not a compensation exception: C7
remains non-writable and non-bypassable by the model, workflow, or compensation engine.

### 6.1 真实能力边界

本轮只对 `workspace.apply_patch` 声称自动补偿。`workspace.run_tests` 与
`artifact.write` 调整为诚实的 `SANDBOX_IDEMPOTENT`，不再声称引擎能恢复任意测试副作用。

新增内部 typed capability `workspace.compensate_patch`。它不是模型可提议的一般工具，
只由 Coordinator 针对已完成、已提交、`COMPENSATABLE` 的 patch node 构造；仍走：

```text
ActionContract -> PolicyKernel -> ActionPermit -> CapabilityBroker -> ActionReceipt
```

该能力不得进入普通 Application grants、provider allowlist 或 WorkflowGraph TOOL dispatch；
普通 workflow/provider 尝试调用时在 commit/runtime 边界拒绝。

### 6.2 快照格式

apply 前以 `sha256(idempotency_key)` 为目录键，在 `.agent-os-artifacts/compensation/` 写入：

- relative path；
- before existed 标志；
- before/applied SHA-256；
- before bytes（若原文件存在）；
- compensated 标志。

immutable manifest 另绑定 version、action-key digest、path、before existence/digest、
applied digest 与 manifest digest；`PREPARED/APPLIED/COMPENSATED` 是独立原子状态，不参与
immutable digest。apply receipt 的 `detail_ref` 绑定 opaque compensation ref，以覆盖
“副作用完成、NODE_COMPLETED 尚未落盘”的崩溃窗口。

事件与输出只保存 opaque `compensation_ref` 和 digest，不保存原文件内容。重启后的新
`WorkspaceSandbox` 可由 ref 找回快照。

snapshot 的 metadata 与 before bytes 必须通过临时文件 + 原子 rename 完整落盘后，才允许
写目标文件；目标本身通过同目录临时文件 + `os.replace()` 原子替换。任何 snapshot I/O
失败都使 patch action 失败且目标文件保持原样。幂等记录绑定稳定 intent fingerprint，
同 key 不同 path/content/capability 必须拒绝。对历史或
异常 receipt 若找不到 durable ref，系统写 `COMPENSATION_FAILED` 和
`manual_intervention_required=true`，绝不伪造 compensated success。

补偿前必须验证目标仍是本 action 写入的 `applied_sha256`。若用户或另一 action 已修改
目标，补偿失败并留下 `COMPENSATION_FAILED`，绝不覆盖新内容。

### 6.3 触发与顺序

- 普通 node failure 或最终 `ObservedOutcome.NOT_MET` 触发；
- 对已完成且存在 durable compensation ref 的 node 按逆拓扑顺序执行；
- 已有 `ACTION_COMPENSATED` 的 node 被跳过；
- 重复补偿通过 compensation idempotency key 返回 replay，不重复副作用；
- C7/task/run/capability 已 halted 时写 `COMPENSATION_BLOCKED` 和
  `manual_intervention_required=true`，不例外执行；
- 只有外部 principal 可调用 `resume_correction` 产生更高 correction epoch；随后 principal
  才能显式调用 `compensate_task`，该补偿仍重新经过 PolicyKernel/permit/broker；
- 普通 `resume_task` 只改变 run 状态，绝不暗中恢复 correction authority；
- 补偿失败不改变原始 failure/NOT_MET，且不得报告 rollback succeeded。

## 7. Replan 与旧上下文隔离

`RUN_PLAN_REBOUND` payload 同时保存新 WorkflowGraph、RunPlanRebound 与更新后的 AgentRun。
TaskAggregate 重放后以新 graph 为当前版本，保留完整历史。

`RunCoordinator._restore_context()` 逐序消费 rebind event：到达 rebind 时，删除
`invalidated_node_ids` 的旧 provider response、tool args、ActionContract 与 node output；之后
只消费新版本事件。已完成 node 不允许 invalidated，因此其 evidence 保持有效。

这防止旧计划中未执行的 provider proposal 或 approval 在新计划上获得执行权。

## 8. Public entry points

### Application

```python
AgentOSApplication.signal_task(task_id, payload)
AgentOSApplication.replan_task(task_id, payload)
AgentOSApplication.resume_correction(task_id, reason)
AgentOSApplication.compensate_task(task_id)
AgentOSApplication.recovery_json(task_id)
```

### HTTP

```text
POST /v1/tasks/{task_id}/signals
POST /v1/tasks/{task_id}/replan
POST /v1/tasks/{task_id}/correction/resume
POST /v1/tasks/{task_id}/compensate
GET  /v1/tasks/{task_id}/recovery
```

HTTP `Idempotency-Key` 继续复用现有 SQLite idempotency path；domain-level `signal_id` 仍是
跨客户端/重启的最终 signal 幂等键。

### CLI

```text
agent-os task-signal <task_id> <signal.json>
agent-os task-replan <task_id> <workflow.json> --reason <text>
agent-os correction-resume <task_id> --reason <text>
agent-os task-compensate <task_id>
agent-os task-recovery <task_id>
```

所有入口调用相同 `AgentOSApplication -> TaskService/RunCoordinator`，不出现第二执行路径。

## 9. 必须先失败的测试

### Contract/aggregate

- WAIT_EVENT 缺少 name/key 拒绝；非 WAIT_EVENT 偷带 wait 字段拒绝；
- ExternalSignal 非 object JSON、scope/run mismatch 拒绝；
- 新 event 未在 aggregate 显式处理时测试失败；
- replan 提升预算、跳版本、改 scope/policy/evaluator、改 completed node 全部拒绝。

### Wait/deadline/concurrency

- 未收到匹配 signal 时普通 resume/run 不得越过 wait；
- 错 name/key、错 tenant/workspace/run 零事件；
- 同 signal 重放零新增节点完成/副作用；
- 两个并发匹配 signal 只允许一个完成 wait；
- deadline 到期和迟到 signal 都不能复活；
- Commitment 已过期不能 start 或继续。

### Replan

- v1 wait 后由授权用户提交 v2，旧 wait 被 invalidated，新计划从完成前缀继续；
- 旧 signal、旧 proposal、旧 approval 不得穿过 rebind；
- `max_replans=1` 后第二次请求拒绝；
- 模型/provider 没有 replan public capability。

### Compensation

- apply 后 worker 中断；新进程测试 NOT_MET 后从 durable snapshot 恢复原文件；
- snapshot 持久化失败时 patch 必须零文件副作用；
- target 被另行修改时补偿拒绝覆盖；
- 重复补偿不产生第二副作用；
- C7 halt 后不执行自动补偿；普通 resume 仍被 correction 拒绝；只有 principal 显式
  resume correction 后，manual compensation 才可恢复文件；
- 没有 compensation ref 的 node 不得伪造 compensated success。

### End to end

真实 SQLite + 真实 workspace：

1. v1 读文件后进入 WAITING_EVENT；
2. 新 Application 进程重放并接收 signal；
3. 可选 v2 rebind 后继续 provider/approval/apply/test/evaluate；
4. 成功路径达到 VERIFIED；
5. 故障路径在重启后补偿并保持 NOT_MET；
6. recovery projection 与 event stream 精确一致；
7. action idempotency key 无重复逻辑副作用。

## 10. 研究器官边界

- CWM：`PARK` 于本切片。没有 identifiable intervention consumer，不进入等待、重规划或
  补偿控制路径。
- BeliefLedger：保持 product critical gap；signal payload 是 task event，不冒充 belief。
- AgentSelfModel/G10：保持 evidence-gated；本轮不让模型决定 act/ask/replan。
- Continual learning/LearnedProcedure：不从一次成功 run 自动晋升任何 workflow 或 policy。
- L0-L3 外部候选：以后可提出 GraphPatch/WorkflowGraph candidate；L4 runtime self-edit 和
  L5 correction-base self-edit 继续禁止。

## 11. 证伪与停止条件

以下任一项发生，本轮降为 `NOT_MET`，不以更多抽象补救：

- signal/resume 竞态产生重复 node completion 或重复 patch；
- 重启后无法精确恢复 wait、replan count 或 compensation ref；
- replan 能修改 completed action 历史或提高权限/评估器；
- compensation 绕过 PolicyKernel/C7，或覆盖 action 之后的用户修改；
- API/CLI 与测试走不同执行路径；
- Product Track 引入 `src/aac`、`experiments` 或外部 Agent framework runtime dependency；
- 通过测试需要移动已冻结 acceptance 语义或删除负路径。

## 12. 交付边界

完成后可声称：

> Agent OS Product Track 在本地 SQLite + workspace sandbox envelope 内，实现并验证了一个
> 受限的长程任务 vertical：持久等待/信号、期限、一次人工授权重规划、重启恢复和
> workspace patch 补偿。

仍不得声称：完全自治、7x24 生产系统、一般长程优势、自我进化、CWM product win、
`LH-RECOVERY-1` passed、Product Done 或 AGI achieved。
