# CLAUDE.md

先读 `AGENTS.md`；本文件只补充 Claude Code 平台提示。

- 当前状态：`docs/CURRENT_STATE.yaml`。
- 产品权威：`docs/AGENT-OS-PRODUCT-BLUEPRINT.md`。
- 产品与研究双轨共仓，但 verdict、依赖和主张隔离。
- Research Track 当前 `src/aac` 保持冻结实验所需的纯 stdlib 边界；Product Track 依赖按 ADR 管理。
- SPINE-0 只证明其明确覆盖的本地 developer path；SPINE-1/ADR-0054 未执行前不得迁入 donor、cross-import、push 或 merge。
- 最高纪律：不得为让预注册门变绿而调机制、环境、门、baseline、种子或轴。

PowerShell：

```powershell
$env:PYTHONPATH="src"; python -m unittest discover -s tests
```

Git Bash / POSIX：

```bash
PYTHONPATH=src python -m unittest discover -s tests
```
