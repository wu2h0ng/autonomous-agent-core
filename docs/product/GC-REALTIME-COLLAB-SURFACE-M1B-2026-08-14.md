# Realtime Collaboration — Surface Conflict Projection (M1b) Goal Card

> Date: 2026-08-14
> Track: Product
> Status: **REAL_EVENT_PRODUCER_AND_CONFLICT_PROJECTION_IMPLEMENTED / SURFACE_RENDERER_NOT_IMPLEMENTED / NOT_REVIEWED / NO_MERGE_PUSH_RELEASE_AUTHORITY**
> Exact base: `34e2344d`（本地 main；M1a merge `1ea99cab` + P2 #4/#5 关闭）
> Authority: founder decision 2026-08-14 §2；M1b CTO 三项锁定（显式钩子 / high-water cursor / file-level）
> Requirement: GOAL-BLUEPRINT M2「人/Agent 同空间并发工作」——可见冲突/协作体验
> Claim ceiling: `REAL_EVENT_PRODUCER_AND_CONFLICT_PROJECTION_IMPLEMENTED / SURFACE_RENDERER_NOT_IMPLEMENTED`

## Goal

把 M1a 已经实现的生产 runtime fence 冲突决策，投影到 macOS Native Surface 的**可见冲突体验**，
并补上 M1a 遗留的**生产事件生产者**（P2 #3）。

用户可见结果（`U`）：当一个人与一个 Agent（或两个 Agent）并发编辑同一文件时，Surface
面板显示**明确的冲突来源 + scope + 建议处置（REPLAN/CONFLICT）**，不允许静默覆盖；用户可
在界面上发起重规划或确认覆盖。

产品能力（`P`）：
1. **生产事件生产者**：把外部文件变更（watcher / 编辑器写入 / 另一 Agent 通过 fence 的写）
   转成 `WorkspaceEvent` 追加进 `SQLiteWorkspaceCommitFence`，推进 `event_cursor`——关闭 P2 #3。
2. **冲突投影**：Surface 在 dispatch 被 fence 拒绝（`WorkspaceWriteRejected`/`ReplanRequired`）
   时，把 `WorkspaceWriteDecision` 转成 typed Surface 冲突视图（scope + relevant event ids +
   disposition + reason），渲染到 files/diff 面板。

## 为什么现在做

1. M1a 已合入 main：runtime fence 是真实生产路径，但没有可见出口——用户只看到「写被拒」，
   看不到原因、来源、或如何重规划。
2. P2 #3 是 M1a 明确的 carry-forward debt：`append_event` 目前仅测试调用，生产 `event_cursor`
   永不前进，冲突事件一旦写入会永久阻断，需要生产事件源。

## 范围（M1b）

1. **事件生产者（P2 #3 关闭）**：一个 file-level watcher 或显式写入钩子，把同 workspace 的
   文件变更转成 `WorkspaceEvent`（MUTATION + 受影响 scope + version 推进），append 进 fence。
2. **冲突投影 contract**：`SurfaceConflictProjection`（lease/action/scope/decision/relevant
   events/suggested disposition），从 `WorkspaceWriteDecision` 派生。
3. **Surface 渲染**：files/diff 面板在冲突时显示 scope + 来源 + disposition + 可操作建议
   （重规划 / 查看差异），不静默覆盖。
4. **测试**：事件生产者产生完整 batch；冲突投影 typed；面板渲染不回归。

## 非目标（本次不做）

watcher 的跨进程事件总线、CRDT、语义 merge、多主机/网络分区、自动 replan、exactly-once
外部效果证明、release、自主性声明。

## 验收形状

- 生产事件生产者推进 `event_cursor`，冲突后可重规划而非永久阻断。
- 冲突投影是 typed contract，Surface 显示来源 + scope + disposition。
- 全 Product 回归零新增失败；Ruff/Pyright 干净；独立 exact-head review + CTO gate。

## 下一步 gate

Context Pack + Architecture Brief 完成后，经 CTO gate 才授权实现。
