# 产品命名：Noem（founder 决策 2026-09-15）

- **产品名**：**Noem**（agent 产品正式命名）。
- **终端命令**：`noem`（大小写均可启动：`noem` / `Noem` / `NOEM`；npm bin 同时注册 `noem` 与 `Noem`；macOS 大小写不敏感 FS 下任意大小写可用）。
- **Agent OS**：仅代表**系统级 agent**（Runtime/Kernel 与系统级存储/守护）：保留 `agent-os-runtime`（daemon）、`~/.agent-os/`（状态）、`AGENT_OS_*`（环境变量）。
- **Noem Work CLI**：本地权威 Agent Work 命令仍为 `agent-os-work`（系统级命名）。
- **兼容别名（deprecated）**：`agentos`、`agent-os-ts` 仍指向同一 cli-ts 入口，后续可移除。
- **代码落点**：`apps/cli-ts`（产品客户端），UI 文案 `NOEM` / `◆ noem`，`--help`/`--version`/错误前缀均为 `noem`。
