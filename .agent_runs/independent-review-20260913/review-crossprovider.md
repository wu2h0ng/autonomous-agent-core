**结论：NO_APPROVE**

发现 1 个阻断级问题：I-23 仍可通过伪造 `ProposedGoal.constraints` 绕过，并最终到达 `TaskService.ensure_task`。

**Finding**

HIGH — forged producer identity bypasses I-23  
`packages/os_core/src/agent_os_core/srl_activation_gate.py:177`  
`packages/os_core/src/agent_os_core/srl_activation_gate.py:182`  
`packages/os_core/src/agent_os_core/srl_runtime.py:318`  
`packages/os_core/src/agent_os_core/srl_runtime.py:329`

当前 gate/runtime 只从 caller-supplied `ProposedGoal.constraints` 读取 `assessor-instance:`。`c76f28fa` 修复了 missing / empty / whitespace，但没有修复 forged value。

具体绕过：

1. 可信 registry 中存在 `ActivationAuthority(authority_instance_id="assessor-instance-1", source_proposed_goal_id="goal-1", source_assessment_id="assessment:event-1", ...)`
2. 调用方传入同一个 `proposal_goal_id="goal-1"`，但把约束改成：
   `assessor-instance:some-other-instance`
3. `SrlRuntime.activate_goal` 看到 producer != authority，放行。
4. `TrustedTaskActivationGate` 也看到 producer != authority，放行。
5. 只要 mandate / requirements / C7 正常，执行到 `TaskServiceCreationAdapter.create_task()`，最终调用 `TaskService.ensure_task()`。

这违反 I-23 的实质：producer/acceptor separation 不能由调用方可篡改字符串决定。已有 `assessment-ref` 与 `mandate-ref` 检查也是从同一组 caller-supplied constraints 读出来的，不能证明 assessor identity 是真实 assessment producer。

**Required Change**

必须把 producer identity 绑定到可信来源，而不是信任 `ProposedGoal.constraints`：

- 从可信 assessment registry / assessment receipt 读取 `source_assessment_id -> assessor_instance_id`，再与 `authority.authority_instance_id` 比较；或
- 让 trusted authority/goal registry 绑定完整 ProposedGoal digest，并在 gate 里校验 caller goal digest 完全一致；或
- 至少把 `ActivationAuthority` 的 trusted record 扩展为包含 source assessment producer identity，并校验它与 goal/assessment 一致。

并添加测试：

- same-instance authority + forged `assessor-instance:other` must reject
- same-instance authority + duplicate `assessor-instance:` where first is benign and second is real producer must reject or fail closed
- runtime path must reject before delegated activation for forged producer metadata, not only missing/empty

**Other Focus Checks**

未发现 caller-minted authority、inactive/expired mandate、mandate-ref mismatch、assessment-ref mismatch、missing requirements、missing C7、epoch mismatch 直接越过当前显式检查到 `ensure_task` 的路径。

冲突 re-activation 已 fail-closed：`InvalidTransitionError` 映射为 `TASK_IDENTITY_CONFLICT`，相同输入 idempotent。

C7 语义未被写入或修改；当前只是消费 `C7ClearanceRef` 并检查 epoch，符合 slice 边界。

**Verdict：NO_APPROVE**

阻断原因不是测试数量，而是信任边界错位：I-23 的关键事实仍来自调用方可改 metadata。这个 slice 要晋升，必须先把 producer identity 绑定到可信 assessment/authority/goal digest。