**结论：APPROVE_WITH_CHANGES**

我没有修改任何 tracked source/test file；`git status --short` 为空。指定验证已跑：

`UV_CACHE_DIR=$PWD/.uvcache uv run --extra product-test pytest ... -q`

结果：`116 passed in 3.52s`

**Findings**

1. [packages/os_core/src/agent_os_core/task_service.py](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/ci-onto-main/packages/os_core/src/agent_os_core/task_service.py:485)  
   `current_outcome()` 在找不到 evaluator 时直接返回历史 `VERIFIED` outcome：
   `if evaluator is None: return outcome`。  
   这不符合 fail-closed 语义。对于 predicate evaluator 未注册、版本/registry 丢失、服务重启未绑定 predicate registry 的场景，历史 `VERIFIED` 会继续被投影为当前 VERIFIED，而不是降级为 `UNRESOLVED`。  
   Required change：未知/缺失 evaluator 应走与 revalidation failure 相同的 stale path，返回 `UNRESOLVED`，并覆盖测试。

2. [packages/os_core/src/agent_os_core/contract_inferencer.py](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/ci-onto-main/packages/os_core/src/agent_os_core/contract_inferencer.py:444)  
   `PredicateSet` 冻结时硬编码 `tenant_id="tenant:1"`、`workspace_id="ws:1"`。  
   这是 scope leakage。`ContractInferencerService.build_expected_outcome()` 后续允许调用方传入真实 tenant/workspace，但冻结的 predicate-set durable truth 已经错绑默认 scope；当前 evaluator 也没有校验 predicate_set scope 与 ExpectedOutcome scope 一致，风险被测试 fixture 掩盖。  
   Required change：冻结 PredicateSet 时必须从真实任务/commitment/service boundary 传入 tenant/workspace，并在 predicate evaluator contract/evaluation/verified-recording 路径校验 predicate_set 的 task/tenant/workspace 与 ExpectedOutcome 一致。

3. [packages/os_core/src/agent_os_core/mandate_responsibility.py](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/ci-onto-main/packages/os_core/src/agent_os_core/mandate_responsibility.py:221)  
   `MandateResponsibilityProjector.classify()` 仍调用 pytest-only `expected_outcome_contract_error()`。  
   推断影响：predicate-backed ExpectedOutcome 会被责任视图标为 `UNSUPPORTED_EVALUATOR`，即使 TaskService 已绑定 predicate evaluator registry。这是 registry refactor 的剩余旁路。  
   Required change：责任投影需要通过 bound TaskService/registry 做 contract validation，或至少不要使用 pytest-only legacy helper 判断新 evaluator。

**C7 Boundary**

语义 predicate 变 blocking 的主路径看起来守住了：未确认 semantic predicate 在 `apply_confirmation()` 中会被降级为 non-blocking；显式 `PredicateConfirmation` 或 clarification 产生的 `pre_endorsed` confirmation 才会进入 blocking/CONFIRMED。未发现 LLM judge 直接变 blocking 的路径。

但上面的 scope leakage 和 missing-registry VERIFIED projection 必须修。当前测试绿不等于这片可以合并。