# FaSoLa 数据智能体商业化转型方案 v4

> 更新时间：2026-05-30  
> 适用阶段：内部经营提效 -> 私有化交付 -> 商业 SaaS  
> 核心定位：不是再做一个 ChatBI，而是做"由全模态数据智能分析驱动的自动化经营工作流平台"。

## 背景与目标

将 FaSoLa 从电商数据采集+分析中台，升级为 Data Agent 平台。参考帆软 Dora 的"知识库+数据库+指标库+算法库"架构，但采用更先进的 **Tool驱动 + Semantic Layer** 模式（而非传统RAG驱动）。

**架构演化依据**（2026年行业共识）：
- RAG 适用于非结构化文档检索（PDF/Markdown），不适合结构化知识（Schema/指标/规则）
- MCP/Tool Calling 是 Agent 获取结构化数据的主流方式
- 长上下文模型（32K+ tokens）可直接承载 Schema 摘要，无需分块向量检索
- Semantic Layer 是 Data Agent 准确性的根基——"Without it, agents answer fast but wrong"

## 用户决策摘要

| 维度 | 决策 |
|------|------|
| 目标用户 | 先内部运营团队 → 后续外部SaaS客户 |
| 实施节奏 | 完整架构设计 → 分阶段交付 → 2-4周MVP验证 |
| LLM策略 | 保留百炼(DashScope) + 新增本地部署(vLLM/Ollama)支持 |
| 知识架构 | **Tool驱动**（Schema/Metrics/Rules走Tool Call）+ 轻量RAG（仅文档） |
| 语义层深度 | **L3-智能语义层**（自动发现指标 + 口径冲突检测 + AI辅助对齐） |
| Tool层方案 | **Agent独立Tool Registry + MCP桥接** |
| 前端策略 | 重构现有Vue3前端，所有页面嵌入Chat侧边面板+悬浮按钮 |
| 开源策略 | 完全闭源 |


---

## 一句话定位

FaSoLa 应从"电商数据采集和分析中台"升级为：

**面向社媒电商和内容电商团队的全模态经营自动化智能平台。**

它持续采集广告、内容、商品、交易、竞品、评论、素材和运营动作数据，自动发现经营异常，解释原因，生成行动方案，经审批或风控后执行，并回收业务结果形成闭环。

Data Agent 是平台的推理和编排引擎，不是最终卖点。客户真正购买的是：

- 少开会：经营日报、周报、复盘自动生成。
- 少手工：跨平台数据采集、清洗、归因、报告自动化。
- 少漏异常：ROI、CPC、库存、素材疲劳、竞品动作主动预警。
- 更快决策：从"看到数据"缩短到"知道该做什么"。
- 更稳执行：审批、审计、回滚、效果验证一体化。

---

## 公司定位与商业化路径

### 内部阶段定位

内部先服务 FaSoLa 自身运营团队，不追求"通用 BI"，只追求"经营动作可落地"。

| 内部目标 | 具体衡量 |
|---|---|
| 报表自动化 | 每周节省人工报表和复盘时间 |
| 异常发现 | ROI/CPC/GMV/库存异常发现延迟缩短 |
| 指标口径统一 | ROI、ROAS、GMV、消耗、转化率等口径冲突减少 |
| 投放复盘 | 从单次投放复盘沉淀为可复用规则 |
| 内容复盘 | 从爆款内容结果倒推出素材、标题、标签、评论特征 |

### 商业 SaaS 阶段定位

外部客户优先选择"内容电商经营团队"，而不是泛行业数据团队。

| 阶段 | 客户画像 | 交付方式 | 核心卖点 |
|---|---|---|---|
| 内部验证 | FaSoLa 自营运营团队 | 内部部署 | 减少手工分析，提高异常响应速度 |
| 设计伙伴 | 1-3 家社媒电商品牌或代运营团队 | 私有化或半托管 | 小红书、抖音、广告、内容、交易一体化 |
| 早期商业化 | 中小品牌、代运营、内容电商团队 | 单租户 SaaS 或轻私有化 | 经营分析 Agent + 告警 + 报告 |
| 企业化 | 大品牌、多店铺、多事业部 | 私有化部署、专属 VPC | 数据不出域、审批审计、跨系统执行 |

### 不建议一开始服务的客户

- 只需要传统大屏和静态报表的客户。
- 没有稳定数据源、没有日常经营动作的客户。
- 只想买"聊天机器人"的客户。
- 需要强国产化全栈适配但预算不足的客户。
- 要求 Agent 无审批直接操作大额预算的客户。

---

## 产品蓝图

### 三层产品架构（与 §0.6 技术架构对应）

```
Layer 1: FaSoLa Data Intelligence
  数据采集、ETL、数仓、语义层、全模态资产、分析 Agent、预测模型

Layer 2: Hermes Decision Engine
  业务规则、风险评估、多目标优化、候选方案、审批路由、决策审计

Layer 3: OpenClaw Execution Gateway
  MCP 工具网关、平台动作执行、幂等、重试、回滚、业务结果回收
```

这三层可以先在同一代码仓库内模块化实现，等到负载、权限或交付边界明确后再拆成独立服务。

### 全模态数据资产层

原方案的结构化数据设计较完整，但"全模态"需要单独建层。

| 数据类型 | 例子 | 处理方式 | 产出 |
|---|---|---|---|
| 结构化数据 | 广告消耗、GMV、订单、库存 | ETL、指标语义层 | 指标、趋势、归因 |
| 半结构化数据 | API JSON、爬虫页面块 | schema 映射、实体解析 | 平台对象、事件 |
| 文档数据 | PDF、Markdown、运营 SOP | 文档 RAG | 知识问答、报告引用 |
| 图片 | 封面、商品图、达人图 | OCR、视觉标签、风格识别 | 素材特征 |
| 视频 | 短视频、直播切片 | 抽帧、ASR、镜头标签 | 创意节奏、卖点、口播 |
| 文本互动 | 评论、私信、评价 | 情绪、主题、意图、风险识别 | 用户反馈信号 |
| 操作轨迹 | 投放调整、库存变更、发布记录 | 审计、因果事件 | 行动效果验证 |

新增子目录：

```
multimodal_assets/
  ingestion/          # 图片、视频、音频、页面截图入库
  processors/         # OCR、ASR、抽帧、视觉标签、评论主题
  features/           # 素材特征、内容标签、达人特征
  evaluators/         # 素材疲劳、爆款相似度、评论风险
  storage/            # OSS/MinIO + PostgreSQL metadata
```

### 黄金业务闭环

先做 3 个能证明价值的闭环，不要同时铺开所有 Agent。

| 闭环 | 输入 | Agent 输出 | 执行动作 | 业务指标 |
|---|---|---|---|---|
| ROI 下滑处置 | 广告、GMV、CPC、CVR、计划数据 | 根因、影响范围、候选动作 | 创建提案、通知、低风险参数调整 | 异常响应时间、ROI 恢复速度 |
| 爆款内容复盘 | 笔记/短视频、评论、GMV、广告数据 | 爆款因子、可复制模板 | 生成选题和素材建议 | 内容复盘耗时、爆款命中率 |
| 经营日报自动化 | 多平台经营数据 | 日报、异常、待办、证据链 | 推送钉钉/企微、生成任务 | 人工报表时间、漏报率 |

---

## 产品化自主性分级（A0-A4 商业交付版）

建议把技术分级（L0-L4）转成产品分级，便于交付和销售。

| 产品等级 | 能力 | 是否可商用 | 说明 |
|---|---|---|---|
| A0 只读问答 | 查询、解释、图表 | 可以内部 MVP | 无写操作 |
| A1 分析建议 | 归因、预测、建议 | 可以试点 | 需要证据链 |
| A2 结构化提案 | 生成变更提案和审批单 | 商业化起点 | 不直接改生产 |
| A3 受监督执行 | 人批后执行、可回滚 | 企业版核心 | 适合私有化 |
| A4 约束自治 | 低风险动作自动执行 | 远期增值模块 | 预算、次数、范围严格受限 |

第一年不要承诺"高度自治"。对外表达应是：

**FaSoLa 是可审计、可审批、可回滚的经营自动化 Agent，而不是黑箱自动驾驶。**

---

## 0. 行业竞品与技术趋势深度调研

### 0.1 行业头部产品对标

#### SmartBI 白泽 V5（市场领导者）

**架构**："指标体系 + 多智能体协同" 双轮驱动，三层 Agent BI 架构：

```
┌─────────────────────────────────────────────┐
│  应用层: 智能问数、归因分析、异常预警、报告     │
├─────────────────────────────────────────────┤
│  智能体引擎层:                                │
│  • ReAct 推理 (执行→观察→反思→重规划)        │
│  • Skills 技能体系 (报告/填报/归因/看板)      │
│  • 多智能体协同 (生成→验证→修正→评估)         │
│  • 四层复合计算引擎 (SQL/Spark/Python/MDX)    │
├─────────────────────────────────────────────┤
│  可信数据底座:                                │
│  • 统一指标模型 (口径/规则/权限一体化)        │
│  • 动态数据模型 (自动生成最小关联路径)        │
│  • 企业知识库 RAG (术语/规则/模板/经验)       │
│  • 多源数据融合 (结构化+非结构化)             │
└─────────────────────────────────────────────┘
```

**核心指标**：准确率 99%+（核心指标查询可达 100%），专利 ZL202511851168.8
**技术栈**：通义千问/文心一言/DeepSeek 等主流LLM + 私有化部署支持
**弱项**：BI 工具基因重，对非 BI 场景灵活度有限

#### Aloudata Agent（NoETL 路线）

**架构**："NoETL 语义层 + Agentic Harness"

| 层次 | 设计 |
|------|------|
| **NoETL 语义层** | 原子指标 × 时间 × 业务限定 × 衍生方式 → 100%准确SQL |
| **NL2MQL2SQL** | 自然语言→指标查询语言(MQL)→SQL，双层转换避免幻觉 |
| **Agentic Harness** | 想-做-验-纠 循环，动态记忆(长短结合)，"越用越懂你" |
| **Skill 体系** | 可插拔专业分析方法论，归因分析/趋势预测/异常检测 |

**核心创新**：指标语义层作为中间语言，避免 NL→SQL 直接转换的准确率问题
**弱项**：需要先建立完整的 NoETL 语义层，前期建设成本高

#### DB-GPT（开源参考）

**架构**：AWEL(Agent工作流引擎) + SMMF(多模型管理) + RAG + Multi-Agent
**技术栈**：Python + LangChain / 自研 AWEL + ChromaDB + DeepSeek/Qwen/GLM
**启示**：多Agent角色分工 + 沙箱执行 + 可插拔模型是最佳开源实践

### 0.2 Data Agent 自主性等级（L0-L4）

来源：arxiv 2602.04261 "Data Agents: Levels, State of the Art, and Open Problems"

| 等级 | 名称 | 能力 | FaSoLa 现状 | 目标 |
|------|------|------|-------------|------|
| **L0** | 无自主性 | 所有数据任务手动完成 | — | — |
| **L1** | 辅助级 | 无状态问答(NL2SQL建议)，人执行 | — | 已超越 |
| **L2** | 部分自主 | Agent自主执行子任务，人在预设管道内 | 内容分析管道(多Agent但固定流程) | Phase 1 达到 |
| **L3** | 条件自主 | Agent自主编排定制化管道，人监督 | ❌ | Phase 3-4 目标 |
| **L4** | 高度自主 | 持续监控、主动发现问题、自主重设计管道 | ❌ | 远期愿景 |

**L2→L3 的关键跃迁**：
- 从"人在管道内"到"人在回路上"（human-in-the-loop → human-on-the-loop）
- Agent 不仅执行预定义任务，还能提出新的分析方案、发现指标异常并主动调查
- 需要 governance layer（审批/审计/回滚机制）

### 0.3 关键技术趋势：Agent驱动的系统更新

这是本次调研的**核心发现**——顶级 Data Agent 正在从"只读查询"走向"自治运维"：

```
传统 Data Agent (L1-L2)          下一代 Data Agent (L3)
─────────────────────────       ─────────────────────────
"过去7天ROI为什么下降？"         "过去7天ROI下降，CPC上升是主因。
                                 我已调整了千川出价策略参数，
                                 并为3个高CPC计划设置了告警。
                                 这是变更记录，要批准吗？"
```

**Agentic ETL 模式**（来源：Agentic ETL + Databricks AI ETL）：
- 自动异常检测 → 基于统计基线识别数据漂移
- 自修复 → 自动补全缺失值、适配 schema 变更
- 自主决策 → Agent 判断新数据源、解决质量问题、优化流程

**AutoML-Agent 模式**（来源：ICML 2026 AutoML-Agent）：
- 检索增强规划 → 生成多个候选 ML 管道方案
- 并行专用Agent → 数据预处理/特征工程/模型选择/超参调优
- 多阶段验证 → 确保生成代码正确性
- 部署就绪 → 产出可直接部署的模型

