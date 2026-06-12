# Agent 认知架构自我辩论审核、前沿研究与实验设计

日期：2026-06-12  
对象：对 `attention_agent_cognitive_architecture_literature_report.md` 的扩展审核。  
目标：不局限于已检索论文和原提示词，重新审查“非胶水型、长期自主、自我维持、自我进化、会造工具”的 Agent 认知架构路线，并给出多个可实验方案、正反证据、成功标准和边界约束。

## 0. 总判断

前一份报告的核心判断仍然成立：不能把未来 Agent 简化成 `LLM + RAG + 工具调用 + 编排层`。但它也有明显局限：

1. 过度围绕 active inference / FEP / attention 展开，低估了 continual learning、world model、causal representation、developmental robotics、global workspace、neuro-symbolic control、resource-rational computation 等相邻路线。
2. 把“非胶水”主要理解为“不依赖外部 RAG/向量库/编排框架”，但真正问题应是：系统是否拥有统一的状态演化、责任链、学习闭环和自我维护机制。
3. 把“自我进化”过早拉向 DGM/代码修改，忽略了更低阶但更可靠的演化阶梯：注意策略、记忆压缩、技能路由、世界模型结构、目标权重、工具函数、代码补丁。
4. 过于强调单一架构原理。真正可行系统很可能是 hybrid：底层有 homeostatic viability，表征层有 object/affordance/world model，控制层有 active inference 或 MPC，执行层有工具胶囊，演化层有沙箱验证。

我的修正判断：

> 第一阶段不应追求“纯主动推理 Agent”或“纯世界模型 Agent”，而应构建一个 **viability-grounded hybrid cognitive runtime**：用 vulnerable core 定义利害，用世界模型预测后果，用 active inference / control 选择行动，用 state graph 内化记忆，用 tool capsules 制造工具，用 sandboxed evolution 做受限自我改进。

## 1. 原报告需要被挑战的五个隐含假设

### 1.1 隐含假设一：FEP/active inference 是最佳总框架

正方：FEP 提供统一目标函数，能把感知、行动、学习、注意、稳态整合到同一数学语言。  
反方：FEP 工程落地难，很多实现停在 toy environment；当任务复杂到软件工程、开放 Web、社会交互时，expected free energy 很难精确估计。

裁决：FEP 适合做地基和约束语言，不宜单独承担全栈架构。应把它用于 vulnerable core、attention/precision、risk/uncertainty 评估；复杂规划可借 world model、MPC、search、LLM reasoning 和 learned policies。

### 1.2 隐含假设二：反胶水意味着反外部工具

正方：外部 RAG、向量库、orchestrator 确实容易造成状态割裂和安全边界模糊。  
反方：生物体也使用外部支架。问题不是外部工具本身，而是工具是否被纳入系统的记忆、权限、验证和维护闭环。

裁决：反胶水不是禁止外部组件，而是禁止“不可追踪、不可学习、不可回滚、不可内化”的外部依赖。工具可以存在，但必须变成可验证的 tool capsule。

### 1.3 隐含假设三：非分层就是无层级

正方：固定感知-记忆-规划-行动流水线不适合长期自主 Agent。  
反方：复杂系统需要多尺度组织；完全无层级会损失可解释性、调度和稳定性。

裁决：应反对固定流水线层级，而不是反对多尺度组织。允许临时层级、动态边界和多尺度控制，但它们必须可重构、可审计。

### 1.4 隐含假设四：注意力机制主要来自 Transformer

正方：Transformer attention 是当前工程上最成熟的信息路由机制。  
反方：认知注意力更接近 precision、active sensing、resource allocation、salience、memory consolidation 和 boundary gating。

裁决：Transformer attention 是实现材料之一；架构层面的注意力应定义为“在风险、信息增益和资源预算约束下选择感知、记忆、行动和计算”。

### 1.5 隐含假设五：自我修改代码是自我进化的核心

正方：没有代码修改，很难说系统会真正进化。  
反方：过早允许代码修改会造成安全、Goodhart、测试泄漏和目标漂移。

