# CLAUDE.md

**先读 `AGENTS.md`(权威工作指令),本文件只补充 Claude Code 平台细节。**

- 本仓库是通用自主智能体原型(主产物/对象层)。研究宪法在 baseline 工作区:
  `../docs/research/RR-0001-unified-autonomous-agent-architecture.md`(v2)、`RR-0003`(原型设计)、`RR-0004`(三仓角色图)。
- Windows PowerShell 命令形式:

```powershell
$env:PYTHONPATH="src"; python -m unittest discover -s tests -v
$env:PYTHONPATH="src"; python experiments/regime_shift.py
```

- Git Bash 下 `PYTHONPATH=src python -m unittest discover -s tests` 即可。
- 纯标准库,无需安装依赖;不要引入第三方包(理由见 ENGINEERING.md)。
- 接力任务从 `docs/PROJECT_PLAN.md` 的任务卡开始;founder 决策倾向画像在该文件 §2。
- 最高纪律:**绝不为让预注册证伪门变绿而调机制**(AGENTS.md §2.5)。