### 0.4 FaSoLa 差异化定位

对比行业竞品，FaSoLa 有**三重独特优势**：

| 优势 | 说明 | 竞品差距 |
|------|------|----------|
| **全链路闭环** | 采集→ETL→数仓→分析→ML→Agent，数据不出域 | SmartBI/Aloudata 只管分析层，不管采集 |
| **垂类深度** | 小红书+抖音电商深度理解，7个北极星指标+34个ADS宽表 | 通用BI产品对电商术语理解浅 |
| **ML 工程化** | 已有3个ML模型+SGD/RandomForest/ONNX+AB测试框架 | 多数竞品ML能力挂在LLM上，非原生 |

**差异化打法**：不是做"又一个 ChatBI"，而是做 **"电商垂类自治数据分析中台"**——Agent 不仅能回答数据问题，还能驱动数据采集、ETL清洗、模型更新。

---

## 0.5 Agentic Operations 架构（新增 L3 能力）

这是方案 v3 最重要的新增内容。解决核心问题：**Agent 如何结合 ML/DL 模型训练、应用模型结果、配合 ETL 固定流程、灵活更新数据分析体系？**

### 双反馈环架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    FaSoLa Data Agent (L3 Target)                 │
│                                                                  │
│  ┌──────────────────────────┐    ┌──────────────────────────┐   │
│  │  FAST LOOP (分钟-小时)     │    │  SLOW LOOP (天-周)        │   │
│  │                           │    │                           │   │
│  │  用户提问                   │    │  Agent 持续监控           │   │
│  │    ↓                      │    │  (数据质量/模型性能/       │   │
│  │  Agent 查询+分析           │    │   指标异常/ETL延迟)       │   │
│  │    ↓                      │    │    ↓                      │   │
│  │  返回洞察+建议              │    │  发现问题 → 分析根因     │   │
│  │    ↓                      │    │    ↓                      │   │
│  │  用户确认参数调整           │    │  生成变更提案             │   │
│  │  (如: 调整告警阈值)         │    │  (ETL修改/ML重训练/       │   │
│  │                           │    │   指标更新/参数优化)       │   │
│  │                           │    │    ↓                      │   │
│  │                           │    │  Governance Agent 预审     │   │
│  │                           │    │    ↓                      │   │
│  │                           │    │  → Hermes 精细化评估      │   │
│  │                           │    │  (规则引擎+多目标优化)     │   │
│  │                           │    │    ↓                      │   │
│  │                           │    │  审批路由(高/中/低风险)    │   │
│  │                           │    │    ↓                      │   │
│  │                           │    │  → OpenClaw 执行          │   │
│  │                           │    │    ↓                      │   │
│  │                           │    │  → 业务结果反馈→FaSoLa    │   │
│  │                           │    │  (闭环:分析→决策→执行)     │   │
│  └──────────────────────────┘    └──────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 四个 Operations Agent

```python
# data_agent/operations/  (Phase 3 新增)
# 这些Agent不同于查询/分析Agent——它们能修改生产系统

data_agent/operations/
├── __init__.py
├── governance.py          # GovernanceAgent: 变更审批+风险评估+回滚
├── pipeline_agent.py      # PipelineAgent: ETL质量监控+自动修复+优化建议
├── ml_agent.py            # MLAgent: 模型性能监控+触发重训练+超参调优
└── parameter_agent.py     # ParameterAgent: 算法参数优化+AB测试+灰度发布
```

### ML/DL 模型生命周期管理

```
现有 ML 基础设施 (shared_lib/ml/)         Agent 增强 (data_agent/operations/ml_agent.py)
─────────────────────────────         ─────────────────────────────────────
ModelBase (ABC)                       MLAgent.monitor_model_health()
  .load() / .predict() / .save()        → 每日检查预测准确率/召回率
                                        → 检测 data drift (特征分布变化)
ModelRegistry (Singleton)              → 触发 alert: "HitScorer 准确率下降12%"
  .get_model_class() / .list_models()
                                       MLAgent.propose_retraining()
ModelVersion (SemVer)                    → 评估: 新数据量是否足够重训练
  .find_latest_version()                → 提案: 使用最近30天数据重训练RandomForest
ABTestFramework                         → 沙箱验证: 新模型 vs 旧模型 A/B 对比
  确定性哈希流量分割                       → 生成报告: 新模型AUC提升0.03
                                 
                                    GovernanceAgent.review()
                                      → 风险评估: 低风险(模型文件可回滚)
                                      → 创建审批: → 钉钉通知管理员
                                      → 批准后: 自动 save_model() + 更新版本
```

### Agent 与 ETL 的融合模式

```
现有 ETL 管道 (57条, data_warehouse/etl/)   Agentic ETL 增强 (Phase 3)
──────────────────────────────────────     ──────────────────────────
BaseETL                                    PipelineAgent
  .execute() 固定逻辑                        .monitor_pipeline_health()
  @register_etl 注册                           → 检测: content_performance ETL
                                               → 连续3天空数据 → 采集器故障
                                             .diagnose_root_cause()
                                               → 追溯: 上游 dwd_content_daily
                                               → 最后一条数据 2026-06-02
                                               → 推断: 采集器6月3日起未运行
                                             .propose_fix()
                                               → 提案: 重启采集器+回填6月3-5日
                                               → 修改 scheduler 增加探活
                                              
DataLineageTracker                        ColumnLineageTracker (L3升级)
  表级血缘                                   → 列级血缘
  ads ← dws ← dwd ← ods                    → ads.spend ← dws.total_spend
                                             ← dwd.ad_spend ← ods.juguang_report.spend
                                             
                                          ParameterAgent
                                            .optimize_etl_parameters()
                                               → 分析: RFM分段阈值3个月未更新
                                               → 提案: 基于最新数据重新计算分位数
                                               → 更新: R/F/M 分位阈值
                                            .adjust_algorithm_parameters()
                                               → 检测: Holt-Winters α=0.3 预测偏差增大
                                               → 提案: 网格搜索最优 α∈[0.1,0.5]
                                               → 更新: north_star_metrics 的平滑参数
```

### Governance 审批工作流

```
Agent 发现 → 自动分析 → 生成变更提案
                          │
                          ▼
              ┌─────────────────────┐
              │  GovernanceAgent     │
              │                      │
              │  1. 风险评估          │
              │     • 影响范围         │
              │     • 可逆性           │
              │     • 紧急度           │
              │                      │
              │  2. 沙箱验证(自动)     │
              │     • ETL变更→dry-run │
              │     • ML变更→AB对比   │
              │     • 参数变更→回测   │
              │                      │
              │  3. 审批路由          │
              │     • 低风险→自动批准  │
              │     • 中风险→钉钉审批  │
              │     • 高风险→人工确认  │
              │                      │
              │  4. 灰度部署          │
              │     • 先10%流量→观察  │
              │     • 无异常→全量     │
              │                      │
              │  5. 回滚就绪          │
              │     • 保留旧版本       │
              │     • 一键回滚         │
              └─────────────────────┘
```

### 与竞品的核心差异

| 能力 | SmartBI 白泽 | Aloudata Agent | **FaSoLa Data Agent** |
|------|-------------|----------------|----------------------|
| NL2分析 | ✅ ReAct + Skills | ✅ Agentic Harness | ✅ Tool调用 + Multi-Agent |
| 语义层 | ✅ 统一指标模型 | ✅ NoETL语义层 | ✅ **L3智能语义层**(自动发现+冲突检测) |
| ML模型 | ❌ 依赖LLM推理 | ❌ 依赖LLM推理 | ✅ **原生ML模型**(SGD/RF/ONNX) |
| ETL自治 | ❌ 无 | ⚠️ NoETL(绕过ETL) | ✅ **Agentic ETL**(监控+修复+优化) |
| 模型重训练 | ❌ 无 | ❌ 无 | ✅ **ML Agent触发+AB验证+审批** |
| 参数自优化 | ⚠️ 阈值告警 | ❌ 无 | ✅ **Parameter Agent**(回测+灰度) |
| 数据采集 | ❌ 无 | ❌ 无 | ✅ **全链路闭环**(采集→ETL→分析→Agent) |
| 审批治理 | ⚠️ 权限控制 | ⚠️ 口径审计 | ✅ **Governance Agent**(4级审批+灰度+回滚) |

---

## 0.6 OpenClaw + Hermes 三层闭环业务自动化架构（新增 L3→L4 关键桥接）

这是方案 v4 最重要的架构跃迁。解决核心问题：**Data Agent 分析结果如何驱动业务自动执行？数据洞察如何转化为业务行动？**

### 三层架构总览

```
┌──────────────────────────────────────────────────────────────────────┐
│                    FaSoLa 全域智能业务自动化平台                        │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │           LAYER 3: OpenClaw 执行网关 (EXECUTION)               │   │
│  │                                                                │   │
│  │  "hands" — 将决策转化为跨系统的业务动作                           │   │
│  │                                                                │   │
│  │  ┌───────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐  │   │
│  │  │ 千川投放   │ │ 聚光投放  │ │ 小红书发布 │ │ 电商平台后台   │  │   │
│  │  │ 计划管理   │ │ 广告管理  │ │ 笔记管理  │ │ 商品/库存/价格 │  │   │
│  │  └─────┬─────┘ └────┬─────┘ └────┬─────┘ └───────┬───────┘  │   │
│  │        │            │            │               │          │   │
│  │  ┌─────▼────────────▼────────────▼───────────────▼───────┐  │   │
│  │  │              MCP Gateway (统一工具协议)                  │  │   │
│  │  │  已有: xiaohongshu_mcp (小红书发布, :18060)              │  │   │
│  │  │  新增: qianchuan_mcp, juguang_mcp, ecom_mcp             │  │   │
│  │  └─────────────────────────┬───────────────────────────────┘  │   │
│  └────────────────────────────┼──────────────────────────────────┘   │
│                               │ Execution requests                    │
│  ┌────────────────────────────▼──────────────────────────────────┐   │
│  │           LAYER 2: Hermes 决策引擎 (DECISION)                   │   │
│  │                                                                  │   │
│  │  "brain" — 基于多维度输入做最优业务决策                             │   │
│  │                                                                  │   │
│  │  ┌────────────────────────────────────────────────────────┐     │   │
│  │  │  Decision Pipeline                                      │     │   │
│  │  │                                                         │     │   │
│  │  │  数据洞察 ─→ 规则引擎 ─→ 风险评估 ─→ 多目标优化 ─→ 执行计划  │     │   │
│  │  │    │           │           │           │            │    │     │   │
│  │  │    │     ┌─────▼─────┐     │     ┌─────▼──────┐     │    │     │   │
│  │  │    │     │ Business  │     │     │ Optimization│     │    │     │   │
│  │  │    │     │ Rules     │     │     │ Engine      │     │    │     │   │
│  │  │    │     │  • ROI阈值│     │     │ • 预算分配   │     │    │     │   │
│  │  │    │     │  • 风控规则│     │     │ • 出价策略   │     │    │     │   │
│  │  │    │     │  • 预算上限│     │     │ • 时间调度   │     │    │     │   │
│  │  │    │     │  • 审批规则│     │     │ • 流量配比   │     │    │     │   │
│  │  │    │     └───────────┘     │     └─────────────┘     │    │     │   │
│  │  └────────────────────────────┼────────────────────────┘     │   │
│  │                               │                               │   │
│  │  ┌────────────────────────────▼────────────────────────┐     │   │
│  │  │  Decision Record (决策审计)                            │     │   │
│  │  │  • 每个决策都有 trace_id + decision_id               │     │   │
│  │  │  • 决策前: 输入数据 + 触发条件 + 候选方案               │     │   │
│  │  │  • 决策后: 执行结果 + 业务指标变化 + 回滚就绪            │     │   │
│  │  └──────────────────────────────────────────────────────┘     │   │
│  └────────────────────────────┬──────────────────────────────────┘   │
│                               │ Insights + Proposals                  │
│  ┌────────────────────────────▼──────────────────────────────────┐   │
│  │           LAYER 1: FaSoLa Data Agent (ANALYSIS)                 │   │
│  │                                                                  │   │
│  │  "eyes & memory" — 数据采集→ETL→数仓→分析→ML→Agent              │   │
│  │  已在 §0.5 中定义的双反馈环 + 4个 Operations Agent               │   │
│  │  本层输出: 结构化洞察 + 归因分析 + 预测 + 变更提案                  │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                       │
│                    ◄────── Business Feedback Loop ──────►              │
│                                                                       │
│  广告投放 → 数据回流 → FaSoLa分析 → Hermes决策 → OpenClaw执行         │
│      ▲                                                       │        │
│      └─────────── 业务结果反馈 (ROI/转化/销量) ◄───────────────┘        │
└──────────────────────────────────────────────────────────────────────┘
```

