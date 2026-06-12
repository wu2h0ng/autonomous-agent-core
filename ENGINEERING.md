# ENGINEERING.md — 技术栈、开发规范、工程化控制

## 1. 技术栈(ADR-0001)

- Python ≥ 3.10,**纯标准库**(`src/` 零第三方依赖)。理由:原型期可证伪性 > 便利;
  零依赖 = 任何机器任何 agent 可即刻接力;杜绝"框架带入的隐性行为"污染机制实验。
- 布局:src layout(`src/aac` 核,`src/envs` 环境,`tests/`,`experiments/`)。
- 测试:`unittest`(与企业仓一致;零依赖)。运行 `PYTHONPATH=src python -m unittest discover -s tests`。
- 类型:全模块 `from __future__ import annotations` + 完整类型注解 + `dataclass` 优先。
- 实验脚本可打印表格;暂不引入绘图依赖(需要时走 ADR 加 dev-extra,核不受影响)。

## 2. 代码规范

- 模块单一职责,与 RR-0001 概念一一对应(ViabilityCore=生存力核,以此类推);新概念先进 ADR 再进代码。
- 注释只写"代码本身说不出的约束"(如罩分离、stake 推导),不写叙事。
- 随机性必须经注入的 `random.Random(seed)`;实验固定种子集合(默认 0–9)。
- 公共行为变更必须先有失败测试。

## 3. 工程化控制(质量门)

提交前本地门(全部通过才许 PR):

```bash
PYTHONPATH=src python -m unittest discover -s tests   # 必须 OK
```

PR 必须使用 `.github/pull_request_template.md`,粘贴质量门输出,并包含
**证伪声明**:"本变更未为通过任何预注册门而调整机制参数/结构"。

## 4. 实验纪律(本仓库特有,最高优先)

1. **预注册**:跑实验前,通过门判据写入 ADR(对照体、度量、种子数、胜出标准)。
2. **机制与实验有效性分离**:发现环境太易/太严可以修环境与度量,但同一轮不得动机制。
3. **负结果一等公民**:不通过 → 如实记录(ADR + baseline RR 文档)→ 走 ADR-0003 决策协议选下一步;
   **禁止**静默重试、换种子挑结果、事后改判据(挪门柱)。
4. 消融体是机制声明的一部分:每个新机制必须同时定义"它关掉之后是什么"。

## 5. 边界控制

- 罩分离:`op_*` 只许出现在 shell、value_channel(operator 主权面定义处)与测试/实验/
  操作员代码;`src/aac/agent.py`、`policy.py`、`relevance.py`、`world_model.py`、
  `viability.py` 及 `src/envs/` 出现 `op_` 调用即违规。agent 一律只持能力视图
  (ShellView / ValueChannelView),构造期即降级,不持原对象。
- 零跨仓 import;零业务词汇(评审时人工检查 + 将来加 lint 词表)。
- 版本控制:本仓库独立 git;面向 main 的变更走 PR;实验产出的大文件不入库。
