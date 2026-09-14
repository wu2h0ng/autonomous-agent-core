**结论：APPROVE_WITH_CHANGES**

发现 1 个 required change；其余攻击点通过。

**Required Change**

- [packages/os_core/src/agent_os_core/c7_receipt.py](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/security-c7-boundary/packages/os_core/src/agent_os_core/c7_receipt.py:112): `C7ReceiptVerifier.verify()` 只校验 `task_id/run_id/capability_id`，没有校验 receipt 中已经 digest-bound 的 `tenant_id/workspace_id`。  
  这会允许“同 task/run/capability 名称 + 同 epoch 状态”的 receipt 在不同 tenant/workspace 语境下被接受，除非上层保证这些 IDs 全局唯一。合同层明确有 `tenant_id/workspace_id` 字段（[c7_receipt.py](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/security-c7-boundary/packages/contracts/src/agent_os_contracts/c7_receipt.py:25)），所以 verifier 应支持并强制 expected tenant/workspace scope mismatch，测试也要覆盖跨 tenant/workspace replay。最小修复：给 `verify()` 加 `expected_tenant_id`、`expected_workspace_id` 参数并在 authority read 前 fail-closed；新增 fault-injection 测试。

**攻击结果**

- stale/replayed receipt：通过。epoch change 后即使 `resume()` 清 halt，旧 receipt 被 `C7EpochReplay` 拒绝，见 [test](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/security-c7-boundary/tests/product/test_c7_receipt_fault_injection.py:47) 和 verifier 比较 [c7_receipt.py](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/security-c7-boundary/packages/os_core/src/agent_os_core/c7_receipt.py:142)。
- halted scope：通过。halted issue/verify 都 fail-closed，见 [c7_receipt.py](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/security-c7-boundary/packages/os_core/src/agent_os_core/c7_receipt.py:68) 和 [c7_receipt.py](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/security-c7-boundary/packages/os_core/src/agent_os_core/c7_receipt.py:140)。`resume()` 能清 halt 是现有 admin 语义，但会 advance epoch，因此旧 receipt 不会复活。
- write/digest tamper：通过。contract validator 重算 digest 并拒绝，见 [contracts c7_receipt.py](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/security-c7-boundary/packages/contracts/src/agent_os_contracts/c7_receipt.py:65)。
- authority unavailable：通过。issue/verify 均 catch authority exception 并抛 `C7AuthorityUnavailable`，见 [os_core c7_receipt.py](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/security-c7-boundary/packages/os_core/src/agent_os_core/c7_receipt.py:63) 和 [os_core c7_receipt.py](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/security-c7-boundary/packages/os_core/src/agent_os_core/c7_receipt.py:131)。
- boundary statement honesty：通过。文档明确说 worker/process compromise 不被 option A 覆盖，见 [C7-BOUNDARY-STATEMENT.md](/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/security-c7-boundary/docs/architecture/C7-BOUNDARY-STATEMENT.md:36)。
- existing C7 weakening/bypass：没有看到对现有 `CorrectionAuthority` / `PolicyKernel` 的削弱；新增模块是导出型、未改旧 permit/guard 路径。但上面的 tenant/workspace verifier 缺口需要补，否则 receipt 本身的 scope 绑定不完整。

验证已跑：

`UV_CACHE_DIR=$PWD/.uvcache uv run --extra product-test pytest tests/product/test_c7_receipt_fault_injection.py tests/product/test_srl_runtime_invariants.py -q`

结果：`48 passed in 2.36s`。 tracked 文件未修改。