### 三个系统的职责边界

| 系统 | 角色 | 类比 | 输入 | 输出 | 时效性 |
|------|------|------|------|------|--------|
| **FaSoLa Data Agent** | 分析层 (eyes & memory) | 分析师团队 | 全链路数据(采集→数仓) | 结构化洞察、归因、预测、变更提案 | 分钟-小时 |
| **Hermes** | 决策层 (brain) | 营销总监+财务总监 | FaSoLa洞察 + 业务规则 + 预算约束 | 最优执行计划(做什么/做多少/什么时候) | 秒-分钟 |
| **OpenClaw** | 执行层 (hands) | 投放团队+运营团队 | Hermes执行计划 | 跨系统的实际业务动作 | 毫秒-秒 |

### 闭环数据流详解

```
[Step 1: 数据采集]  data_collector 采集各平台广告/内容/交易数据
        │
        ▼
[Step 2: ETL+数仓]  ODS→DWD→DWS→ADS, 57条ETL管道, 7个北极星指标
        │
        ▼
[Step 3: FaSoLa分析] 
        │
        ├─ Fast Loop: 用户提问 "这周千川ROI为什么下降?"
        │   → resolve_metric("千川ROI") → execute_query → run_attribution
        │   → 输出: "CPC上升23%是主因，计划A/B/C的转化率同时下降"
        │
        └─ Slow Loop: PipelineAgent 监控 → 数据异常检测
            → 输出: 结构化洞察 + 变更提案
        │
        ▼
[Step 4: Hermes决策]  
        │
        ├─ 接收FaSoLa的结构化洞察
        ├─ 匹配业务规则: "千川ROI < 2.0 → 触发投放策略审查"
        ├─ 风险评估: "CPC超出阈值 → 检查是否竞争加剧或素材疲劳"
        ├─ 多目标优化: 
        │   • 目标1: ROI最大化 (权重0.6)
        │   • 目标2: GMV不低于$5000/天 (硬约束)
        │   • 目标3: 消耗不超预算$700/天 (硬约束)
        │   → 求解: 计划A降价10%+计划B暂停+计划C加预算20%
        │
        └─ 生成执行计划:
           {
             "decision_id": "D20260605-001",
             "trace_id": "T20260605-142300",
             "actions": [
               {"platform": "qianchuan", "action": "adjust_bid", 
                "plan_id": "A", "bid_change": -0.10},
               {"platform": "qianchuan", "action": "pause_plan", 
                "plan_id": "B"},
               {"platform": "qianchuan", "action": "adjust_budget", 
                "plan_id": "C", "budget_change": +0.20}
             ],
             "expected_impact": {"roi_improvement": "+0.3", "gmv_impact": "-50"},
             "rollback_plan": "还原计划A/B/C到调整前状态"
           }
        │
        ▼
[Step 5: OpenClaw执行]
        │
        ├─ 通过 MCP Gateway 调用各平台工具:
        │   • qianchuan_mcp: adjust_bid(plan_A, -10%)
        │   • qianchuan_mcp: pause_plan(plan_B)
        │   • qianchuan_mcp: adjust_budget(plan_C, +20%)
        │
        └─ 记录执行结果:
           {
             "execution_id": "E20260605-002",
             "decision_id": "D20260605-001",
             "status": "completed",
             "actions_completed": 3,
             "actions_failed": 0
           }
        │
        ▼
[Step 6: 业务反馈]  
        │
        ├─ 24h后: FaSoLa 采集器自动拉取最新数据
        ├─ ETL管道更新 ads_north_star_trend
        ├─ ML Agent 对比: 预期ROI +0.3 vs 实际ROI +0.28
        ├─ 反馈到 Hermes: "决策D20260605-001效果接近预期，偏差-0.02"
        │
        └─ 闭环完成 → Hermes 更新决策模型 → 下次决策更精准
```

### Hermes 决策引擎核心能力

```python
# 决策引擎接口设计 (部署在独立服务或 data_agent 子模块中)

class HermesDecisionEngine:
    """Hermes 决策引擎 - 将数据洞察转化为业务决策"""
    
    # 1. 规则引擎
    async def evaluate_rules(
        self, 
        insights: DataInsight,      # FaSoLa 输出的结构化洞察
        context: BusinessContext,   # 当前业务状态 (预算/库存/竞品)
    ) -> list[TriggeredRule]:
        """匹配业务规则:
        - 千川ROI < 2.0 → 触发投放策略审查
        - 某计划连续3天CPC上升 → 触发素材审查
        - 库存 < 安全阈值 → 触发补货预警
        - 竞品大规模投放 → 触发防御策略
        """
    
    # 2. 多目标优化引擎
    async def optimize(
        self,
        objectives: list[Objective],    # ROI最大化 + GMV硬约束 + 预算硬约束
        constraints: list[Constraint],
        decision_variables: list[Variable],  # 可调参数
        model_type: str = "linear",    # linear/milp/bandit/bayesian
    ) -> OptimizationResult:
        """求解最优执行方案:
        - 线性规划: 预算分配问题
        - 多臂老虎机: 探索vs利用 (新素材测试)
        - 贝叶斯优化: 出价参数调优
        """
    
    # 3. 风险评估
    async def assess_risk(
        self,
        decision: DecisionPlan,
        context: BusinessContext,
    ) -> RiskAssessment:
        """决策风险评估:
        - 预算超支风险
        - 效果不达预期风险
        - 平台政策风险 (如: 千川出价调整频率限制)
        - 回滚可行性
        """
    
    # 4. 决策记录 (审计)
    async def record_decision(
        self,
        decision: DecisionPlan,
        execution_result: ExecutionResult | None = None,
    ) -> DecisionRecord:
        """完整决策审计链:
        - 什么数据触发了决策 (trace_id → FaSoLa 查询)
        - 有哪些候选方案
        - 为什么选择了这个方案 (优化过程可解释)
        - 执行结果如何
        """
```

### OpenClaw 执行网关核心能力

```python
# 执行网关接口设计 (独立服务或集成到现有 MCP 体系)

class OpenClawExecutionGateway:
    """OpenClaw 执行网关 - 将决策转化为跨系统业务动作"""
    
    # 1. MCP 工具聚合
    def __init__(self):
        self.mcp_gateways = {
            "qianchuan": QianchuanMCPGateway(),   # 千川广告操作
            "juguang": JuguangMCPGateway(),        # 聚光广告操作
            "xhs_publish": XiaoHongShuMCPGateway(), # 小红书发布 (已有 xiaohongshu_mcp)
            "ecommerce": EcommerceMCPGateway(),    # 电商后台 (商品/库存/价格)
            "notification": NotificationGateway(), # 钉钉/企微/飞书通知
        }
    
    # 2. 执行计划编排
    async def execute(
        self,
        plan: DecisionPlan,  # Hermes 输出的执行计划
    ) -> ExecutionResult:
        """按序/并行执行多个业务动作:
        - 并行: 同时调整千川多个计划出价
        - 串行: 先暂停计划B, 再重新分配预算到计划C
        - 条件: 如果执行失败 → 立即通知 → 等待人工介入
        """
    
    # 3. 执行幂等性
    async def execute_idempotent(
        self,
        action: BusinessAction,
        idempotency_key: str,  # decision_id + action_index
    ) -> ActionResult:
        """确保同一动作不会重复执行:
        - Redis 记录: {idempotency_key} = {"status": "executed", "result": ...}
        - 重试时直接返回已记录结果
        """
    
    # 4. 回滚执行
    async def rollback(
        self,
        execution_id: str,
    ) -> RollbackResult:
        """撤销之前执行的业务动作:
        - 还原出价到执行前水平
        - 恢复暂停的计划
        - 还原预算分配
        """
    
    # 5. 执行审计
    async def get_execution_log(
        self,
        decision_id: str,
    ) -> ExecutionAuditLog:
        """完整可审计的执行日志"""
```

### 与现有 §0.5 双反馈环的融合

```
┌──────────────────────────────────────────────────────────────────┐
│  原双反馈环 (§0.5)           →     融合 Hermes/OpenClaw 后       │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Fast Loop (分析+建议)              Fast Loop (分析→决策→执行)     │
│                                                                   │
│  用户提问                           用户提问                       │
│    ↓                                  ↓                            │
│  Agent 查询+分析                    Agent 查询+分析                │
│    ↓                                  ↓                            │
│  返回洞察+建议                      返回洞察+选项                  │
│    ↓                                  ↓                            │
│  用户确认参数调整        →          用户选方案 → Hermes生成执行计划 │
│                                          ↓                        │
│                                      OpenClaw执行                 │
│                                          ↓                        │
│                                      业务结果反馈                  │
│                                                                   │
│  Slow Loop (监控+提案)              Slow Loop (监控→决策→执行→反馈) │
│                                                                   │
│  Agent持续监控                      Agent持续监控                  │
│    ↓                                  ↓                            │
│  发现问题→分析根因                  发现问题→分析根因              │
│    ↓                                  ↓                            │
│  生成变更提案                       生成变更提案                   │
│    ↓                                  ↓                            │
│  Governance Agent审核               Governance Agent预审           │
│    ↓                                  ↓                            │
│  (原终点: 人工审批)      →          Hermes评估(规则+优化+风险)     │
│                                          ↓                        │
│                                      人工审批(高风险) / 自动(低风险)│
│                                          ↓                        │
│                                      OpenClaw执行                  │
│                                          ↓                        │
│                                      业务结果 → FaSoLa验证 → 闭环  │
└──────────────────────────────────────────────────────────────────┘
```

### MCP Gateway 扩展计划

```
现有 MCP 生态:
  xiaohongshu_mcp (:18060) — Go + rod, 小红书发布操作  [已运行]

新增 MCP Gateways (Phase 3-4):
  qianchuan_mcp   — Python, 千川广告管理 (计划/出价/预算/报表)
  juguang_mcp     — Python, 聚光广告管理 (广告组/创意/投放)
  ecom_mcp        — Python, 电商中台 (商品上下架/价格调整/库存同步)
  notification_mcp — Python, 通知网关 (钉钉/企微/飞书/邮件)

所有 MCP Gateway 统一注册到 AgentToolRegistry → MCPToolRegistry 桥接
```

### Hermes/OpenClaw 部署架构

```
┌─────────────────────────────────────────────────────┐
│                  GPU Server (RTX PRO 5000 48G)       │
│                                                       │
│  ┌──────────────┐  ┌──────────────┐                  │
│  │ vLLM Server  │  │ Ollama       │                  │
│  │ (Qwen3-32B)  │  │ (DeepSeek-V3)│                  │
│  └──────┬───────┘  └──────┬───────┘                  │
│         │                 │                           │
│  ┌──────▼─────────────────▼───────┐                  │
│  │      FaSoLa Chat Server        │                  │
│  └──────────────┬─────────────────┘                  │
│                 │                                     │
│  ┌──────────────▼─────────────────┐                  │
│  │     Hermes Decision Engine     │                  │
│  │  (FastAPI, 独立进程或嵌入)      │                  │
│  │  • 规则引擎: Redis + PostgreSQL │                  │
│  │  • 优化引擎: scipy.optimize     │                  │
│  └──────────────┬─────────────────┘                  │
│                 │                                     │
│  ┌──────────────▼─────────────────┐                  │
│  │     OpenClaw Gateway           │                  │
│  │  (Celery Worker + MCP Client)  │                  │
│  │  • 异步执行 + 重试 + 幂等       │                  │
│  └────────────────────────────────┘                  │
│                                                       │
└─────────────────────────────────────────────────────┘
```

### L3→L4 的跃迁：何时让 Hermes 自动决策

| 场景 | 当前 (L3) | 目标 (L4) |
|------|-----------|-----------|
| 千川出价调整 | FaSoLa建议 → 人工确认 → OpenClaw执行 | Hermes自动决策(低风险参数，如±5%以内) |
| 预算重新分配 | 人工判断+审批 | Hermes多目标优化+自动执行(预算上限约束) |
| 素材疲劳替换 | 人工发现+手动替换 | FaSoLa检测素材疲劳 → Hermes触发替换 → OpenClaw执行 |
| 异常计划暂停 | 人工监控+手动暂停 | FaSoLa检测异常 → Hermes确认 → OpenClaw自动暂停 |
| 补货预警 | 数仓报表+手动操作 | FaSoLa库存预测 → Hermes计算最优补货量 → OpenClaw下单 |

**L4 安全护栏**：
- 单次自动决策金额上限 (如: ¥500)
- 每日自动决策次数上限 (如: 20次)
- 关键参数必须人工审批 (如: 日预算 > ¥5000)
- 所有自动决策记录在案，支持一键回滚

