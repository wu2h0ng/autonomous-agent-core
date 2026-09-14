**结论：APPROVE**

逐项 closure：

1. `current_outcome` unknown evaluator fail-open：**CLOSED**  
   证据：[task_service.py](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/ci-onto-main/packages/os_core/src/agent_os_core/task_service.py:485) 现在 evaluator 缺失或 `verify_verified_recording` 失败都会返回新的 `UNRESOLVED` current outcome，不再投影历史 `VERIFIED`。

2. `MandateResponsibilityProjector.classify` 使用 pytest-only helper：**CLOSED**  
   证据：[mandate_responsibility.py](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/ci-onto-main/packages/os_core/src/agent_os_core/mandate_responsibility.py:223) 支持传入 bound `OutcomeEvaluatorRegistry`；投影路径在 [mandate_responsibility.py](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/ci-onto-main/packages/os_core/src/agent_os_core/mandate_responsibility.py:633) 从 `self._tasks.evaluator_registry` 取当前绑定 registry。

3. `PredicateSet` hardcoded `tenant:1/ws:1` scope：**CLOSED**  
   证据：freeze scope 已线程化到 [contract_inferencer.py](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/ci-onto-main/packages/os_core/src/agent_os_core/contract_inferencer.py:340) 和 [contract_inferencer_service.py](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/ci-onto-main/packages/os_core/src/agent_os_core/contract_inferencer_service.py:203)。更关键的是 evaluator 在 [predicate_evaluator.py](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/ci-onto-main/packages/os_core/src/agent_os_core/predicate_evaluator.py:97)、[predicate_evaluator.py](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/ci-onto-main/packages/os_core/src/agent_os_core/predicate_evaluator.py:122)、[predicate_evaluator.py](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/ci-onto-main/packages/os_core/src/agent_os_core/predicate_evaluator.py:269) 三处分别校验 contract/evaluate/verify 的 predicate-set task/tenant/workspace 与 ExpectedOutcome 一致。

新 bypass 尝试结果：未发现可用绕过。临时探针覆盖 unknown-version predicate set、scope mismatch on `contract_error` / `evaluate` / `verify_verified_recording`、registry loss，均 fail-closed。

验证：
`UV_CACHE_DIR=$PWD/.uvcache uv run --extra product-test pytest tests/product/test_predicate_evaluator.py tests/product/test_contract_inferencer.py tests/product/test_mandate_responsibility_projection.py tests/product/test_task_service.py -q`

结果：`110 passed in 3.13s`

未修改 tracked source/test file。`git status --short` 只显示既有未跟踪项：`.agent_runs/port-review-20260913/`、`agent-os.sqlite3.collaboration`。

Remaining required change：无。