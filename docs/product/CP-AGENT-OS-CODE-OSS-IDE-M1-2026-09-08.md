# Context Pack — Agent OS Code-OSS IDE M1

> Goal Card: `docs/product/GC-AGENT-OS-CODE-OSS-IDE-M1-2026-09-08.md`
> Date: 2026-09-08

## Observed state

- 当前 `apps/macos` 是 Tauri + React Surface，能监督 Runtime，但没有 Monaco、LSP、Extension Host、SCM、Debug Adapter 和成熟 PTY 工作台。
- Code-OSS 官方源码采用 MIT；1.106.3 的 commit 为 `bf9252a2fb45be6893dd8870c0bf37e2e1766d61`。
- 本机 Qoder IDE 的 `package.json` 指向 `microsoft/vscode.git`，发行包保留 `out/vs/workbench`、`vscode-dts`、标准内置扩展和 Code-OSS 依赖；Qoder 自有层位于 `out/lingma` 与 `aicoding-*` 扩展。
- 现有 Runtime descriptor 默认位于 `~/.agent-os/runtime.json`，包含 loopback 地址和 bearer token，文件权限应为 0600。
- 现有 Surface protocol 为 `1.0`，会话入口是 `/v1/surface/sessions` 与 `/v1/surface/sessions/{id}/turns`。

## Decision inputs

- IDE 成熟度来自 Code-OSS，不在 Tauri 中重建。
- Agent OS Runtime 保持 provider-neutral、独立进程和唯一状态真相。
- 大部分集成放进内置扩展；仅当 Extension API 无法满足统一 Surface 时才维护窄 Workbench 补丁。
- 上游源码不直接 vendor 进产品仓；以 lock + bootstrap + overlay 形成可复现 fork 工作区。

## Risks

- Code-OSS 上游更新可能改变菜单、Webview 和扩展接口；通过固定版本、契约测试和升级脚本控制。
- 扩展宿主可以读取 descriptor，因此必须校验路径、普通文件件、0600 权限、loopback host 和协议版本，日志永不包含 token。
- Command Center 菜单布局由 Workbench 控制；若扩展贡献无法稳定落在最右侧，再引入单文件上游补丁，而不是扩大 fork 面。