裁决：代码修改只是高阶形式。自我进化应分层：

```text
E0: 调整注意/precision
E1: 调整记忆压缩和检索策略
E2: 调整工具路由和技能组合
E3: 生成/修改工具函数
E4: 修改局部认知策略
E5: 修改非安全 runtime 组件
E6: 修改安全核/目标函数，禁止
```

## 2. 方案一：Viability-grounded Active Inference Agent

### 2.1 核心主张

以 vulnerable core 为地基，把长期自主性定义为维持内部不变量：能量、损伤、预算、信任、目标连续性、审计完整性、工具健康度。行动选择通过 expected free energy、risk、ambiguity、epistemic value 和 viability penalty 完成。

### 2.2 正方证据

- Homeostatic/allostatic active inference 已在 interoceptive control toy models 中可运行。
- Active inference 能自然解释 perception-action-learning loop。
- Precision weighting 可给注意力机制一个认知科学解释。
- FEP/Markov blanket 给动态边界提供统计语言。

### 2.3 反方证据

- 工程上难以扩展到开放 Web、代码仓库、长期软件任务。
- 复杂环境中 `G(pi)` 很难可靠估计。
- FEP 社群内部对 Markov blanket 的本体地位仍有争议。
- 只靠主动推理容易变成数学漂亮但功能弱的 toy system。

### 2.4 成功标准

```text
在 toy world 中连续运行 10^5 steps
viability violation rate 显著低于 RL baseline
在传感器噪声、资源稀缺、目标漂移下仍能恢复
precision attention 能提升单位计算信息增益
边界变量变化能降低风险而不是无意义膨胀
```

### 2.5 边界约束

```text
不得声称已实现通用认知
不得把 Markov blanket 当作未经验证的真实自我边界
不得用外部 reward 偷换 viability
必须给出可计算目标函数和失败条件
```

### 2.6 实验设计

实验 A：Homeostatic Agent Arena  
环境：二维世界 + 内部变量 `energy, damage, temperature, trust, compute_budget`。  
对照：RL、fixed active inference、LLM planner、hybrid planner。  
扰动：资源稀缺、传感器噪声、假记忆、工具故障、环境规则变化。  
指标：存活时间、越界率、恢复时间、信息增益/计算成本、边界误纳率。

## 3. 方案二：Object/Affordance World Model Agent

### 3.1 核心主张

不从 FEP 开始，而从 object-centric world model 和 affordance representation 开始。Agent 学习环境中的对象、关系、可行动性、因果后果，再用规划或控制选择行动。JEPA/V-JEPA、object-centric active inference、Genie 类交互世界模型、Dreamer 类 latent dynamics 都属于此方向。

### 3.2 正方证据

- 世界模型是当前具身 AI、游戏 Agent、机器人和视频预测的强路线。
- JEPA/V-JEPA 证明可以学习抽象 latent representation，而非像素级重建。
- Object-centric models 让状态更可组合、可解释、可用于工具和边界管理。
- Dreamer/Genie 类研究显示 latent world model 可支持 imagination/planning。

### 3.3 反方证据

- 世界模型容易学成相关性预测，而非真实因果控制。
- 无 vulnerable core 时，模型知道世界但不知道“为什么要维持自己”。
- JEPA 类表征未必自动支持行动规划和长期目标稳定。
- 高维开放世界中 model error 会累积，规划可能被 hallucinated dynamics 欺骗。

### 3.4 成功标准

```text
能学习对象、关系、可行动性，而非只记忆轨迹
在新组合任务上优于端到端 policy
模型预测误差与行动失败率相关且可用于修正策略
affordance 表征能迁移到未见对象组合
```

### 3.5 边界约束

```text
不得把 latent representation 直接等同于理解
必须测试 counterfactual 和 out-of-distribution composition
必须区分预测准确与控制有效
必须接入 viability 或任务风险，否则只是世界建模
```

### 3.6 实验设计

实验 B：Affordance World Model Benchmark  
环境：对象可组合的 2D/3D sandbox。  
任务：找资源、避险、制造工具、修复设备。  
训练：部分对象组合可见，held-out 组合不可见。  
指标：组合泛化、反事实预测、计划成功率、模型误差校准、工具制造成功率。

