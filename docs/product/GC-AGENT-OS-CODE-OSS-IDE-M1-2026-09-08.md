# Goal Card — Agent OS Code-OSS IDE M1

> Date: 2026-09-08
> Track: Product
> Status: IMPLEMENTATION_AUTHORIZED / BRANCH_CONTAINED / NOT_RELEASED
> Branch: `codex/ide-ui`

## User result

`U-AGENT-IDE-1`: 用户在同一个 Agent OS 桌面产品中使用成熟代码编辑环境，并通过右上角唯一按钮在 Agent 与 IDE 两个 Surface 之间切换；工作区、任务、对话、变更与运行状态不因切换而丢失。

## Product capability

`P-AGENT-IDE-1`: 基于 MIT Code-OSS 1.106.3 的可复现发行底座，内置 Agent OS 扩展并连接既有本地 Surface Runtime。Code-OSS 提供编辑、文件、搜索、Git、终端、调试、语言服务和扩展宿主；Agent OS 提供任务、工具、审批、证据、恢复和协作语义。

## First usable vertical slice

1. 精确锁定并获取 Code-OSS 上游。
2. 打开真实仓库并使用原生 Code-OSS 编辑能力。
3. 右上角仅显示一个目标 Surface 按钮：`Agent ↗` 或 `IDE ↗`。
4. Agent Surface 读取私有 Runtime descriptor，连接同一个 Agent OS Runtime。
5. 用户从 Agent Surface 创建工作、发送目标并回到 IDE。
6. Runtime 不可用、descriptor 非法、协议不匹配时明确失败且不泄露 bearer token。

## Boundaries

- Agent Core Runtime 和 C7 权威不进入 Code-OSS，也不由扩展替代。
- 不复制 Cursor、Qoder 的闭源实现。
- 不依赖 Microsoft 商标、Visual Studio Marketplace 或专有 Remote 扩展。
- Tauri Surface 保留为迁移参考，不再承担 IDE 内核建设。
- 本分支不授权 push、merge、签名、公证或发布。

## Acceptance

- 上游 commit/tag/sha256 锁可机械校验。
- 扩展单元测试、类型检查和 bundle 构建通过。
- Code-OSS 能加载内置 Agent OS 扩展。
- 单按钮互斥条件有自动测试。
- 真实 Runtime 连接和失败路径均经过桌面验证。

