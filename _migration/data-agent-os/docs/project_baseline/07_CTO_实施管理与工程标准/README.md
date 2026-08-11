# CTO 实施管理与工程标准

> 日期：2026-06-02  
> 角色视角：CEO / CTO  
> 用途：把现有产品战略、技术 PRD、阶段性落地方案和评测样本，转成 CEO 可决策、团队可执行、工程可验收的实施管理文件。

## 阅读顺序

### CEO / CTO 决策层

1. `Codex_CEO角色定义与项目专属Skill.md`
2. `CTO给CEO的实施决策简报.md`
3. `CTO_开发团队技术栈与下一步执行纪要_20260603.md`

### 交付治理层

4. `研发团队90天执行方案.md`
5. `工程标准_风险控制与交付SOP.md`
6. `开发团队Agent协作与交付SOP.md`

### Agent 治理层

7. `Agent角色与Skill配置总表.md`
8. `agent_skill_registry.yaml`
9. `架构师Agent角色与CTO审批流程.md`
10. `产品经理与项目经理Agent补充方案.md`
11. `Codex_CTO角色定义与项目专属Skill.md`
12. `Codex_PM角色定义与项目专属Skill.md`
13. `Business_Consultant角色定义与项目专属Skill.md`

### 工具与研究层

14. `Code_Agent_全面开发治理方案.md`
15. `AI全自动编码工作流编排_最优落地方案.md`
16. `AI_Agent工程化开发工作流_自研编排规范.md`
17. `Code_Agent开源辅助项目选型.md`
18. `GitHub开源项目选型调研.md`

## 文档定位

| 文档 | 面向对象 | 解决的问题 |
|---|---|---|
| `Codex_CEO角色定义与项目专属Skill.md` | CEO、创始团队、Codex CEO | 定义公司级战略、客户承诺、资本配置、路线图优先级和最终业务授权边界 |
| `CTO给CEO的实施决策简报.md` | CEO、创始团队、投资人沟通前内部决策 | 是否做、先做什么、不做什么、要投入什么资源、用什么指标判断成败 |
| `研发团队90天执行方案.md` | 产品、研发、数据、AI、测试、安全和解决方案团队 | 未来 90 天具体如何推进，谁负责什么，交付什么，如何验收 |
| `工程标准_风险控制与交付SOP.md` | 工程团队、Code Agent、评审人、交付负责人 | 代码、契约、数据安全、Agent、评测、发布、风险控制的统一标准 |
| `Code_Agent_全面开发治理方案.md` | CTO、研发负责人、AI 工程负责人、所有使用 Code Agent 的工程师 | 模型、AI IDE、Agent 角色、Prompt/Skill、工作流、质量门禁、token ROI、项目记忆规则 |
| `AI全自动编码工作流编排_最优落地方案.md` | CTO、DevOps、平台工程、AI 工程负责人 | 在脚本、n8n、CI/CD 三种模式中选择本项目最优自动化编排架构 |
| `架构师Agent角色与CTO审批流程.md` | CTO、架构师 Agent、研发负责人、后续实现 Agent | 强制先设计后实现，定义架构设计产物、架构师 prompt 和 CTO 审批门禁 |
| `Agent角色与Skill配置总表.md` | CTO、研发负责人、Agent Runner 负责人、所有工程 Agent | 定义项目所需全部 Agent、Skill、职责范围、工程目标、边界条件和交接关系 |
| `agent_skill_registry.yaml` | Agent Runner、Cursor/Codex 配置生成器、平台工程 | 机器可读的 Agent/Skill 注册表，用于后续生成实际 Agent 配置 |
| `产品经理与项目经理Agent补充方案.md` | CTO、产品负责人、项目负责人、Product/Project Manager Agent | 判断开工资料完备性，定义产品经理 Agent 和项目经理 Agent 的职责、产物和开工门槛 |
| `Codex_PM角色定义与项目专属Skill.md` | CEO、CTO、项目负责人、Codex PM | 定义 Codex 作为项目经理时的职责、边界、升级规则和本地 PM skill |
| `开发团队Agent协作与交付SOP.md` | CTO、Development Team Agent、实现 Agent、评审人 | 把已批准工程任务拆成 PR 级任务包，定义开发团队 Agent 路由、DoD、质量门禁和交付就绪判断 |
| `CTO_开发团队技术栈与下一步执行纪要_20260603.md` | CTO、Development Team Agent、Frontend/Backend/Eval/DevOps Agent | 固化开发团队内部沟通后的技术栈决策、禁用项、PR 顺序、语言分层共识和 CTO 门禁；语言边界以 `docs/decisions/ADR-0010-language-stack-boundaries.md` 为准 |

## 核心管理结论

第一阶段不以“完整 OS”作为研发目标，也不销售“替代 BI / 替代数仓”的宏大叙事。第一阶段只证明一个可被业务 owner 真实使用、可被工程团队稳定交付的可信业务生产闭环：

```text
业务问题
  -> BusinessIntent
  -> SemanticObject lite
  -> MetricContract
  -> ProviderContract lite
  -> DataProduct candidate
  -> SQL Safety / Eval
  -> EvidenceChain
  -> ActionProposal
  -> Approval lite
  -> Feedback / Trace lite
  -> KnowledgeAsset candidate
```

所有新增功能、架构抽象、连接器和 Agent 能力，都必须服务这个业务生产闭环。无法直接增强闭环验收的内容，默认延后。