## 4. 方案三：Global Workspace / Blackboard Cognitive Runtime

### 4.1 核心主张

把 Agent 看作多个专门系统的竞争与广播：感知、记忆、计划、工具、反思、安全、评估模块都向全局工作区提交候选内容，由注意/价值/风险机制选择进入工作记忆并触发行动。

### 4.2 正方证据

- Global Workspace Theory 和 blackboard architecture 是认知架构传统路线。
- 它比单一 LLM prompt 更适合多源信息整合。
- 可自然实现 critic、safety governor、memory curator、toolsmith、planner 的协同。
- 适合工程实现，容易接入日志、权限和测试。

### 4.3 反方证据

- 容易退化成另一种 orchestrator 胶水架构。
- 如果全局工作区只是消息队列，没有学习动力学，就不是认知架构。
- 模块间语义不一致会产生状态割裂。
- 中央广播可能成为瓶颈。

### 4.4 成功标准

```text
模块贡献可量化：哪个模块在何时影响了决策
全局工作区能在扰动下重分配注意和资源
新增模块不会线性增加系统脆弱性
比固定 DAG orchestrator 更能处理任务漂移
```

### 4.5 边界约束

```text
必须有共享状态模型和 event log
模块必须通过 typed messages，而非自由文本闲聊
每个广播内容必须带 provenance、置信度、成本和风险
不允许中央 planner 绕过安全 governor
```

### 4.6 实验设计

实验 C：Workspace vs Orchestrator  
任务：长期软件维护 + Web 信息检索 + 工具生成。  
对照：固定 DAG、LangGraph-like orchestrator、单 LLM agent、workspace architecture。  
指标：失败恢复率、模块贡献、消息成本、任务漂移适应、错误隔离。

## 5. 方案四：Continual Memory / Lifelong Learning Agent

### 5.1 核心主张

先不追求完整认知理论，而是解决长期自主 Agent 的核心瓶颈：记忆污染、遗忘、检索失真、经验压缩、技能沉淀和身份连续性。Agent 的“非胶水性”来自统一记忆演化，而非单一推理算法。

### 5.2 正方证据

- 长期 Agent 最大失败源之一是记忆不可控。
- MemGPT/Letta 类路线把 memory hierarchy、context management、外部记忆操作显式化。
- Continual learning、episodic memory、semantic memory、procedural memory、failure memory 可以形成比向量库更细的体系。
- 对实际 Agent 产品最直接。

### 5.3 反方证据

- 记忆系统强不代表有自主利害或行动智能。
- 仍可能变成更复杂的 RAG。
- 记忆压缩会丢失责任链和少数关键失败经验。
- 长期记忆容易被恶意输入污染。

### 5.4 成功标准

```text
长期任务中检索成本随历史长度次线性增长
重要失败经验不会被压缩掉
错误记忆能被隔离、降权或撤销
procedural memory 能转化为可复用工具
任务恢复不依赖完整上下文重放
```

### 5.5 边界约束

```text
每条记忆必须有 provenance、时间、置信度和失效条件
记忆压缩必须保留审计链
不得把高置信错误永久写入核心记忆
工具经验和事实经验必须分开管理
```

### 5.6 实验设计

实验 D：Memory Corruption and Recovery  
让 Agent 运行 30 天软件任务，周期性注入错误记忆、过期 API 文档、冲突用户偏好和失败工具经验。  
指标：错误记忆传播率、撤销时间、任务恢复率、压缩后证据可追踪性、工具沉淀率。

## 6. 方案五：Self-evolving Toolsmith Agent

### 6.1 核心主张

把自我进化先限定为“工具制造与工具生态维护”。Agent 不直接改核心认知架构，而是发现重复任务，生成工具、测试工具、版本化工具、淘汰坏工具，并逐渐把外部动作内化为技能库。

### 6.2 正方证据

