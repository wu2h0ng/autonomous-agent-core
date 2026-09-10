# Review Request — Slice 2 独立评审（builder ≠ reviewer）

**Reviewer:** 独立子代理（非 builder）
**Scope commits（codex/ide-ui，按序）:**
1. `437a6463` — 封闭解码器 decodeTaskDetail/decodeTaskTrajectory + 真实样本 fixture
2. `2ce7f289` — 主进程桥 getTaskDetail/getTaskTrajectory + IPC 三命令
3. `538f37bc` — AgentOSTaskContentProvider 转录投影 + 注册接缝
4. `01d4d97e` — slice-2 e2e oracle + 两个 e2e 发现的修复（raw segment、DRAFT→InProgress）

**工作目录:** `/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core/.worktrees/ide-ui`

**必读输入:**
- 计划：`docs/superpowers/plans/2026-09-10-agent-os-dual-workbench-slice-2.md`（范围边界 In/Out、Global Constraints）
- 验证报告：`.agent_runs/dual-workbench-slice-1-20260909/verification-slice-2.md`
- 变更集：`git show` 上述 4 个 commit，或 `git diff e13684a2..HEAD -- apps/code-oss`

**评审要点（逐项给 verdict）:**
1. **封闭性**：decodeTaskDetail 白名单输出是否真的按构造封闭（approval/proposed_action/provider/events 等富字段在任何输入下都不可能出现在输出）；decodeTaskTrajectory 的 exact-keys 三层校验是否有洞。
2. **桥安全**：assertSafeRouteSegment 是否真的能防路径穿越（`/`、`..`、编码绕过、超长、非字符串）；raw segment 拼接在取消 encodeURIComponent 后是否引入新注入面；GET allowlist 模板匹配是否会被构造路径绕过（如 `/v1/tasks/x` 匹配 detail 模板但实际越权）。
3. **只读不变式**：IPC 表面是否仍只有 3 个读命令；content provider 是否绝无写路径（requestHandler 缺席）；DRAFT→InProgress 映射修正是否合理、有没有破坏 Slice 1 语义。
4. **测试有效性**：测试是否会在实现被绕过/置空时失败（挑 2-3 个关键测试做变异推演，或直接对源码做只读变异心算）；e2e 断言（seq 计数、键缺席、bearer 缺席、无写控件）是否有漏。
5. **计划符合性**：In/Out 边界是否被遵守（无 Python/contracts 变更、无上游新文件、patch 面未扩大——用 `git diff e13684a2..HEAD --stat` 核实）；真实样本 fixture 是否含敏感信息。
6. **诚实性**：verification-slice-2.md 的声明与代码/测试实际是否一致（特别是 gap 仅单测覆盖的标注）。

**可复跑验证（可选但鼓励）:**
- `cd apps/code-oss && node scripts/verify.mjs`
- `node --test tests/runtime-task-bridge.test.mjs`、`node --test tests/agent-os-sessions-provider.test.mjs`
- e2e 较长（~2min/个），可选：`node --test tests/dual-workbench-slice-2.test.mjs`

**输出:** 写 `.agent_runs/dual-workbench-slice-1-20260909/review-s2-final-subagent.md`，
含逐项 verdict（APPROVE/REQUEST_CHANGES + P0/P1 分级）与总体结论。
**纪律:** 你是 reviewer，不改任何源码；发现问题的唯一输出是评审报告。
