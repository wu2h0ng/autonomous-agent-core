# ENGINEERING.md — Agent OS 双轨技术栈、开发规范、工程化控制

## 0. Scope

产品架构以 `docs/AGENT-OS-PRODUCT-BLUEPRINT-V1.md` 为准。本文件原有 Python/stdlib/预注册规则继续约束当前 `src/aac`、`experiments`、研究 adapters 与 Research Track；不得把这些控制变量外推成 Product Track 的永久技术栈。

## 1. Research Track 技术栈(ADR-0001)

- Python ≥ 3.10,**纯标准库**(`src/` 零第三方依赖)。理由:原型期可证伪性 > 便利;
  零依赖 = 任何机器任何 agent 可即刻接力;杜绝"框架带入的隐性行为"污染机制实验。
- 布局:src layout(`src/aac` 核,`src/envs` 环境,`tests/`,`experiments/`)。
- 测试:`unittest`(与企业仓一致;零依赖)。运行 `PYTHONPATH=src python -m unittest discover -s tests`。
- 类型:全模块 `from __future__ import annotations` + 完整类型注解 + `dataclass` 优先。
- 实验脚本可打印表格;暂不引入绘图依赖(需要时走 ADR 加 dev-extra,核不受影响)。

### 1.1 Product Track 技术栈边界

- 首个产品 scaffold 前必须通过架构 ADR，确定应用/UI、持久化、队列、身份、secret broker、observability 与部署基线。
- Product Track 可使用成熟第三方库、模型 SDK、数据库、队列、搜索/vector、身份和 UI 技术；依赖必须有许可证、安全、维护和替换评估。
- 不得外包的 authority spine: canonical contracts、Task/Commitment/AgentRun、WorkflowGraph IR、capability policy、ActionContract、belief/outcome、correction 与 research-promotion rules。
- Product Track 不直接 import Research Track 的实验模块。候选机制先形成 `ResearchCandidateManifest`，再通过稳定接口和产品复验晋升。
- Domain pack 可有领域语义；通用 `packages/` core 不得依赖 Data Agent 或其他领域对象。

## 2. 代码规范

- 模块单一职责,与 RR-0001 概念一一对应(ViabilityCore=生存力核,以此类推);新概念先进 ADR 再进代码。
- 注释只写"代码本身说不出的约束"(如罩分离、stake 推导),不写叙事。
- 随机性必须经注入的 `random.Random(seed)`;实验固定种子集合(默认 0–9)。
- 公共行为变更必须先有失败测试。

## 3. 工程化控制(质量门)

Research Track 提交前本地门:

```bash
PYTHONPATH=src python -m unittest discover -s tests   # 必须 OK
```

Product Track 必须在首个架构 ADR 中建立 lint/type/unit/integration/e2e/security 和可重复构建命令；在该工具链落地前，不得把 schema、mock 或 UI shell 记为产品能力。

PR 必须使用 `.github/pull_request_template.md` 并按所选轨粘贴质量门。Research Track 机制/实验变更继续包含**证伪声明**:"本变更未为通过任何预注册门而调整机制参数/结构"。

## 4. Research Track 实验纪律(最高优先)

1. **预注册**:跑实验前,通过门判据写入 ADR(对照体、度量、种子数、胜出标准)。
2. **机制与实验有效性分离**:发现环境太易/太严可以修环境与度量,但同一轮不得动机制。
3. **负结果一等公民**:不通过 → 如实记录(ADR + baseline RR 文档)→ 走 ADR-0003 决策协议选下一步;
   **禁止**静默重试、换种子挑结果、事后改判据(挪门柱)。
4. 消融体是机制声明的一部分:每个新机制必须同时定义"它关掉之后是什么"。
5. **统计功效与假阴性防护(CTO 2026-06-14 钉为硬规范)**:跑门前在 ADR 预注册
   (a) **最小可检测效应量 MDE**——实务上有意义的阈(如 ≥X% regret 改善),
   (b) 在目标功效(默认 power ≥ 0.8、α 由门判据定)下达此 MDE 所需的**种子数/样本量**。
   **欠功效的 NOT MET 不是负结果,是"不确定"**——不得当作机制被证伪写入结论。
   报告必带**效应量 + 置信区间(或自助分布)**,不得只报 p 值。配对设计 + 非参检验
   (Wilcoxon 配对单侧)为默认;门含多判据/多臂时声明多重比较处置。
   校准种子与 r-final 种子**永远不相交**(已实践,固化为规则)。
6. **候选必须预指定,禁止同种子上认领事后赢家**:门的"候选臂"在 r-final 前钉死
   (如 G9 钉 P4=gate+organ)。若数据显示另一臂才是赢家(如 G9 实测 P0=gate-alone 胜、
   organ 反而有害),那是**新假设**,必须在**与本轮不相交的 fresh seeds** 上另设确认门坐实,
   **不得**用同一批种子改判候选(HARKing / 挪门柱的变体)。G9→G10 的 P0 fresh-seed
   确认即此规则的范例。

## 5. 边界控制

- 罩分离:`op_*` 只许出现在 shell、value_channel(operator 主权面定义处)与测试/实验/
  操作员代码;`src/aac/agent.py`、`policy.py`、`relevance.py`、`world_model.py`、
  `viability.py` 及 `src/envs/` 出现 `op_` 调用即违规。agent 一律只持能力视图
  (ShellView / ValueChannelView),构造期即降级,不持原对象。
- 外部仓库不得成为运行时依赖；Product Track 与 Research Track 之间只通过晋升 contract，不直接 import 实验实现。
- ADR-0054 只为 `T-P-OS-SPINE-1` 提供一次 history-safe Data Agent 迁移例外：
  SPINE-0 先独立验收；donor full SHA、全历史 secret/customer-data/license 扫描和
  provenance 在任何 import 前必须 `PASS`；失败时 filtered mirror 或 `ABORT`。
  该例外不允许 runtime import、双向同步、自动 push/merge 或其他跨仓复制。
- 通用 OS core 零领域词汇；领域词汇只允许在 `domain_packs/`、插件、连接器与对应测试。
- Research Track 当前 `src/aac` 继续零业务词汇、纯 stdlib，除非独立 ADR 明确改变实验控制变量。
- 版本控制:本仓库独立 git;面向 main 的变更走 PR;实验产出的大文件不入库。