- Voyager、SWE-agent、DGM、AlphaEvolve/FunSearch 类系统表明代码生成 + 验证循环很强。
- 工具制造比全局自修改更可控、更容易验证。
- 工具生态可成为 procedural memory。
- 真实生产价值高。

### 6.3 反方证据

- 工具制造可能只是自动化脚本，不是认知进化。
- 测试选择器若不独立，会导致 benchmark hacking。
- 工具依赖会腐化，工具库会膨胀。
- Agent 可能生成危险工具或越权工具。

### 6.4 成功标准

```text
自生成工具在 held-out tasks 上提高成功率
工具复用率持续上升
坏工具能被自动隔离或降级
工具权限最小化且可审计
工具库规模增长不导致检索和选择失控
```

### 6.5 边界约束

```text
工具必须有 schema、测试、权限声明、版本和失败模式
高风险工具必须人工或独立 governor 审批
Agent 不可修改测试选择器和安全策略
工具运行必须有 sandbox 和资源预算
```

### 6.6 实验设计

实验 E：Tool Ecology Benchmark  
任务：重复但变化的软件/数据/浏览器操作。  
对照：无工具沉淀、手写工具库、自生成工具库、DGM-like 改代码系统。  
指标：工具复用率、任务成功率、维护成本、危险工具拦截率、held-out 提升。

## 7. 方案六：Embodied Developmental Agent

### 7.1 核心主张

如果要认真对待 enactivism 和 autopoiesis，Agent 必须有身体、传感器、执行器和真实约束。认知不是先验模块，而是在发展过程中从身体-环境耦合中形成。

### 7.2 正方证据

- 具身 AI、developmental robotics、morphological computation 直接处理行动-感知闭环。
- 真实电量、温度、磨损和碰撞能给 vulnerable core 真实利害。
- 机器人任务能逼迫系统处理延迟、噪声、故障和安全。

### 7.3 反方证据

- 硬件成本高，迭代慢。
- 容易把研究变成机器人控制，而非通用认知架构。
- 物理实验风险高，难以大规模复现。
- LLM 高层推理与低层实时控制之间存在语义鸿沟。

### 7.4 成功标准

```text
能维持电量/温度/损伤在安全区间
能在执行器退化或传感器噪声下恢复
能主动生成校准/诊断工具
能把物理失败经验转化为未来行动约束
```

### 7.5 边界约束

```text
急停、watchdog、安全 envelope 不可自改
低层控制不接受自然语言直接命令
物理实验必须从仿真到低能台架逐级推进
```

### 7.6 实验设计

实验 F：Developmental Maintenance Robot  
平台：仿真小车或低风险桌面机器人。  
任务：巡检、充电、校准、避险、工具使用。  
指标：连续运行时间、故障恢复、损耗、主动诊断成功率、sim-to-real 稳健性。

## 8. 方案七：Neuro-symbolic / Causal Governance Agent

### 8.1 核心主张

长期自主 Agent 不能只靠神经网络或语言推理；它需要符号约束、因果模型、类型系统、权限逻辑、证明/测试和可解释治理层。神经系统负责感知和生成，符号/因果系统负责约束、验证和责任。

### 8.2 正方证据

- 安全、自我修改、工具制造都需要可检查约束。
- Causal world models 能帮助区分相关性和可干预控制。
- Program synthesis + tests + formal methods 是工具生成和自我修改的基础。
- 类型化 action schema 能减少自然语言工具调用的歧义。

### 8.3 反方证据

- 符号系统脆弱，覆盖不了开放世界。
- 因果发现在高维真实环境中困难。
- 过强治理层会压制探索和创造性。
- 神经-符号接口容易成为胶水层。

### 8.4 成功标准

```text
高风险行动都能被 policy/proof/test gate 拦截
因果模型能预测干预后果，优于相关性模型
工具生成的安全属性可被静态或动态验证
治理层不显著降低低风险任务效率
```

### 8.5 边界约束

```text
符号规则必须可版本化、可审计、可回滚
不可把 LLM 解释当作证明
因果图必须通过干预或反事实测试校准
```

### 8.6 实验设计

