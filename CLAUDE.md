# CLAUDE.md

**先读 `AGENTS.md`(权威工作指令),本文件只补充 Claude Code 平台细节。**

- 本仓库是完整 Agent OS 产品主仓，采用 Product Track + Research Track 双轨分层 monorepo。产品定义先读 `docs/AGENT-OS-PRODUCT-BLUEPRINT-V1.md`；当前状态先读 `docs/CURRENT_STATE.yaml`。
- 研究宪法和历史证据仍在 baseline 工作区 RR 文档、本仓 ADR/结果中；不得因产品身份更新而改写 verdict，也不得以研究测试代替产品验收。
- Windows PowerShell 命令形式:

```powershell
$env:PYTHONPATH="src"; python -m unittest discover -s tests -v
$env:PYTHONPATH="src"; python experiments/regime_shift.py
```

- Git Bash 下 `PYTHONPATH=src python -m unittest discover -s tests` 即可。
- 当前 `src/aac` Research Track 保持其已冻结的纯标准库约束。未来 Product Track 可按 ADR 引入成熟 UI、存储、队列、身份、模型 SDK 等依赖，但不得外包 Agent OS 的 authority spine，也不得让插件绕过 contracts/policy。
- `T-P-OS-SPINE-0` 只构建 generic developer golden path。Data Agent donor 的一次性迁移属于 `T-P-OS-SPINE-1`，必须遵守 ADR-0054 的 Hard Boundary #19、full-history safety、provenance 与 no-runtime-import 门；不得因 founder 选择 Option B 而提前 import、push 或 merge。
- 接力任务从 `docs/PROJECT_PLAN.md` 的任务卡开始;founder 决策倾向画像在该文件 §2。
- 最高纪律:**绝不为让预注册证伪门变绿而调机制**(AGENTS.md §2.5)。