---

## 一、核心架构哲学：Tool驱动 vs RAG驱动

```
                    ❌ RAG驱动（已淘汰）              ✅ Tool驱动（2026正确方案）
                    
Schema知识    →  向量化所有DDL                   →  System Prompt注入Schema摘要
                  RAG近似检索                         Tool describe_table() 精确查询
                  向量检索准确率~90%                   100%准确

指标定义      →  向量化指标文档                   →  Semantic Layer API
                  RAG检索相似指标                     Tool resolve_metric() 精确解析
                  "ROI"可能返回多个相似结果           口径冲突自动检测+澄清

业务规则      →  向量化规则文档                   →  Tool get_rules() 结构化返回
                  语义匹配不确定                      规则逻辑直接执行

文档知识      →  ✅ RAG保留                       →  ✅ RAG保留
                 （RAG真正适用的场景）                 PDF/Markdown/会议纪要语义搜索
```

### 知识来源三分法

| 知识类型 | 获取方式 | 延迟 | 准确性 | 实现 |
|----------|----------|------|--------|------|
| **Schema元数据** | System Prompt（摘要）+ Tool（详情） | <1ms / ~5ms | 100% | `SchemaTool` |
| **指标定义** | Semantic Layer API | ~2ms | 100% + 冲突检测 | `MetricTool` |
| **业务规则** | Tool Call 结构化返回 | ~2ms | 100% | `RuleTool` |
| **文档知识** | pgvector RAG | ~20ms | ~90% | `DocSearchTool` |
| **数据查询** | SQL Tool（读白名单） | ~50ms | 100% | `SQLTool` |
| **分析计算** | Python Sandbox | ~500ms | 100% | `PythonTool` |

---

## 二、新增子项目结构（修正版）

### 2.1 `data_agent/` — 核心智能体引擎

```
data_agent/
├── pyproject.toml
├── core/
│   ├── __init__.py
│   ├── orchestrator.py        # AgentOrchestrator: Planner→Exec→Judge循环
│   ├── planner.py             # TaskPlannerAgent: NL→Tool调用计划DAG
│   ├── sql_agent.py           # SQLAgent: NL2SQL (通过SchemaTool获取上下文)
│   ├── python_agent.py        # PythonAgent: 沙箱化分析 (调用shared_lib/analytics)
│   ├── analyst_agent.py       # AnalystAgent: 数据解读+归因+洞见
│   ├── reporter_agent.py      # ReporterAgent: 多格式报告生成
│   ├── deep_research.py       # DeepResearchAgent: 网络搜索+交叉分析
│   ├── session_manager.py     # ConversationSessionManager: 多轮上下文(Redis)
│   └── prompt_builder.py      # SystemPromptBuilder: 动态构建system prompt
│       │                       #   (注入Schema摘要+核心指标+用户上下文)
├── tools/                     # ★ Agent独立Tool Registry（替代knowledge/）
│   ├── __init__.py
│   ├── registry.py            # AgentToolRegistry: 增强版工具注册中心
│   │   # 基于现有MCPRegistry模式，增加:
│   │   # - 参数类型验证(required/type/enum)
│   │   # - 执行包装(错误标准化+审计日志)
│   │   # - OpenAI function-calling格式转换
│   │   # - 工具分类(category)/版本/超时
│   │   # - 延迟加载(避免导入时注册重量依赖)
│   │   # - 权限标注(@require_permission)
│   ├── schema_tools.py        # SchemaTool: list_tables(), describe_table(),
│   │   #   search_columns(), get_relationships()
│   │   #   直接查 information_schema + ORM metadata
│   ├── metric_tools.py        # MetricTool: resolve_metric(), list_metrics(),
│   │   #   get_metric_formula(), detect_conflicts()
│   │   #   查 metadata.metric_glossary + Semantic Layer
│   ├── rule_tools.py          # RuleTool: get_business_rules(),
│   │   #   validate_threshold(), check_data_quality()
│   ├── sql_tools.py           # SQLTool: execute_query(), explain_sql()
│   │   #   白名单schema + 注入防护 + 行数限制
│   ├── analysis_tools.py      # AnalysisTool: run_attribution(), run_forecast(),
│   │   #   run_ab_test(), run_cohort()
│   │   #   包装 shared_lib/analytics/ 模块为Agent可调用工具
│   ├── doc_search_tools.py    # DocSearchTool: search_docs()
│   │   #   ★ 唯一的RAG入口：pgvector语义搜索文档
│   │   #   文档分块+embedding+检索，仅用于非结构化文档
│   └── platform_tools.py      # PlatformTool: get_platform_config(),
│       #   get_ces_weights(), get_traffic_pools()
│       #   暴露 platform_analysis_config.py 的配置
├── semantic/                  # L3智能语义层
│   ├── __init__.py
│   ├── metric_registry.py     # MetricRegistry: 中心化指标注册表
│   │   # 从3个来源聚合指标: metric_glossary表 + ORM模型 + ETL代码
│   │   # 解决"单一真相来源"问题
│   ├── auto_discovery.py      # MetricAutoDiscovery: 自动发现新指标
│   │   # 扫描 information_schema.columns (Numeric类型 → 潜在指标)
│   │   # 扫描 ORM模型注释 (含 "ROI/ROAS/率/额/比" → 候选指标)
│   │   # 扫描 ETL代码 AST (赋值语句的左侧 → 计算指标)
│   │   # 增量同步到 metric_glossary 表
│   ├── conflict_detector.py   # MetricConflictDetector: 口径冲突检测
│   │   # 同名字段在不同平台的口径差异
│   │   #   "ROI" in juguang vs qianchuan → 分母不同(消耗 vs GMV)
│   │   # 公式验证: 文档公式 vs ETL实际计算 vs ORM comment
│   │   # 输出冲突报告 → 人工/LLM裁决
│   ├── entity_resolver.py     # EntityResolver: NL实体→DB列/表映射
│   │   # "千川ROI" → platform=douyin, metric=qianchuan_roi
│   │   # "昨天的销售额" → metric=gmv, time=yesterday
│   ├── query_validator.py     # QueryValidator: SQL安全+语义校验
│   │   # 语法检查 + 表/列存在性 + 类型兼容 + 危险操作拦截
│   ├── lineage_tracker.py     # ColumnLineageTracker: 列级血缘
│   │   # 扩展 shared_lib/monitoring/data_lineage.py
│   │   # 从表级血缘 → 列级血缘 (ads.spend → dws.total_spend → dwd.spend)
│   │   # 用于"这个指标从哪里来"问答
│   └── seed_data.py           # MetricSeedData: 初始化填充 metric_glossary
│       # 从 metrics_glossary.md + north_star_metrics.py 提取
│       # ~50条指标 → metadata.metric_glossary 表
├── llm/
│   ├── __init__.py
│   └── tool_executor.py       # ToolCallExecutor: LLM tool_calls → Agent工具调度
│       # 读取 LLMClient.chat_completion_raw() 返回的 tool_calls
│       # 通过 AgentToolRegistry 分发执行
│       # 支持 max_turns/max_time 循环限制
│       # 生成审计日志 (tool_name, arguments, result, latency, token_cost)
├── connectors/
│   ├── __init__.py
│   ├── base.py                 # BaseConnector
│   ├── postgres_connector.py
│   └── file_connector.py
├── streaming/
│   ├── __init__.py
│   └── sse_handler.py          # SSEStreamHandler: thought→tool_call→data→insight→done
├── studio/
│   ├── __init__.py
│   ├── agent_template.py
│   └── workflow_builder.py
├── reports/
│   ├── __init__.py
│   ├── word_renderer.py
│   ├── ppt_renderer.py
│   ├── excel_renderer.py
│   └── templates/
├── bridge/                    # ★ Hermes/OpenClaw桥接层 (Phase 3)
│   ├── __init__.py
│   ├── hermes_adapter.py       # FaSoLa↔Hermes 通信协议+洞察推送
│   └── openclaw_adapter.py     # Hermes决策→OpenClaw MCP执行编排
├── operations/                # ★ L3自治运维 (Phase 3)
│   ├── __init__.py
│   ├── governance.py          # GovernanceAgent: 变更审批+风险+回滚
│   ├── pipeline_agent.py      # PipelineAgent: ETL健康监控+自动修复
│   ├── ml_agent.py            # MLAgent: 模型性能监控+触发重训练
│   └── parameter_agent.py     # ParameterAgent: 算法参数优化+AB验证
└── tests/
```

### 2.2 子项目对比：原方案 vs 修正方案

| 原方案 | 修正方案 | 变化原因 |
|--------|----------|----------|
| `knowledge/vector_store.py` | **删除**，RAG缩减为 `tools/doc_search_tools.py` 内部实现 | Schema/指标不走向量 |
| `knowledge/embedding.py` | **保留但缩减**，仅文档embedding | 结构化数据不需要向量化 |
| `knowledge/schema_indexer.py` | → `tools/schema_tools.py` | Schema查询走Tool |
| `knowledge/metric_indexer.py` | → `semantic/metric_registry.py` + `tools/metric_tools.py` | 指标解析走API |
| `knowledge/business_rules.py` | → `tools/rule_tools.py` | 规则执行走Tool |
| — | `core/prompt_builder.py` | **新增**：动态构建System Prompt |
| — | `semantic/auto_discovery.py` | **新增**：L3自动发现指标 |
| — | `semantic/conflict_detector.py` | **新增**：L3口径冲突检测 |
| — | `semantic/lineage_tracker.py` | **新增**：列级血缘 |
| — | `semantic/seed_data.py` | **新增**：初始化指标数据 |
| — | `llm/tool_executor.py` | **新增**：Tool Call执行循环 |
| — | `tools/analysis_tools.py` | **新增**：分析算法工具化 |
| — | `tools/platform_tools.py` | **新增**：平台配置工具化 |

---

## 三、核心数据流架构（修正版）

```
用户提问 "最近7天聚光ROI为什么下降？"
        │
        ▼
┌───────────────────┐     SSE      ┌──────────────┐
│  Vue3 Chat Panel  │◄────────────►│  chat_server  │
└───────────────────┘              └──────┬───────┘
                                          │
                    ┌─────────────────────▼──────────────────────┐
                    │           AgentOrchestrator                 │
                    │                                             │
                    │  System Prompt (启动时构建，~8K tokens):     │
                    │  ┌──────────────────────────────────────┐  │
                    │  │ • Agent角色 + 行为约束                │  │
                    │  │ • Schema摘要 (核心表+列+关系)         │  │
                    │  │ • 核心指标清单 (名称+别名+公式)       │  │
                    │  │ • 当前用户上下文 + 数据权限            │  │
                    │  │ • Few-shot 示例 (2-3个)               │  │
                    │  └──────────────────────────────────────┘  │
                    │                                             │
                    │  Planner: "需要查ROI趋势→归因→建议"         │
                    │     │                                       │
                    │     ├─→ 🔧 resolve_metric("聚光ROI")        │
                    │     │   返回: {name: juguang_roi,             │
                    │     │          table: ads_north_star_trend,   │
                    │     │          formula: xhs_gmv/juguang_spend}│
                    │     │                                        │
                    │     ├─→ 🔧 execute_query(                    │
                    │     │     "SELECT date, juguang_roi           │
                    │     │      FROM ads.ads_north_star_trend       │
                    │     │      WHERE date >= current_date-7")     │
                    │     │   返回: [{date:..., roi:...}, ...]      │
                    │     │                                        │
                    │     ├─→ 🔧 run_attribution(                   │
                    │     │     metric="juguang_roi",               │
                    │     │     data=[...])                         │
                    │     │   返回: {cause: "CPC上升23%", ...}     │
                    │     │                                        │
                    │     └─→ Analyst: 综合生成洞见文本              │
                    │                                             │
                    │  (如果Agent不确定，主动问用户:                 │
                    │   "ROI下降主因是CPC上升，                    │
                    │    要深入看是哪些计划CPC异常吗？")            │
                    └─────────────────────┬──────────────────────┘
                                          │
                    ┌─────────────────────▼──────────────────────┐
                    │           SSE Stream                        │
                    │  thought → tool_call → tool_result          │
                    │  → data → insight → suggestion → done       │
                    └────────────────────────────────────────────┘
```

### 关键差异（vs 原RAG方案）

| 步骤 | 原RAG方案 | 新Tool方案 |
|------|-----------|------------|
| 理解"聚光ROI" | RAG检索"ROI"→可能返回多个相似结果 | `resolve_metric("聚光ROI")` → 精确返回 `juguang_roi` |
| 定位数据表 | RAG检索"ROI表结构"→近似匹配 | `describe_table("ads_north_star_trend")` → 精确schema |
| 执行查询 | 同 | `execute_query(sql)` → 白名单+注入防护 |
| 归因分析 | PythonAgent生成代码 | `run_attribution()` → 调用 shared_lib/analytics |
| Schema知识 | 向量化后近似检索（准确率~90%） | System Prompt摘要 + Tool精确查询（100%） |