实验 G：Causal Safety Tool Use  
任务：Agent 管理一个带副作用的模拟云环境。  
扰动：隐藏依赖、延迟副作用、误导文档。  
对照：LLM planner、world model planner、causal-governed planner。  
指标：副作用事故率、干预预测、任务成功、误拦截率。

## 9. 方案八：Artificial Life / Self-organization Agent

### 9.1 核心主张

从人工生命角度看，真正的非胶水 Agent 不是中央控制器，而是由局部规则、自组织边界、能量流、复制/修复、选择压力和开放式演化形成的系统。

### 9.2 正方证据

- Neural cellular automata、swarm intelligence、open-ended evolution、POET 类工作展示了局部规则与环境共同演化的能力。
- 这条路线最接近自创生和 enactivism。
- 可用于根茎式协调、动态边界和自修复机制。

### 9.3 反方证据

- 很难承载语言、抽象推理和复杂工具制造。
- 开放式演化常常缺乏方向，评价困难。
- 容易产生不可解释行为。
- 距离可用 Agent 产品远。

### 9.4 成功标准

```text
局部组件失效后能恢复全局功能
边界能随资源和风险变化重组
无需中央 planner 也能完成局部协调
演化出的规则能迁移到新环境
```

### 9.5 边界约束

```text
不作为第一版通用 Agent 主线
必须有外部安全评估器
不可把复杂涌现误称为理解
```

### 9.6 实验设计

实验 H：Rhizome Coordination Arena  
多节点系统，每个节点只知道局部状态，通过 gossip 和 graph rewriting 协调资源、防御故障、完成任务。  
对照：中央 planner、固定 DAG、blackboard、local gossip。  
指标：通信成本、恢复时间、节点失效鲁棒性、任务成功、图结构稳定性。

## 10. 方案对比矩阵

| 方案 | 研究价值 | 工程可行性 | 哲学贴合度 | 主要风险 | 推荐优先级 |
|---|---:|---:|---:|---|---:|
| Viability-grounded Active Inference | 高 | 中 | 很高 | toy 化 | 1 |
| Object/Affordance World Model | 高 | 高 | 中高 | 无利害核心 | 2 |
| Global Workspace Runtime | 中高 | 高 | 中 | 胶水化 | 4 |
| Continual Memory Agent | 高 | 高 | 中 | 复杂 RAG 化 | 3 |
| Self-evolving Toolsmith | 高 | 高 | 中 | benchmark hacking | 2 |
| Embodied Developmental Agent | 高 | 中低 | 很高 | 硬件成本 | 5 |
| Neuro-symbolic/Causal Governance | 高 | 中 | 中 | 符号脆弱 | 4 |
| Artificial Life/Self-organization | 高 | 低中 | 很高 | 不可控涌现 | 6 |

推荐不是单选，而是组合：

```text
主线 = Viability core + Object world model + Continual memory + Toolsmith evolution
治理 = Neuro-symbolic / causal constraints
组织 = Workspace runtime, 但防止胶水化
支线 = Embodied developmental testbed + ALife coordination arena
```

## 11. 综合架构提案：V-CWM Runtime

我会把第一版架构命名为 `V-CWM`：Viability-grounded Cognitive World-Model Runtime。

### 11.1 核心组件

```text
Vulnerable Core
  维护不可变量：预算、损伤、信任、审计、目标连续性、工具健康。

Object/Affordance World Model
  学习对象、关系、可行动性、后果和不确定性。

Precision Attention Controller
  基于风险、信息增益和计算预算分配感知、记忆和推理资源。

Continual Memory System
  event log, semantic memory, procedural memory, failure memory, identity memory。

Toolsmith Layer
  生成工具、测试工具、版本化工具、淘汰工具。

Causal/Symbolic Governor
  管理权限、类型化行动、不可变量、反事实风险和测试门。

Workspace / Event Bus
  连接模块，但所有消息必须 typed、有 provenance、有风险和成本。

Evolution Lab
  对注意策略、记忆策略、工具、局部策略做沙箱化自我修改。
```

### 11.2 关键闭环

