# 产品命名：Noem（founder 决策 2026-09-15）

- **产品名**：**Noem**（agent 产品正式命名）。
- **终端命令**：`noem`。npm bin 仅注册 `noem`（注册 `Noem` 会在大小写不敏感 FS 上与 `noem` 冲突）；在**大小写不敏感 FS（macOS/Windows）** 下 `Noem`/`NOEM` 自动解析到它，大小写敏感 FS（Linux）不保证。
- **Agent OS**：仅代表**系统级 agent**（Runtime/Kernel 与系统级存储/守护）：保留 `agent-os-runtime`（daemon）、`~/.agent-os/`（状态）、`AGENT_OS_*`（环境变量）。
- **Noem Work CLI**：本地权威 Agent Work 命令仍为 `agent-os-work`（系统级命名）。
- **兼容别名（deprecated）**：`agentos`、`agent-os`、`agent-os-ts` 仍指向同一 cli-ts 入口，后续可移除。
- **代码落点**：`apps/cli-ts`（产品客户端），UI 文案 `NOEM` / `◆ noem`，`--help`/`--version`/错误前缀均为 `noem`。