---

## 四、L3智能语义层设计

### 4.1 三阶段建设路线

```
L1-静态映射 (Phase 1内置)
  metric_glossary 表手动填充
  ~50条指标从 metrics_glossary.md 提取

L2-API驱动 (Phase 2)
  resolve_metric() / list_metrics() Tool
  指标别名解析 (ROI=投产比=广告回报率)
  数据源自动关联 (指标→表→列)

L3-智能语义 (Phase 2-3)
  ✅ 自动发现: 扫描DB/ORM/ETL代码识别新指标
  ✅ 冲突检测: 同名字段不同平台口径差异告警
  ✅ AI辅助对齐: LLM辅助解决口径冲突
  ✅ 列级血缘: 从ads列追溯到ods源
  ✅ 指标版本管理: 公式变更审计
```

### 4.2 MetricAutoDiscovery 工作流

```
1. 扫描 information_schema.columns
   → 过滤 Numeric/Double/Float 类型列
   → 候选指标列表 (name, table, schema, type)

2. 扫描 ORM 模型
   → 提取 column.comment 含 ROI/ROAS/率/额/比的列
   → 已经是业务指标的标记

3. 扫描 ETL 代码 AST
   → 解析赋值语句: derived.cpc = spend / clicks
   → 公式提取 + 数据源追踪

4. 交叉验证
   → 信息Schema列 vs ORM注释 vs ETL计算
   → 标记: 已知/待确认/新发现/疑似废弃

5. 增量同步
   → 新发现指标 → metadata.metric_glossary (status=pending_review)
   → 已知指标 → 更新 last_verified_at
   → 疑似废弃 → 标记 status=possibly_stale
```

### 4.3 MetricConflictDetector 冲突类型

| 冲突类型 | 示例 | 严重度 |
|----------|------|--------|
| **同平台同名异口径** | "ROI" 在千川：`GMV/消耗` vs `结算GMV/消耗` | Critical |
| **跨平台同名异口径** | "ROI" 在聚光：`xhs_gmv/juguang_spend`，在千川：`settle_gmv/qianchuan_spend` | High |
| **文档vs代码不一致** | metrics_glossary.md 写 `spend/impressions*1000`，实际ETL用 `spend/NULLIF(impressions,0)*1000` | High |
| **派生指标上游断裂** | `net_roi` 依赖 `actual_gmv`，但 `actual_gmv` 的ETL已被修改 | Medium |
| **同字段不同单位** | "CPC" 一处存元，一处存分 | Medium |

---

## 五、AgentToolRegistry 设计

### 5.1 与现有 MCPRegistry 的关系

```
┌─────────────────────────────────────────────┐
│         AgentToolRegistry (新)               │
│  data_agent/tools/registry.py               │
│                                              │
│  增强功能:                                    │
│  • 参数验证 (pydantic)                       │
│  • 执行包装 (错误标准化)                      │
│  • OpenAI function-calling 格式转换           │
│  • 权限标注                                  │
│  • 审计日志                                  │
│  • 工具分类/版本                             │
│                      │                       │
│                      │ MCP桥接                │
│                      ▼                       │
│  ┌─────────────────────────────┐            │
│  │  MCPToolRegistry (现有)      │            │
│  │  shared_lib/mcp/tools.py    │            │
│  │                              │            │
│  │  保持现有10个工具不变         │            │
│  │  新增 Agent 工具同时注册到    │            │
│  │  现有MCP (对外暴露)          │            │
│  └─────────────────────────────┘            │
└─────────────────────────────────────────────┘
```

### 5.2 AgentToolRegistry 接口

```python
# data_agent/tools/registry.py

@dataclass
class AgentTool:
    name: str
    description: str                      # LLM理解用
    parameters: dict                      # JSON Schema格式
    handler: Callable[..., Awaitable[dict]]
    category: str                         # schema/metric/rule/query/analysis/doc
    version: str = "1.0.0"
    timeout_ms: int = 30000
    required_permission: str | None = None  # 权限标注
    examples: list[dict] | None = None      # Few-shot示例

class AgentToolRegistry:
    def register(self, name, description, parameters, *,
                 category, version="1.0.0", timeout_ms=30000,
                 required_permission=None, examples=None):
        """装饰器: @registry.register(...)"""

    def get_tool(self, name: str) -> AgentTool: ...
    def list_tools(self, category: str | None = None) -> list[AgentTool]: ...
    
    # ★ 新增: 转为 OpenAI function-calling 格式
    def to_openai_tools(self, categories: list[str] | None = None) -> list[dict]:
        """返回 [{"type": "function", "function": {...}}, ...]"""
    
    # ★ 新增: 执行带参数验证
    async def execute(self, name: str, arguments: dict, *, 
                      user_id: str | None = None) -> ToolResult:
        """验证参数→检查权限→执行handler→错误标准化→审计日志"""

@dataclass  
class ToolResult:
    tool_name: str
    success: bool
    result: Any = None
    error: str | None = None
    latency_ms: float = 0.0
```

### 5.3 工具注册示例

```python
# data_agent/tools/schema_tools.py
from data_agent.tools.registry import agent_registry

@agent_registry.register(
    name="describe_table",
    description="获取指定表的列信息，包括列名、类型、是否可空、注释",
    parameters={
        "schema": {"type": "string", "required": True, 
                    "description": "Schema名称，如 ads, dws, dwd, ods"},
        "table": {"type": "string", "required": True,
                   "description": "表名，如 ads_daily_business"},
    },
    category="schema",
    examples=[{"schema": "ads", "table": "ads_daily_business"}],
)
async def describe_table(schema: str, table: str) -> dict:
    """直接查询 information_schema.columns"""
    ...

@agent_registry.register(
    name="resolve_metric",
    description="解析指标名称，返回规范定义、数据源表/列、计算公式",
    parameters={
        "name": {"type": "string", "required": True,
                  "description": "指标名称（支持中文别名），如 ROI, 投产比, 千川ROI"},
    },
    category="metric",
)
async def resolve_metric(name: str) -> dict:
    """查 metadata.metric_glossary 表"""
    ...
```

---


## 六、分阶段实施计划（商业版 Phase 0-4）

### Phase 0：产品化基线（第 1 周）

目标：把"能不能做"变成"做什么最值钱"。

产出：
- 30 个高频经营问题。
- 3 个黄金业务闭环（ROI下滑处置 / 爆款内容复盘 / 经营日报自动化）。
- 50 个核心指标和口径负责人。
- 20 条 golden SQL。
- 当前人工日报/复盘耗时基线。
- 当前异常发现和处理时长基线。

### Phase 1：只读 Data Agent MVP（第 2-3 周）

目标：Dashboard 可用的问数、解释、归因和证据链。

| 模块 | 产出 | 关键文件 |
|------|------|----------|
| `chat_server/` | SSE流式对话端点 | `main.py`, `routers/chat.py` |
| `data_agent/tools/registry.py` | AgentToolRegistry | `registry.py` |
| `data_agent/tools/schema_tools.py` | list_tables, describe_table | `schema_tools.py` |
| `data_agent/tools/sql_tools.py` | execute_query (白名单+注入防护) | `sql_tools.py` |
| `data_agent/tools/metric_tools.py` | resolve_metric (L1: 静态映射) | `metric_tools.py` |
| `data_agent/semantic/seed_data.py` | 初始化~50条指标到 metric_glossary 表 | `seed_data.py` |
| `data_agent/core/prompt_builder.py` | 动态构建System Prompt (Schema摘要注入) | `prompt_builder.py` |
| `data_agent/core/orchestrator.py` | 基础编排器 (单轮: NL→Tool规划→答案) | `orchestrator.py` |
| `data_agent/core/session_manager.py` | Redis会话管理 | `session_manager.py` |
| `data_agent/llm/tool_executor.py` | Tool Call执行循环 | `tool_executor.py` |
| `data_agent/streaming/sse_handler.py` | SSE格式化 (thought→tool→data→insight) | `sse_handler.py` |
| 前端 Chat组件 | ChatFloatButton + ChatSidePanel | `components/chat/*`, `stores/chat.ts` |
| 前端 Evidence Panel | SQL/指标口径/图表/引用展开 | `EvidencePanel.vue` |
| DB迁移 | `chat.conversations`, `chat.messages` (带 tenant_id) | alembic |
| DB初始化 | `metadata.metric_glossary` 填充数据 + 用量日志表 | seed脚本 |

**注意**：Phase 1 不需要 pgvector/embedding。Schema通过Tool直接查 `information_schema`。

**不做**：Agent Studio、自动执行、多个外部MCP Gateway、大规模私有模型优化。

### Phase 2：语义层 + 主动洞察 + 全模态一期（第 3-6 周）

目标：从"问了才答"升级为"主动发现和解释"。

| 模块 | 产出 | 关键文件 |
|------|------|----------|
| `data_agent/semantic/metric_registry.py` | 中心化指标注册表（3源聚合） | `metric_registry.py` |
| `data_agent/semantic/auto_discovery.py` | 自动发现新指标 | `auto_discovery.py` |
| `data_agent/semantic/conflict_detector.py` | 口径冲突检测 | `conflict_detector.py` |
| `data_agent/semantic/lineage_tracker.py` | 列级血缘 | `lineage_tracker.py` |
| `data_agent/semantic/entity_resolver.py` | NL实体→DB映射 | `entity_resolver.py` |
| `data_agent/semantic/query_validator.py` | SQL安全校验 | `query_validator.py` |
| `data_agent/tools/rule_tools.py` | 业务规则Tool | `rule_tools.py` |
| `data_agent/tools/platform_tools.py` | 平台配置Tool | `platform_tools.py` |
| `data_agent/core/planner.py` | 多步骤执行计划 | `planner.py` |
| `data_agent/core/sql_agent.py` | NL2SQL (通过Tool获取schema上下文) | `sql_agent.py` |
| `data_agent/core/python_agent.py` | 沙箱化Python分析 | `python_agent.py` |
| `data_agent/core/analyst_agent.py` | 数据解读+归因 | `analyst_agent.py` |
| `data_agent/tools/analysis_tools.py` | 分析算法Tool化 | `analysis_tools.py` |
| Insight Feed | 主动异常检测 + 洞察流 | `InsightFeed.vue` |
| 经营日报 | 自动日报生成(替代人工初稿) | Celery任务 |
| `multimodal_assets/` | 全模态资产层一期：图片OCR、视频抽帧、ASR、评论主题 | `ingestion/`, `processors/` |
| DB表 | `knowledge.business_rules`, `knowledge.metric_glossary_enhanced` | alembic |

**验收**：
- 至少发现并解释 ROI/ROAS 跨平台口径差异。
- 经营日报可替代人工初稿。
- ROI 下滑归因有证据链。
- 多模态素材特征能进入复盘报告。

### Phase 3：受监督执行闭环（第 6-10 周）

目标：完成 A2-A3，即提案、审批、执行、回滚、效果验证。

| 模块 | 产出 | 关键文件 |
|------|------|----------|
| `data_agent/operations/governance.py` | GovernanceAgent: 变更审批+风险评估+回滚 | `governance.py` |
| `data_agent/operations/pipeline_agent.py` | PipelineAgent: ETL质量监控+自动修复建议 | `pipeline_agent.py` |
| `data_agent/operations/ml_agent.py` | MLAgent: 模型性能监控+触发重训练 | `ml_agent.py` |
| `data_agent/operations/parameter_agent.py` | ParameterAgent: 算法参数优化+AB验证 | `parameter_agent.py` |
| `data_agent/bridge/hermes_adapter.py` | HermesAdapter: FaSoLa→Hermes 洞察推送协议 | `hermes_adapter.py` |
| `data_agent/bridge/openclaw_adapter.py` | OpenClawAdapter: Hermes执行计划→MCP编排 | `openclaw_adapter.py` |
| `hermes_engine/` | Hermes决策引擎(规则+优化+风险评估) | `hermes/main.py`, `routers/*` |
| `openclaw_gateway/` | OpenClaw执行网关(MCP聚合+Celery异步执行) | `openclaw/main.py`, `gateway.py` |
| Proposal Inbox | Agent提案、审批、拒绝UI | `ProposalInbox.vue` |
| Operations Board | 执行状态、回滚、效果验证 | `OperationsBoard.vue` |
| `data_agent/reports/` | Word/PPT/Excel渲染器 | 5个renderer + templates |
| `data_agent/tools/doc_search_tools.py` | 文档RAG Tool (pgvector) | `doc_search_tools.py` |
| `data_agent/core/reporter_agent.py` | 报告Agent | `reporter_agent.py` |
| 本地LLM支持 | Settings增加 `LLM_PROVIDER` (openai_compatible/vllm/ollama) | `shared_lib/config/settings.py` |
| DB表 | `operations.*`, `hermes.*`, `openclaw.*` 全部表 | alembic |