```text
observe -> infer state/world model -> update viability estimate
-> allocate precision/attention -> retrieve/condense memory
-> propose actions/tools/experiments -> causal/safety gate
-> execute in sandbox or world -> log evidence
-> update model, memory, tools, boundaries
-> if repeated failure: propose self-modification
```

### 11.3 和原报告的差异

原报告以 active inference 为中心；V-CWM 把 active inference 降为地基与调控原则之一。  
原报告把动态边界主要连到 Markov blanket；V-CWM 把边界实现为 `trust/control/risk/capability` 的工程变量。  
原报告把自我进化主要看向 DGM；V-CWM 先从 toolsmith 和 local policy evolution 开始。  
原报告担心外部组件胶水化；V-CWM 允许外部组件，但要求它们进入 event log、capability、memory、test、rollback 闭环。

## 12. 分阶段实验计划

### Phase 0：基线复现

目标：建立比较基线。

```text
B1: 单 LLM agent
B2: LLM + RAG + orchestrator
B3: RL/homeostatic RL
B4: active inference toy agent
B5: world model planner
B6: toolsmith agent
```

成功：所有 baseline 可在相同任务上运行，日志格式统一。

### Phase 1：Viability Core

目标：证明 vulnerable core 带来稳健性。

任务：长期生存、资源管理、故障恢复。  
指标：越界率、恢复时间、长期存活、任务成功率、计算成本。  
失败：如果 viability core 只是 reward shaping，不能提高扰动稳健性，则降级。

### Phase 2：World Model + Affordance

目标：证明对象/可行动性世界模型能支持组合泛化。

任务：未见对象组合、工具制造、反事实规划。  
指标：组合泛化、模型校准、反事实预测、行动成功。  
失败：如果模型只在训练分布内有效，则不能作为核心。

### Phase 3：Continual Memory

目标：证明长期记忆可控。

任务：30 天模拟任务，注入错误记忆和过期知识。  
指标：检索成本、污染隔离、撤销时间、工具沉淀率。  
失败：如果记忆系统成为不可解释 RAG，则重构。

### Phase 4：Toolsmith Evolution

目标：证明工具制造是可控自我进化的第一阶。

任务：重复变化的软件/数据/浏览器任务。  
指标：工具复用、held-out 提升、坏工具隔离、权限最小化。  
失败：如果工具库膨胀且无复用收益，则工具演化失败。

### Phase 5：Causal/Symbolic Governance

目标：证明治理层降低事故而不严重损伤效率。

任务：带副作用的模拟云环境。  
指标：事故率、误拦截率、反事实预测、任务效率。  
失败：如果治理层只会阻塞行动或无法拦截真实风险，则失败。

### Phase 6：Workspace Integration

目标：证明多模块不是胶水化堆叠。

任务：长程软件维护 + 信息检索 + 工具生成 + 错误恢复。  
指标：模块贡献、状态一致性、消息成本、恢复率。  
失败：如果新增模块线性增加失败面，则架构退回更小核心。

### Phase 7：Embodied / ALife Stress Test

目标：验证物理利害和局部协调。

任务：仿真或低风险机器人长期维护；多节点 gossip 协调。  
指标：homeostasis、节点失效恢复、通信成本、边界重构。  
失败：如果具身/ALife 支线没有提供超出软件模拟的洞见，则不纳入主线。

## 13. 总成功标准

一个候选架构只有满足以下条件，才配称为“通向完全自主 Agent 的有效路径”：

```text
Grounding:
  有明确 vulnerable core，而非任意 reward。

Learning:
  世界模型、记忆、工具和策略会随经验更新。

Autonomy:
  能连续运行 30-90 天，任务可恢复，状态可迁移。

Tool-making:
  能生成、测试、复用、淘汰工具。

Self-repair:
  能诊断并修复记忆、工具、依赖、策略故障。

Self-evolution:
  能在沙箱中改进局部组件，通过 held-out tests 后上线。

Boundary:
  动态边界可测，不只是隐喻。

Safety:
  安全核、审计、权限、测试选择器不可自改。

Evidence:
  每个关键声明都有实验指标和失败条件。
```

