# Slice 2 Verification — 任务详情 + trajectory 只读转录

Date: 2026-09-11 · Branch: codex/ide-ui · Builder: kimi-builder

## Commits (Slice 2)

| Task | Commit | Content |
|------|--------|---------|
| 1 | 437a6463 | 封闭解码器 decodeTaskDetail / decodeTaskTrajectory + 真实样本 fixture |
| 2 | 2ce7f289 | 主进程桥 getTaskDetail/getTaskTrajectory（safe-segment 路由校验 + IPC 三命令） |
| 3 | 538f37bc | AgentOSTaskContentProvider：转录投影 + 注册接缝 |
| 4 | (this) | slice-2 e2e oracle + DRAFT→InProgress 映射修正 |

## Test Evidence

- 单元/合同：`node scripts/verify.mjs` 聚焦套件全绿（7 个测试文件）。
  - bridge 19/19（含 safe-segment 路径穿越拒绝、IPC typed 参数校验、descriptor 守卫继承）
  - provider 14/14（含转录映射、no-run 分支、fail-closed 解析、42 事件标签全集）
- 编译：`npm run compile`（.code-oss/upstream）0 errors。
- e2e：`tests/dual-workbench-slice-2.test.mjs` 绿（真实 daemon + stub provider + 双窗口）：
  - 选中带 run 任务 → 转录按序渲染 20 步（seq #1..#20，首 TASK_CREATED 末 RUN_FAILED）
  - 选中 DRAFT 任务 → 详情 + "No run has been recorded" 笔记，无 trajectory 请求
  - 页面/载荷无 approval/proposed_action/provider_usage/lease_fence/bearer_token/workflow_digest/tenant_id 键（评审后 approval 已补入 e2e 禁用清单并复跑转绿）
  - bearer 不出现在任何 renderer 的 DOM/storage/console
  - 无写控件（send/delete/archive/fork/approve 全无）
  - reload 后 runtime 存活、标签复现；application quit 有界终止 runtime
- Slice 1 e2e 回归：`tests/dual-workbench-slice-1.test.mjs` 绿（DRAFT 映射修正未破坏）。

## Oracle Teeth（变异实证）

在编译产物中把 `for (const step of trajectory.steps)` 变异为空循环后，
e2e 在 "transcript renders the trajectory in order" 断言超时变红；还原后转绿。
证明 e2e 确实咬住转录渲染路径。

## e2e 发现的两个真实缺陷（已修）

1. **%3A 404**：桥的 encodeURIComponent 把 run_id 的 `:` 编成 %3A，而 Python 路由不做
   percent-decode → 真实 daemon 404。单测无法发现（loopback handler 不回放路由语义）。
   修复：safe-segment 校验后直接拼原始段。
2. **DRAFT→Untitled 映射泄漏写控件**：上游把 Untitled 视为"本地未发送草稿"，
   选中后打开可交互 new-chat 编辑器 —— 对 runtime 拥有的 DRAFT 任务构成写面。
   修复：DRAFT/null → SessionStatus.InProgress（改动 Slice 1 已批准映射，理由见代码注释）。

## Unit-Only Coverage（如实标注）

- **gap 标注渲染**：真实 runtime 的 trajectory 序列连续（probe 实证：二次运行 seq 重排为 1..23，
  detail 仍指向首个 run），HTTP 路径无法产生真实 gap。gap 渲染由
  tests/agent-os-sessions-provider.test.mjs（合成 gapBefore=3）与解码器合成测试覆盖。
- gapBefore 语义的解码器边界由 tests/runtime-task-detail-contract.test.mjs 覆盖。

## Screenshots

- screenshots/slice2-transcript.png — 转录视图（seq #1..#20 全序可见；中央叠加为上游
  Copilot 登录欢迎弹窗，非本切片组件，e2e 断言不受其遮挡影响）
- screenshots/slice2-draft-no-run.png — DRAFT 任务：read-only 横幅 + no-run 笔记

## Known Limits

- 登录欢迎弹窗在上游 flaky 出现；e2e 用 dismiss 循环处理，截图中仍可见。
- run 以 FAILED 终态（evaluator:none 要求 evidence）——转录内容不受影响。

## 独立评审收口（review-s2-final-subagent.md）

- 结论 APPROVE_SLICE_2，P0=0。
- P1-1 已关闭：decodeTaskDetail 增加已知顶层键封闭校验（19 键，真实 fixture 钉死），
  未知顶层字段 fail-closed 作合同漂移报警；新增 red-first 测试，8/8 绿。
- O-3 已补记：DRAFT→InProgress 映射修正见上文「e2e 发现的两个真实缺陷」，
  并在计划文档补记。