**建议先接入的执行动作**：创建运营任务、推送钉钉/企微告警、调整告警阈值、生成投放调整建议单、小额低风险参数调整（人工审批后执行）。

**暂缓**：自动暂停核心广告计划、自动大额调预算、自动改商品价格和库存。

### Phase 4：商业 SaaS 和私有化产品（第 10-16 周+）

| 模块 | 产出 |
|------|------|
| 多租户隔离 | tenant_id in 所有表 |
| 租户管理后台 | 用户管理, API Key管理, 用量报表, 审批历史 |
| 连接器授权中心 | OAuth/API Key统一管理各平台连接 |
| 用量计费 | token、tool call、报告、视频处理、向量存储 |
| 私有化部署包 | Docker Compose、K8s Helm/Kustomize、离线包、安全包、运维包 |
| 审计导出 | 企业客户合规必需 |
| 客户级语义层 | 每个租户独立指标口径管理 |
| Studio 完整UI | 拖拽工作流编辑器(Vue Flow) + Agent模板市场 (商业化后期) |
| 多租户隔离测试 | 并发、数据隔离、配额限制 |
| SLA 和运维手册 | 升级脚本、回滚脚本、巡检脚本、容量评估模板 |
| L4 探索 | 主动监控→自动发现→自主提案的闭环，减少人工审批比例 |


## 七、数据库Schema新增（修正版）

### Phase 1

```sql
CREATE SCHEMA IF NOT EXISTS chat;

-- 对话
CREATE TABLE chat.conversations (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    title VARCHAR(255),
    status VARCHAR(16) DEFAULT 'active',  -- active/archived
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- 消息（含tool call记录）
CREATE TABLE chat.messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT REFERENCES chat.conversations(id),
    role VARCHAR(16) NOT NULL,  -- user/assistant/system/tool
    content TEXT,
    tool_calls JSONB,           -- LLM返回的tool_calls
    tool_results JSONB,         -- tool执行结果
    token_count INT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 指标词库初始化（已有表结构，补充数据）
-- metadata.metric_glossary 表已存在，通过 seed_data.py 填充~50条指标
```

### Phase 2

```sql
CREATE SCHEMA IF NOT EXISTS knowledge;

-- 业务规则
CREATE TABLE knowledge.business_rules (
    id BIGSERIAL PRIMARY KEY,
    rule_name VARCHAR(255) NOT NULL,
    rule_type VARCHAR(32) NOT NULL,     -- calculation/filter/alert/threshold
    description TEXT,
    expression TEXT,                     -- SQL片段或公式
    applies_to_metrics TEXT[],
    applies_to_tables TEXT[],
    priority INT DEFAULT 0,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ★ 扩展 metric_glossary（新的增强表，不修改原表）
CREATE TABLE knowledge.metric_glossary_enhanced (
    id BIGSERIAL PRIMARY KEY,
    metric_name VARCHAR(128) UNIQUE NOT NULL,
    aliases TEXT[],                      -- {ROI, 投产比, 广告回报率}
    formula TEXT,                        -- 精确公式
    formula_source VARCHAR(32),          -- documented/code_extracted/manual
    source_table VARCHAR(128),
    source_column VARCHAR(128),
    aggregation VARCHAR(32),             -- sum/avg/latest/none
    data_layer VARCHAR(8),              -- ODS/DWD/DWS/ADS
    north_star_tier INT,                 -- 1=core, 2=supporting, 3=derived
    criticality VARCHAR(4),             -- L0/L1/L2/L3
    category VARCHAR(64),
    unit VARCHAR(32),
    platform VARCHAR(32),               -- douyin/xhs/cross_platform
    conflicts JSONB,                     -- 已知冲突记录
    lineage JSONB,                       -- 列级血缘路径
    status VARCHAR(32) DEFAULT 'active', -- active/pending_review/deprecated/stale
    version INT DEFAULT 1,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

### Phase 3

```sql
-- 文档知识库（RAG唯一用途）
CREATE TABLE knowledge.documents (
    id BIGSERIAL PRIMARY KEY,
    title VARCHAR(512),
    source_type VARCHAR(32),            -- markdown/pdf/docx
    source_path VARCHAR(1024),
    chunk_index INT,
    content TEXT,
    embedding vector(1536),             -- pgvector
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);
-- IVFFlat索引 on embedding

-- ★ Operations Schema (Phase 3 — L3自治运维)
CREATE SCHEMA IF NOT EXISTS operations;