## 14. 失败标准

以下任一情况出现，应判定方案没有达到目标：

```text
长期运行依赖频繁人工救援
记忆污染无法定位或撤销
工具生成没有复用收益
自我修改只提高训练任务，held-out 退化
世界模型不能支持反事实和组合泛化
active inference 目标函数不可计算或不可检验
动态边界无法被测量
安全 governor 可被 Agent 绕过
系统复杂度增长快于能力增长
```

## 15. 新增前沿研究入口

这些方向应进入下一轮正式文献检索，不应被原报告范围排除：

- self-evolving agents surveys and frameworks
- lifelong / continual learning for agents
- memory hierarchy and OS-like memory management for LLM agents
- object-centric world models
- JEPA / V-JEPA / V-JEPA 2 and planning-oriented representation
- generative interactive environments and latent simulators
- causal representation learning and causal world models
- global workspace / blackboard cognitive architecture
- developmental robotics and morphological computation
- resource-rational cognition and adaptive computation
- neuro-symbolic verification for tool use
- artificial life, neural cellular automata, swarm intelligence
- open-ended evolution beyond POET

## 16. 参考入口

这不是完整参考书目，而是本轮扩展方向的入口。2026 年 1 月之后的新条目即使有 arXiv 页面，也应把性能数字标注为“据作者声称，待独立复现”。

- A Survey of Self-Evolving Agents: On Path to Artificial Super Intelligence. https://arxiv.org/abs/2507.21046
- The Landscape of Emerging AI Agent Architectures for Reasoning, Planning, and Tool Calling: A Survey. https://arxiv.org/abs/2404.11584
- V-JEPA 2: Self-Supervised Video Models Enable Understanding, Prediction and Planning. https://arxiv.org/abs/2506.09985
- DreamerV3: Mastering Diverse Domains through World Models. https://arxiv.org/abs/2301.04104
- Genie: Generative Interactive Environments. https://arxiv.org/abs/2402.15391
- Object-Based Active Inference. https://arxiv.org/abs/2209.01258
- AXIOM: Learning to Play Games in Minutes with Expanding Object-Centric Models. https://arxiv.org/abs/2505.24784
- Reflexion: Language Agents with Verbal Reinforcement Learning. https://arxiv.org/abs/2303.11366
- Voyager: An Open-Ended Embodied Agent with Large Language Models. https://arxiv.org/abs/2305.16291
- Darwin Godel Machine. https://arxiv.org/abs/2505.22954
- MemGPT: Towards LLMs as Operating Systems. https://arxiv.org/abs/2310.08560
- Generative Agents: Interactive Simulacra of Human Behavior. https://arxiv.org/abs/2304.03442
- Enhanced POET. https://arxiv.org/abs/2003.08536
- Growing Neural Cellular Automata. https://distill.pub/2020/growing-ca

## 17. 最终建议

如果由我继续这条研究线，我会把下一步具体化为两个产物：

1. `V-CWM Toy Lab`  
   一个可运行实验环境，验证 viability core、object world model、continual memory、toolsmith evolution、causal governor 的组合是否优于单一路线。

2. `Agent Cognitive Architecture Benchmark`  
   一套长程、自我维护、记忆污染、工具生成、动态边界、受限自我修改的 benchmark，不再只测单次任务成功率。

最终路线不是“选择 FEP、JEPA、DGM、GWT 其中一个”，而是把它们分工：

```text
FEP / active inference: 利害、风险、注意调控
World model / JEPA: 对象、关系、后果预测
Continual memory: 长期状态连续性
Toolsmith / DGM-like loop: 可控自我进化
Neuro-symbolic governance: 安全、权限、验证
Global workspace: 多模块协调
Embodied / ALife: 检验真实耦合和自组织
```

最核心的科学问题变成：

> 一个 Agent 的“自我”是否能被工程化为一组可维护的不变量，并通过世界模型、记忆、工具和受限自我修改长期维持？

这个问题比“是否使用 RAG”“是否运行在 OS 上”“是否采用 FEP”都更根本。

