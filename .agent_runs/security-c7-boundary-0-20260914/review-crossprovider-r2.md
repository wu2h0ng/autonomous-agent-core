**Verdict: APPROVE_WITH_CHANGES**

上一轮 required change **部分 CLOSED**：`f13958a6` 确实给 [c7_receipt.py](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/security-c7-boundary/packages/os_core/src/agent_os_core/c7_receipt.py:113) 的 `C7ReceiptVerifier.verify()` 增加并执行了 `expected_tenant_id` / `expected_workspace_id`，显式传入错误 tenant/workspace 时会在读 authority 前 `C7ReceiptScopeMismatch` fail-closed。新增测试也覆盖了显式 cross-tenant / cross-workspace replay。

但我发现一个仍需修的绕过：**scope param omission**。如果调用方省略 `expected_tenant_id` / `expected_workspace_id`，同一 `task/run/capability` 的 receipt 仍会被接受；这和 verifier docstring 里的 “missing/mismatched scope fail-closed” 以及边界声明里的 scope-binding 语义不一致。我的 inline probe 结果：

```text
cross_tenant_explicit: REJECTED_SCOPE_MISMATCH
cross_workspace_explicit: REJECTED_SCOPE_MISMATCH
tenant_workspace_omitted: ACCEPTED
epoch_resume_old_receipt: REJECTED_EPOCH_REPLAY
halting_after_issue: REJECTED_HALTED
digest_tamper_tenant: REJECTED_VALIDATION
```

**Required change:** 让 `C7ReceiptVerifier.verify()` 对 tenant/workspace expected scope 缺失也 fail-closed，或引入一个强制 scope context 的非可选参数对象；否则 API 仍允许调用方通过 omission 绕过 cross-tenant/workspace replay 检查。相应更新测试：不传 tenant/workspace expected 时应拒绝。

其他新绕过尝试未成立：epoch resume、halting、digest tamper 都 fail-closed。边界 statement 总体仍诚实地承认 worker/process compromise 不在 option A 内，但文档表格也需要同步 tenant/workspace scope，避免继续只写 `task/run/capability`。

验证已跑：

```text
UV_CACHE_DIR=$PWD/.uvcache uv run --extra product-test pytest tests/product/test_c7_receipt_fault_injection.py -q
11 passed in 0.39s
```

未修改 tracked 源码/测试文件。`git status --short` 只显示既有 untracked review 文件。