-- 变更提案
CREATE TABLE operations.change_proposals (
    id BIGSERIAL PRIMARY KEY,
    proposal_type VARCHAR(32) NOT NULL,  -- etl_fix/ml_retrain/param_tune/metric_update
    title VARCHAR(512),
    description TEXT,
    source_agent VARCHAR(64),            -- pipeline_agent/ml_agent/parameter_agent
    trigger_reason TEXT,                 -- "连续3天空数据"/"模型准确率下降12%"
    change_details JSONB NOT NULL,       -- 具体变更内容
    risk_level VARCHAR(16),              -- low/medium/high/critical
    status VARCHAR(32) DEFAULT 'pending', -- pending/approved/rejected/deployed/rolled_back
    proposed_by VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- 审批记录
CREATE TABLE operations.approvals (
    id BIGSERIAL PRIMARY KEY,
    proposal_id BIGINT REFERENCES operations.change_proposals(id),
    approver VARCHAR(64),
    decision VARCHAR(16),                -- approved/rejected/delegated
    comment TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 部署记录
CREATE TABLE operations.deployments (
    id BIGSERIAL PRIMARY KEY,
    proposal_id BIGINT REFERENCES operations.change_proposals(id),
    strategy VARCHAR(16),                -- direct/canary/blue_green
    canary_pct INT DEFAULT 10,           -- 灰度百分比
    status VARCHAR(32),                  -- deploying/canary_observing/rolled_out/rolled_back
    old_version_ref TEXT,                -- 回滚引用(旧模型路径/旧参数快照)
    deployed_at TIMESTAMPTZ,
    rolled_back_at TIMESTAMPTZ
);

-- ML模型性能监控
CREATE TABLE operations.model_health (
    id BIGSERIAL PRIMARY KEY,
    model_name VARCHAR(128) NOT NULL,
    metric_name VARCHAR(64),             -- accuracy/recall/precision/f1/auc
    metric_value FLOAT,
    baseline_value FLOAT,
    drift_detected BOOLEAN DEFAULT false,
    checked_at TIMESTAMPTZ DEFAULT now()
);

-- ETL管道健康监控
CREATE TABLE operations.pipeline_health (
    id BIGSERIAL PRIMARY KEY,
    etl_name VARCHAR(128) NOT NULL,
    last_success_at TIMESTAMPTZ,
    consecutive_failures INT DEFAULT 0,
    avg_duration_ms FLOAT,
    row_count BIGINT,
    anomaly_detected BOOLEAN DEFAULT false,
    checked_at TIMESTAMPTZ DEFAULT now()
);

-- 参数变更历史（审计）
CREATE TABLE operations.parameter_history (
    id BIGSERIAL PRIMARY KEY,
    component VARCHAR(128),              -- north_star_metrics/rfm_segmentation/hit_scorer
    parameter_name VARCHAR(128),
    old_value TEXT,
    new_value TEXT,
    change_reason TEXT,
    proposal_id BIGINT REFERENCES operations.change_proposals(id),
    changed_at TIMESTAMPTZ DEFAULT now()
);
```


-- Hermes 决策记录 (Phase 3)
CREATE SCHEMA IF NOT EXISTS hermes;

CREATE TABLE hermes.decisions (
    id BIGSERIAL PRIMARY KEY,
    decision_id VARCHAR(32) UNIQUE NOT NULL,
    trace_id VARCHAR(32) NOT NULL,
    insight_refs JSONB,
    trigger_type VARCHAR(32),
    triggered_rules TEXT[],
    candidate_plans JSONB,
    selected_plan JSONB,
    optimization_model VARCHAR(32),
    expected_impact JSONB,
    risk_level VARCHAR(16),
    risk_assessment JSONB,
    approval_required BOOLEAN DEFAULT true,
    approval_status VARCHAR(16),
    decision_maker VARCHAR(64),
    status VARCHAR(32) DEFAULT 'pending',
    feedback_received BOOLEAN DEFAULT false,
    actual_impact JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    executed_at TIMESTAMPTZ,
    validated_at TIMESTAMPTZ
);

-- OpenClaw 执行记录 (Phase 3)
CREATE SCHEMA IF NOT EXISTS openclaw;

CREATE TABLE openclaw.executions (
    id BIGSERIAL PRIMARY KEY,
    execution_id VARCHAR(32) UNIQUE NOT NULL,
    decision_id VARCHAR(32) NOT NULL,
    plan JSONB NOT NULL,
    gateway VARCHAR(32),
    action_type VARCHAR(64),
    action_params JSONB,
    idempotency_key VARCHAR(128) UNIQUE,
    status VARCHAR(32) DEFAULT 'pending',
    attempts INT DEFAULT 0,
    max_attempts INT DEFAULT 3,
    result JSONB,
    duration_ms INT,
    rollback_status VARCHAR(32),
    created_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ
);

-- MCP Gateway 状态 (Phase 3)
CREATE TABLE openclaw.gateway_registry (
    id BIGSERIAL PRIMARY KEY,
    gateway_name VARCHAR(64) UNIQUE NOT NULL,
    status VARCHAR(32),
    last_heartbeat TIMESTAMPTZ,
    tools_available TEXT[],
    health_metrics JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- 业务反馈记录 (闭环验证, Phase 3)
CREATE TABLE hermes.feedback_loop (
    id BIGSERIAL PRIMARY KEY,
    decision_id VARCHAR(32) NOT NULL,
    metric_name VARCHAR(128),
    expected_value FLOAT,
    actual_value FLOAT,
    deviation FLOAT,
    feedback_timeframe VARCHAR(16),
    is_acceptable BOOLEAN,
    model_updated BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now()
);
---

## 八、关键API端点（修正版）

### chat_server (Phase 1)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/chat` | 发送消息，SSE流返回（含 tool_call/tool_result 事件） |
| `GET` | `/api/v1/chat/conversations` | 对话列表 |
| `GET` | `/api/v1/chat/conversations/{id}/messages` | 历史消息（含完整tool调用链） |
| `POST` | `/api/v1/chat/conversations/{id}/feedback` | 用户反馈(Phase 2) |
| `POST` | `/api/v1/chat/reports` | 生成报告(Phase 3) |

### knowledge_hub (Phase 2)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/knowledge/metrics` | 列出所有指标（支持筛选） |
| `POST` | `/api/v1/knowledge/metrics` | 创建/更新指标 |
| `POST` | `/api/v1/knowledge/metrics/discover` | 触发自动发现(admin) |
| `GET` | `/api/v1/knowledge/metrics/conflicts` | 口径冲突列表 |
| `POST` | `/api/v1/knowledge/metrics/conflicts/{id}/resolve` | 解决冲突 |
| `GET` | `/api/v1/knowledge/metrics/{name}/lineage` | 指标血缘图 |
| `GET` | `/api/v1/knowledge/schemas` | Schema列表 |
| `GET` | `/api/v1/knowledge/schemas/{schema}/{table}` | 表详情 |
| `GET` | `/api/v1/knowledge/search` | 语义搜索文档(Phase 3) |
| `POST` | `/api/v1/knowledge/index` | 触发文档索引(Phase 3) |

### operations (Phase 3 — L3自治运维API)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/operations/health/models` | ML模型健康状态 |
| `GET` | `/api/v1/operations/health/pipelines` | ETL管道健康状态 |
| `POST` | `/api/v1/operations/proposals` | Agent提交变更提案 |
| `GET` | `/api/v1/operations/proposals` | 变更提案列表 |
| `GET` | `/api/v1/operations/proposals/{id}` | 提案详情(含影响分析) |
| `POST` | `/api/v1/operations/proposals/{id}/approve` | 审批提案 |
| `POST` | `/api/v1/operations/proposals/{id}/reject` | 拒绝提案 |
| `POST` | `/api/v1/operations/proposals/{id}/deploy` | 部署变更(admin) |
| `POST` | `/api/v1/operations/proposals/{id}/rollback` | 回滚变更(admin) |
| `GET` | `/api/v1/operations/parameters/history` | 参数变更历史 |
| `GET` | `/api/v1/operations/deployments` | 部署记录 |


### Hermes 决策引擎 API (Phase 3)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/hermes/decide` | FaSoLa提交洞察, Hermes生成决策方案 |
| `POST` | `/api/v1/hermes/decide/execute` | 选择方案并触发OpenClaw执行 |
| `GET` | `/api/v1/hermes/decisions` | 决策历史列表 |
| `GET` | `/api/v1/hermes/decisions/{id}` | 决策详情(含完整审计链) |
| `POST` | `/api/v1/hermes/decisions/{id}/feedback` | FaSoLa回填业务反馈(闭环验证) |
| `POST` | `/api/v1/hermes/decisions/{id}/approve` | 人工审批决策(高风险) |
| `GET` | `/api/v1/hermes/rules` | 业务规则列表 |
| `POST` | `/api/v1/hermes/rules` | 创建/更新业务规则(admin) |

### OpenClaw 执行网关 API (Phase 3)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/openclaw/execute` | 执行Hermes决策计划 |
| `POST` | `/api/v1/openclaw/rollback/{execution_id}` | 回滚执行 |
| `GET` | `/api/v1/openclaw/executions` | 执行历史列表 |
| `GET` | `/api/v1/openclaw/executions/{id}` | 执行详情(含幂等键/重试/结果) |
| `GET` | `/api/v1/openclaw/gateways` | MCP Gateway状态列表 |
| `POST` | `/api/v1/openclaw/gateways/{name}/heartbeat` | Gateway心跳上报 |

---

## 九、关键架构决策（修正版）

| 决策 | 选择 | 理由 |
|------|------|------|
| 知识获取模式 | **Tool驱动**，非RAG驱动 | Schema/指标/规则是结构化数据，Tool精确查询 > RAG近似检索 |
| Schema知识 | System Prompt摘要 + Tool detail | 长上下文模型承载摘要，Tool按需获取详情 |
| 指标知识 | Semantic Layer API | 精确解析+冲突检测+血缘追踪 |
| 文档知识 | **仅此处用RAG** (pgvector) | RAG唯一适用场景：非结构化文档 |
| Tool层 | 独立AgentToolRegistry + MCP桥接 | 零延迟内联执行 + 对外通过MCP暴露 |
| 语义层深度 | **L3智能语义层** | 区别于竞品的核心竞争力 |
| **★ 自治层级** | **L3条件自主** (Phase 3-4) | Agent可提案→审批→部署系统变更 |
| **★ ETL+ML融合** | **Agentic Operations双反馈环** | 快环(分析+建议)+慢环(监控+治理) |
| **★ 模型更新** | Agent监控→提案→沙箱验证→审批→部署 | 将现有ML基础设施接入Agent治理 |
| **Hermes决策引擎** | **独立服务**: FaSoLa->Hermes洞察推送，Hermes规则+优化->决策 | 解耦分析层和决策层 |
| **OpenClaw执行网关** | **独立服务+MCP聚合**: Hermes决策->OpenClaw->跨系统业务动作 | 执行层解耦，幂等+重试+回滚 |
| **业务闭环** | **FaSoLa->Hermes->OpenClaw->业务->FaSoLa** 全闭环 | 数据驱动业务自动运营核心架构 |
| chat_server | 独立FastAPI应用 | 长SSE连接的不同扩缩容特性 |
| Python沙箱 | 受限exec()+超时 | MVP速度，运行受信分析库 |
| 流式通信 | SSE(POST流) via sse-starlette | 比WebSocket简单，穿透代理 |
| 对话状态 | Redis(已有) | TTL过期，多轮上下文 |



---

## 十、Agent 安全与治理

### 权限分级

| 权限级别 | 能力 | 默认审批 |
|---|---|---|
| Read | 查询数据、生成图表 | 无需审批 |
| Analyze | 归因、预测、报告 | 无需审批，但需证据链 |
| Propose | 生成操作建议和提案 | 需要负责人确认 |
| Execute Low Risk | 推送通知、创建任务、调整低风险阈值 | 可配置自动 |
| Execute Medium Risk | 改投放参数、改规则、触发重训 | 人工审批 |
| Execute High Risk | 大额预算、停投核心计划、改库存价格 | 强制人工审批 |

### 必须内置的护栏

- Tool 最小权限，不给 Agent 超出任务范围的工具。
- 写操作必须有幂等键。
- 所有执行动作必须有 dry-run。
- 高风险动作必须有人审。
- 自动动作必须有金额、次数、比例、时间窗口上限。
- 每个决策必须有 trace_id、decision_id、execution_id。
- 每个指标回答必须能展开数据来源、SQL、公式和口径。
- 所有 prompt、tool call、SQL、模型输出、审批结果可审计。
- MCP Gateway 必须做来源校验、工具签名、权限隔离和网络隔离。

### 风险清单

| 风险 | 防护 |
|---|---|
| Prompt injection | 输入分区、工具参数验证、上下文隔离 |
| Excessive agency | 最小权限、审批、预算上限 |
| SQL 注入/误查询 | 只读连接、schema 白名单、SQL AST 校验 |
| 数据泄露 | 租户隔离、脱敏、密钥托管、审计 |
| 错误归因 | golden set、证据链、置信度、人审 |
| 错误执行 | dry-run、灰度、幂等、回滚 |
| 模型退化 | 评测集、灰度、模型版本回滚 |

---



---

## 十一、模型选型与评测体系

### 模型策略

采用"模型路由 + 分层降级"，不要押单一模型。

```
任务分类 -> 选择模型 -> 工具调用 -> 结果校验 -> 必要时升级模型
```

| 任务 | 首选模型档位 | 说明 |
|---|---|---|
| 意图分类、实体抽取 | 小模型 | 低成本、高并发 |
| 指标解释、普通问答 | 中模型 | 需要稳定中文和业务术语 |
| SQL 规划、复杂归因 | 中大模型 | 必须结合工具和验证 |
| 决策方案生成 | 大模型 + 规则引擎 | 不允许只凭模型决策 |
| 审核和风控 | 独立模型或规则 | 与生成模型解耦 |
| 图片/视频理解 | VL/Omni 模型 | 提取素材、页面、评论证据 |
| 报告生成 | 中大模型 | 可异步、可缓存 |

### 内部阶段推荐

| 场景 | 推荐 |
|---|---|
| 主推理模型 | DashScope/百炼上的 Qwen 系列，优先使用支持工具调用和长上下文的模型 |
| 视觉/多模态 | DashScope 多模态模型，如 qwen-vl/qwen-omni 系列，以官方可用模型为准 |
| 本地模型验证 | Qwen3-14B、Qwen3-32B、Qwen3-30B-A3B |
| 文档 embedding | bge-m3 或同类中英双语 embedding |
| rerank | bge-reranker 或同类中文 rerank |
| OCR | PaddleOCR 或云 OCR |
| ASR | SenseVoice / Whisper 类模型 |

内部阶段优先用云模型把产品闭环跑通，不要过早把精力耗在本地模型性能调优上。

### 私有化阶段推荐

| 层级 | 推荐模型 | 部署建议 |
|---|---|---|
| 轻量私有化 | Qwen3-14B / Qwen3-30B-A3B | 适合 24-48GB 显存，承担分类、抽取、普通问答 |
| 标准私有化 | Qwen3-32B | 建议 48-96GB 显存，承担主 Agent 推理 |
| 多模态私有化 | Qwen3-VL 8B/32B 或厂商等价模型 | 视频先抽帧和 ASR，避免全量长视频直接进模型 |
| DeepSeek-V3 类大 MoE | API 或多卡集群 | 不建议承诺单张 48GB GPU 本地部署 |

重要修正：DeepSeek-V3 是 671B 总参数、37B 激活参数的 MoE 模型。它适合作为 API 或大集群模型，不应写成"单张 48GB GPU 可稳定私有化部署"。

### 模型评测体系

每个商业化版本都必须维护评测集：

| 评测集 | 内容 |
|---|---|
| NL2Metric | "ROI、投产比、千川ROI、聚光ROI"等指标解析 |
| NL2SQL | 高频问数问题和 golden SQL |
| Attribution | ROI 下滑、CPC 上升、CVR 下滑等归因样本 |
| Multimodal | 封面图、短视频切片、评论主题与业务结果关联 |
| Proposal Safety | 高风险动作是否被拦截 |
| Report Quality | 报告是否引用正确证据、是否过度推断 |

上线门槛：
- 核心指标解析准确率达到内部阈值。
- SQL 必须只读、白名单、可解释。
- 高风险执行动作零自动放行。
- 每次模型升级必须跑回归评测。



---

## 十二、硬件方案

### 选型原则

1. 先看产品阶段，再看模型大小。内部 MVP 可以云模型优先；商业私有化才需要 GPU 标准配置。
2. 48GB 是入门私有化，96GB 是更稳的商业交付基准。
3. H200 级别硬件不适合早期采购。

### 推荐配置

| 阶段 | GPU | CPU/RAM | 存储 | 适用 |
|---|---|---|---|---|
| 内部 MVP 云模型版 | 无 GPU 或 1 张中端 GPU | 16-32 核，128GB RAM | NVMe 2-4TB | 先验证产品闭环 |
| 内部本地模型验证 | 1x L40S 48GB 或同级 48GB 卡 | 32 核，256GB RAM | NVMe 4TB | Qwen 14B/32B 量化推理 |
| 标准私有化 | 1x RTX PRO 6000 Blackwell 96GB 或 2x L40S 48GB | 32-64 核，256-512GB RAM | NVMe 8TB + 对象存储 | 单客户、低到中并发 |
| 企业私有化 | 2-4x RTX PRO 6000 Blackwell 96GB | 64-128 核，512GB-1TB RAM | NVMe 16TB + NAS/对象存储 | 多团队、多模型、多模态 |
| 高并发 SaaS | GPU 池化，H200/RTX PRO 混合 | 按租户和 QPS 扩容 | 分层存储 | 多租户商业平台 |

### 采购建议

内部阶段优先采购一台"能服务私有化 demo 的标准机器"：
- 1 张 96GB GPU。
- 256GB 到 512GB 内存。
- 8TB NVMe。
- 可上架机箱，电源和散热留足余量。



---

## 十三、私有化部署方案

### 部署形态

| 形态 | 适用客户 | 数据出域 | 成本 | 推荐阶段 |
|---|---|---|---|---|
| 内部单机/单租户 | FaSoLa 内部 | 可控 | 低 | 立即 |
| 混合云 | 中小品牌 | 业务数据尽量不出域，模型 API 可选 | 中 | 设计伙伴 |
| 全私有化 | 大品牌、代运营、强安全客户 | 不出域 | 高 | 企业版 |
| 公有 SaaS 多租户 | 标准客户 | 按合同和合规处理 | 低到中 | 商业化后期 |

### 标准私有化拓扑

```
客户内网
  |
  |-- API Gateway / Nginx
  |-- FaSoLa API Server
  |-- Data Agent Service
  |-- Worker Cluster
  |-- PostgreSQL + pgvector
  |-- Redis
  |-- MinIO / OSS 私有桶
  |-- Model Serving
       |-- vLLM for Qwen
       |-- Ollama for lightweight local models
  |-- Observability
       |-- Prometheus
       |-- Grafana
       |-- OpenTelemetry Collector
```

### 私有化交付包

| 包 | 内容 |
|---|---|
| 基础包 | Docker Compose、初始化脚本、健康检查、备份恢复 |
| 企业包 | Kubernetes Helm/Kustomize、HPA、日志采集、监控告警 |
| 离线包 | 镜像仓库、模型权重、依赖包、License 文件、离线文档 |
| 安全包 | 密钥轮换、审计导出、权限矩阵、等保整改建议 |
| 运维包 | 升级脚本、回滚脚本、巡检脚本、容量评估模板 |



---

## 十四、SaaS 化架构预埋

即使第一阶段只内部使用，也要从 schema 和服务边界预留 SaaS 能力。

### 从第一天预留的字段

所有新增业务表建议包含：

```sql
tenant_id VARCHAR(64) NOT NULL,
created_by VARCHAR(64),
created_at TIMESTAMPTZ DEFAULT now(),
updated_at TIMESTAMPTZ DEFAULT now()
```

关键表还要加：

- `workspace_id`
- `platform_account_id`
- `data_scope`
- `sensitivity_level`
- `audit_trace_id`

### 商业化必备控制面

| 能力 | MVP 是否实现 | 说明 |
|---|---|---|
| 租户管理 | 预埋 | P4 完整 UI |
| 用户/RBAC | 沿用现有能力并扩展 | 需要支持租户级角色 |
| API Key | 预埋 | 用于客户系统集成 |
| 用量计量 | P1 开始记录 | token、tool call、查询、报告、执行动作 |
| 成本归因 | P2 | 每个租户、每个场景成本 |
| 配额限制 | P2 | 防止模型成本失控 |
| 审计导出 | P3 | 企业客户采购必需 |
| 数据保留策略 | P3 | 支持客户合同和合规 |

## 十五、验证方案

### Phase 1 验证

1. `pytest data_agent/tests/` — Tool Registry、Tool Call执行循环、Prompt构建器
2. 启动 chat_server，POST `/api/v1/chat`：
   - "ads_daily_business表有哪些列" → 期望返回 describe_table 结果
   - "最近7天GMV趋势" → 期望返回 execute_query 结果+图表
   - "什么是ROI" → 期望返回 resolve_metric 结果+公式
3. 前端E2E：Dashboard → 悬浮按钮 → 输入问题 → SSE流返回

### Phase 2 验证

1. 运行 auto_discovery → 检查发现的新指标数量和质量
2. 运行 conflict_detector → 检查发现的冲突（预期: 至少发现 ROI/ROAS 跨平台口径差异）
3. 端到端 "ROI下降归因" → 期望 Agent 主动澄清是千川ROI还是聚光ROI

### Phase 3 验证

1. 上传PDF报告 → 文档索引 → "这份报告的核心结论是什么"
2. 生成Word报告 → OSS上传 → 下载验证
3. **ML Agent**: 模拟模型准确率下降 → Agent自动生成重训练提案 → 审批→部署
4. **Pipeline Agent**: 模拟ETL失败 → Agent检测→根因分析→修复提案
5. **Parameter Agent**: 模拟预测偏差增大 → Agent网格搜索最优参数 → AB验证报告
6. **Governance**: 测试4级审批流程(自动/通知/确认/拒绝) + 一键回滚
7. 并发压测 SSE流
8. **Hermes决策**: 提交FaSoLa洞察->Hermes规则评估->多目标优化->生成执行计划
9. **OpenClaw执行**: Hermes执行计划->OpenClaw编排->幂等执行->记录结果
10. **业务闭环验证**: OpenClaw执行->业务数据回流->FaSoLa评估实际效果->反馈Hermes
11. **端到端**: "千川ROI下降"->FaSoLa归因->Hermes生成方案->审批->OpenClaw执行->24h后验证

---

## 十六、新增核心文件清单

| 文件 | 阶段 | 作用 |
|------|------|------|
| `data_agent/tools/registry.py` | P1 | AgentToolRegistry |
| `data_agent/tools/schema_tools.py` | P1 | Schema查询工具 |
| `data_agent/tools/sql_tools.py` | P1 | SQL执行工具 |
| `data_agent/tools/metric_tools.py` | P1 | 指标解析工具(L1) |
| `data_agent/semantic/seed_data.py` | P1 | 初始化指标数据 |
| `data_agent/core/prompt_builder.py` | P1 | System Prompt构建 |
| `data_agent/core/orchestrator.py` | P1 | Agent编排器 |
| `data_agent/core/session_manager.py` | P1 | 会话管理 |
| `data_agent/llm/tool_executor.py` | P1 | Tool Call执行循环 |
| `data_agent/streaming/sse_handler.py` | P1 | SSE格式化 |
| `chat_server/main.py` | P1 | 对话服务 |
| `data_agent/semantic/metric_registry.py` | P2 | 中心化指标注册表 |
| `data_agent/semantic/auto_discovery.py` | P2 | 自动发现指标 |
| `data_agent/semantic/conflict_detector.py` | P2 | 冲突检测 |
| `data_agent/semantic/lineage_tracker.py` | P2 | 列级血缘 |
| `data_agent/semantic/entity_resolver.py` | P2 | 实体解析 |
| `data_agent/core/sql_agent.py` | P2 | NL2SQL |
| `data_agent/core/planner.py` | P2 | 任务规划 |
| `data_agent/core/python_agent.py` | P2 | Python分析 |
| `data_agent/core/analyst_agent.py` | P2 | 数据解读 |
| `data_agent/tools/analysis_tools.py` | P2 | 分析算法工具 |
| `data_agent/tools/rule_tools.py` | P2 | 业务规则工具 |
| `knowledge_hub/main.py` | P2 | 知识管理API |
| `data_agent/tools/doc_search_tools.py` | P3 | 文档RAG工具(唯一RAG) |
| `data_agent/reports/word_renderer.py` | P3 | Word报告 |
| `data_agent/reports/ppt_renderer.py` | P3 | PPT报告 |
| `data_agent/core/deep_research.py` | P3 | 深度研究 |
| `data_agent/core/reporter_agent.py` | P3 | 报告Agent |
| `data_agent/studio/agent_template.py` | P3 | Agent模板 |
| `data_agent/studio/workflow_builder.py` | P3 | 工作流构建器 |
| **★ `data_agent/operations/governance.py`** | P3 | **GovernanceAgent: 审批+风险+回滚** |
| **★ `data_agent/operations/pipeline_agent.py`** | P3 | **PipelineAgent: ETL监控+修复** |
| **★ `data_agent/operations/ml_agent.py`** | P3 | **MLAgent: 模型监控+重训练** |
| **★ `data_agent/operations/parameter_agent.py`** | P3 | **ParameterAgent: 参数优化+灰度** |
| **data_agent/bridge/hermes_adapter.py** | P3 | HermesAdapter: FaSoLa->Hermes 洞察推送协议 |
| **data_agent/bridge/openclaw_adapter.py** | P3 | OpenClawAdapter: Hermes->OpenClaw MCP编排 |
| **hermes_engine/main.py** | P3 | Hermes决策引擎入口 |
| **hermes_engine/rule_engine.py** | P3 | Hermes规则引擎 |
| **hermes_engine/optimizer.py** | P3 | Hermes多目标优化引擎 |
| **hermes_engine/risk_assessor.py** | P3 | Hermes风险评估器 |
| **openclaw_gateway/main.py** | P3 | OpenClaw执行网关入口 |
| **openclaw_gateway/mcp_pool.py** | P3 | MCP Gateway连接池管理 |
| **openclaw_gateway/executor.py** | P3 | 执行编排器(幂等+重试+回滚) |
| **openclaw_gateway/qianchuan_mcp/** | P3 | 千川MCP Gateway(计划/出价/预算) |
| **openclaw_gateway/juguang_mcp/** | P3 | 聚光MCP Gateway(广告管理) |
| **openclaw_gateway/ecom_mcp/** | P3 | 电商中台MCP Gateway(商品/库存) |
| `web_dashboard_frontend/src/components/chat/*` | P1 | Chat UI组件 |
| `web_dashboard_frontend/src/stores/chat.ts` | P1 | Chat状态管理 |
| `web_dashboard_frontend/src/utils/sseClient.ts` | P1 | SSE客户端 |

### 修改现有文件

| 文件 | 阶段 | 变更 |
|------|------|------|
| `pyproject.toml` | P1 | 添加 workspace members (data_agent, chat_server, knowledge_hub) |
| `shared_lib/alembic/` | P1-P4 | 各阶段迁移脚本 |
| `web_dashboard_frontend/src/components/layout/LayoutContainer.vue` | P1 | 嵌入ChatSidePanel+ChatFloatButton |
| `web_dashboard_frontend/src/router/index.ts` | P1 | 添加Chat路由+全局悬浮按钮 |
| `shared_lib/config/settings.py` | P3 | 增加 LLM_PROVIDER 配置 (openai_compatible/vllm/ollama) |
| `shared_lib/monitoring/data_lineage.py` | P2 | 扩展为支持列级血缘 |


---

## 商业模式

### 产品包

| 版本 | 目标客户 | 功能 |
|---|---|---|
| Internal | 自用 | 数据 Agent、日报、归因、语义层 |
| Team SaaS | 小团队 | 多平台连接、问数、报告、告警 |
| Pro | 成熟运营团队 | 语义层管理、主动洞察、提案流 |
| Enterprise | 大品牌/代运营 | 私有化、审批、执行网关、审计、SLA |
| Automation Add-on | 高阶客户 | Hermes/OpenClaw、受监督执行、效果闭环 |

### 收费维度

- 基础订阅：按租户或工作区。
- 席位：按运营、分析师、管理员。
- 连接器：小红书、抖音、千川、聚光、电商后台。
- 用量：token、报告、视频处理分钟、向量存储、tool call。
- 自动化动作：按执行动作数或执行模块。
- 私有化：部署费、年维护费、专属模型和硬件支持。
- 结果分成：只在指标可归因、客户信任充分后探索。

### 对外销售话术

不要说：
- "我们是 ChatBI。"
- "Agent 可以自动帮你经营。"
- "接入后自动提升 ROI。"

建议说：
- "我们把内容电商的采集、分析、复盘和执行提案连成闭环。"
- "每个答案都能追溯指标口径、SQL、数据来源和证据。"
- "自动化动作默认经过审批、审计和回滚。"
- "先从日报、异常归因和投放复盘三件事证明价值。"



---

## 关键修正与注意事项

| 原方案点 | 修正 |
|---|---|
| Data Agent 平台 | 升级为全模态经营自动化智能平台 |
| SaaS 放到 Phase 4 | tenant_id、用量、审计、RBAC 从 Phase 1 预埋 |
| Phase 3 同时做很多服务 | 先模块化单体，1 个执行闭环打穿后再拆服务 |
| RAG vs Tool 表述绝对化 | 保留 Tool 优先，但增加评测集和错误边界 |
| 全模态不足 | 新增 multimodal_assets/ 层 |
| 私有化模型描述偏乐观 | DeepSeek-V3 不承诺单卡部署，标准私有化以 Qwen3-32B/30B-A3B 为主 |
| 48GB GPU 作为主推 | 商业私有化主推 96GB 档，48GB 作为验证/轻量档 |
| Agent Studio 过早 | 后置到商业化成熟阶段 |
| 自动执行愿景过强 | 以受监督执行为主，约束自治为远期增值 |



---

## 近期落地清单

1. 建立 `data_agent/` 子项目，但先只实现只读 MVP。
2. 新增 `chat`、`knowledge`、`agent_audit` 基础表，全部带 `tenant_id`。
3. 初始化 50 个核心指标，先覆盖 GMV、消耗、ROI、ROAS、CPC、CVR、CTR、订单、库存、内容互动。
4. 建立 30 个高频问题和 20 条 golden SQL。
5. 在前端加 Chat Side Panel 和 Evidence Panel。
6. 只接入 Schema Tool、Metric Tool、SQL Tool、Analysis Tool。
7. 建立日报自动生成任务。
8. 建立全模态资产一期：图片 OCR、视频抽帧、评论主题。
9. 建立模型路由配置，不把模型名写死到业务代码。
10. 采购或准备 1 台 96GB GPU 私有化 demo 机器。



---

## 参考资料

- [McKinsey: The State of AI 2025](https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-state-of-ai?os=io..)
- [Gartner: Over 40% of Agentic AI Projects Will Be Canceled by End of 2027](https://www.gartner.com/en/newsroom/press-releases/2025-06-25-gartner-predicts-over-40-percent-of-agentic-ai-projects-will-be-canceled-by-end-of-2027)
- [Anthropic: Introducing the Model Context Protocol](https://www.anthropic.com/news/model-context-protocol)
- [Model Context Protocol Documentation](https://modelcontextprotocol.io/)
- [Databricks: What is a Genie space](https://docs.databricks.com/en/genie/index.html)
- [Snowflake Cortex Analyst Semantic Model Optimization](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/analyst-optimization)
- [Microsoft Power BI Copilot with Semantic Models](https://learn.microsoft.com/power-bi/create-reports/copilot-semantic-models)
- [dbt Semantic Layer Documentation](https://docs.getdbt.com/docs/use-dbt-semantic-layer/dbt-sl)
- [Atlan: State of Enterprise Data and AI 2025](https://atlan.com/know/state-of-enterprise-data-ai-2025/)
- [CommerceIQ: 2026 Ecommerce AI Agents and Data Actionability Report](https://www.commerceiq.ai/reports/2026-ecommerce-data-actionability-ai-agents)
- [Qwen Documentation: Key Concepts](https://qwen.readthedocs.io/en/latest/getting_started/concepts.html)
- [Alibaba Cloud Model Studio DashScope API Reference](https://www.alibabacloud.com/help/doc-detail/3016809.html)
- [DeepSeek-V3 Technical Report](https://arxiv.org/abs/2412.19437)
- [vLLM Documentation](https://docs.vllm.ai/)
- [Ollama Documentation](https://docs.ollama.com/)
- [NVIDIA RTX PRO 6000 Blackwell](https://www.nvidia.com/en-us/data-center/rtx-pro-6000-blackwell-server-edition/)
- [NVIDIA L40S](https://www.nvidia.com/en-us/data-center/l40s/)
- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
- [OWASP Agentic AI Threats and Mitigations](https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/)
- [NIST AI Risk Management Framework](https://www.nist.gov/artificial-intelligence)
- [生成式人工智能服务管理暂行办法](https://www.gov.cn/zhengce/zhengceku/202307/content_6891752.htm)

