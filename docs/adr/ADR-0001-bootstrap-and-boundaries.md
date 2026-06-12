# ADR-0001: 仓库引导决策与边界

- Status: Accepted
- Date: 2026-06-12
- Deciders: founder(新建独立仓库拍板)+ agent(技术选型)

## Context

RR-0004 确立本仓库为对象层(通用智能体原型,主产物)。需要钉死技术底座与边界,
使任何 agent 可零摩擦接力。

## Decision

1. **Python ≥3.10,纯标准库**。备选 pytest/numpy/gymnasium 被否:原型期每个机制必须
   "裸露可读",第三方框架的隐性行为会污染机制实验;零依赖=任何环境即刻可跑。
   需要时按新 ADR 以 dev-extra 引入,核心不受影响。
2. **src layout + unittest**,与企业仓工程习惯一致,降低跨仓认知成本。
3. **边界**:零业务语义;零跨仓 import;`op_*` 罩面与 agent 代码路径分离(ENGINEERING §5);
   LLM 不进控制路径(器官 hook 留待 P4,需 founder 批准)。
4. **独立 git 仓库**,main 分支,PR 制;实验大文件不入库。

## Consequences

- 学习/绘图类能力受限——可接受,原型期可证伪性优先。
- 跨仓共享代码不可能——刻意如此,支撑关系只走 RR 规格/工作流门/未来内核依赖(RR-0004 §4)。
