# 非“胶水”型 Agent 认知架构与注意力机制文献检索报告

检索日期：2026-06-12  
范围：2020 年以来公开文献为主，必要处回溯早期奠基论文。  
主要来源：arXiv、ACL/EMNLP/NeurIPS/ICLR 论文页、Frontiers/MDPI/PMC/PubMed 条目、Crossref/DOI 页面、Hugging Face Papers、Papers with Code/GitHub 线索、OpenAlex/Semantic Scholar 作为补充。Semantic Scholar 匿名接口在本次检索中出现限流，因此不作为唯一证据源。

## 1. 引言：冲突与目标

当前主流 Agent 工程范式通常是 LLM + RAG + 记忆库 + 工具调用 + 编排层。这个组合非常有效，但它的系统形态更像“胶水架构”：智能行为由多个异质外部组件拼接而成，每增加一个能力就增加一次跨系统调用、状态同步和安全边界设计。RAG 与向量数据库解决了外部知识检索，却把“记忆”从智能体的自我动力学中剥离；工具调用解决了外部行动，却让行动选择依赖中央 orchestrator；任务规划解决了长链执行，却常常是 prompt-level 或框架级流水线。结果是成本、可观测性、安全边界和自我演化能力都很难随规模线性扩展。

你的研究问题要求更强的立场：Agent 不应只是外部组件的调用者，而应有一个自我维持的利害核心，并把记忆、规划、注意、技能和边界管理内化为同一耦合动力系统的不同观察窗口。这个方向同时牵涉三条文献线索：

1. 工程注意力机制：Transformer self-attention、稀疏/线性/硬件友好注意力、长上下文 KV 管理、attention sink、GQA、FlashAttention、Native Sparse Attention、状态空间模型等。
2. 认知注意力机制：主动推理中的 precision weighting、salience、epistemic value、affordance selection，把注意力理解为行动-感知闭环中的不确定性调控，而不是孤立的信息选择模块。
3. 自主进化机制：Reflexion、Voyager、Darwin Godel Machine 等把“反思”“技能库”“代码自修改”做成可测系统，但它们目前仍主要依赖外部 LLM、文本记忆和 benchmark 验证，不等同于自创生动力系统。

本报告的基本判断是：截至 2026-06-12，尚未发现一个系统同时满足：(a) 自由能驱动的主动推理，(b) 可生长的动态边界或可变化马尔可夫毯，(c) Godel/DGM 风格自指代码修改。最接近“第一块基石”的不是注意力工程本身，而是“有生理/系统利害的 homeostatic active inference toy agent”。但工程上要跑起来，必须借用注意力机制的三类成果：选择性采样、长时程内部记忆、局部协调。

## 2. 目标数据库与检索式

目标论文网站和数据库建议固定为以下组合：

| 来源 | 用途 | 本轮作用 |
|---|---|---|
| arXiv | AI、主动推理、预印本、2025-2026 新系统 | 主来源；确认题名、时间、摘要、版本 |
| ACL Anthology / EMNLP / NeurIPS / ICLR / OpenReview | 工程注意力机制与 Agent 论文的会议状态 | 用于区分预印本与正式会议论文 |
| Semantic Scholar | 引用网络、相关论文扩展 | 本轮被 429 限流，仅作补充 |
| OpenAlex / Crossref | DOI、期刊、出版信息 | 适合验证出版状态 |
| PubMed / PMC / Frontiers / MDPI | 认知科学、主动推理、神经机器人、interoception | 主动推理和 homeostasis 线索 |
| Hugging Face Papers | AI 论文、模型/数据/代码链接 | 用于补充 AI 论文生态和开源线索 |
| Papers with Code / GitHub | 可复现实装 | 用于标记“机制”还是“规整理想” |

核心检索式分三组：

- 注意力工程：`efficient attention transformer 2020`, `linear attention transformer`, `long context attention`, `FlashAttention`, `GQA`, `attention sinks`, `Native Sparse Attention`, `state space model attention alternative`
- 主动推理与认知注意：`active inference attention precision`, `epistemic value salience affordance active inference`, `object-based active inference`, `homeostatic active inference agent`
- 自我边界与自我修改：`Markov blanket dynamic boundary active inference`, `Markov blankets in the brain`, `Darwin Godel Machine`, `Reflexion language agents`, `self-modifying coding agents`

## 3. 2020 年以来注意力机制论文谱系

### 3.1 2020-2022：从二次复杂度到稀疏/线性/近似注意力

这一阶段的核心问题是 Transformer 自注意力的 O(n^2) 时间/内存复杂度。Longformer 提出滑窗局部注意力加任务驱动全局注意力，使长文档处理趋于线性复杂度；arXiv 摘要明确指出标准 self-attention 随序列长度二次增长，并提出线性伸缩的替代机制。BigBird 通过局部、随机和全局稀疏模式维持长序列建模能力。Linformer 假设 self-attention 矩阵低秩，把复杂度降为线性。Performer 用 FAVOR+ 随机特征近似 softmax attention，强调正交随机特征和可扩展性。Reformer 使用 LSH attention 和 reversible layers，减少长序列内存成本。Tay 等的 Efficient Transformers survey 对 Reformer、Linformer、Performer、Longformer 等“X-former”做了系统分类，并把它们定位为围绕计算和内存效率的架构变体。

这批工作对你的研究问题的意义是：它们证明“注意力”可以从全局中央广播改造成局部、稀疏、近似或可学习路由。若要反对胶水架构，重要启发不是某个具体 Transformer 变体，而是让信息流成为局部动力学规则：局部窗口、全局锚点、低秩瓶颈、核化近似、随机路由，都可以被解释为动态边界与局部协调的工程原型。

关键论文：

- Tay et al., 2020/2022, Efficient Transformers: A Survey. https://arxiv.org/abs/2009.06732
- Beltagy et al., 2020, Longformer: The Long-Document Transformer. https://arxiv.org/abs/2004.05150
- Zaheer et al., 2020, Big Bird: Transformers for Longer Sequences. https://arxiv.org/abs/2007.14062
- Wang et al., 2020, Linformer: Self-Attention with Linear Complexity. https://arxiv.org/abs/2006.04768
- Choromanski et al., 2020/2021, Rethinking Attention with Performers. https://arxiv.org/abs/2009.14794
- Kitaev et al., 2020, Reformer: The Efficient Transformer. https://arxiv.org/abs/2001.04451
- Katharopoulos et al., 2020, Transformers are RNNs: Fast Autoregressive Transformers with Linear Attention. https://arxiv.org/abs/2006.16236

### 3.2 2022-2024：精确注意力的硬件化与长上下文运行时

FlashAttention 是关键转折。它并不近似注意力，而是用 IO-aware tiling 避免把完整 attention matrix 写入 HBM，从而把精确 attention 做得更快、更省内存。FlashAttention-2 继续改进并行度和 work partitioning，摘要明确指出 attention layer 是长序列伸缩的主要瓶颈，并报告相对 FlashAttention 约 2 倍加速。PagedAttention/vLLM 则从推理系统角度处理 KV cache 的分页和共享，使长上下文服务从模型结构问题变成运行时内存管理问题。GQA 在 MHA 和 MQA 之间折中，用较少 KV head 换取接近 MHA 的质量和接近 MQA 的速度。StreamingLLM 提出 attention sinks，说明少量初始 token 可作为稳定注意力锚点，使窗口化流式推理更可行。

这些论文对 Agent 架构的意义很直接：长期自主运行不只需要“更长上下文”，还需要可控的记忆写入、压缩、锚点和遗忘机制。注意力机制从“输入 token 之间的相似度”变成“有限计算预算下哪些状态值得保留”的机制。若把自创生核心看作维持 viability 的系统，那么 attention sink、KV eviction、GQA、paged cache 都可以被抽象成资源约束下的边界调控。

关键论文：

- Dao et al., 2022, FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness. https://arxiv.org/abs/2205.14135
- Dao, 2023, FlashAttention-2. https://arxiv.org/abs/2307.08691
- Kwon et al., 2023, Efficient Memory Management for Large Language Model Serving with PagedAttention / vLLM. https://arxiv.org/abs/2309.06180
- Ainslie et al., 2023, GQA: Training Generalized Multi-Query Transformer Models from Multi-Head Checkpoints. https://arxiv.org/abs/2305.13245
- Xiao et al., 2023/2024, Efficient Streaming Language Models with Attention Sinks. https://arxiv.org/abs/2309.17453
- Liu et al., 2023, Ring Attention with Blockwise Transformers for Near-Infinite Context. https://arxiv.org/abs/2310.01889

### 3.3 2023-2026：注意力替代物与混合长期记忆

RetNet、RWKV、Mamba、Mamba-2、Kimi Linear 等工作把“注意力”与“递归/状态空间/线性时间记忆”重新放到同一张图中。Mamba 的选择性状态空间模型表明，并非所有长期依赖都必须通过显式 token-token attention 表达。RetNet 以 retention 机制结合并行训练、递归推理和长程保留。Native Sparse Attention 进一步把稀疏注意力做成硬件对齐、可原生训练的机制。DeepSeek-V2 的 MLA、GQA/MQA 系列、Infini-attention 和 TransformerFAM 等则把 KV cache 压缩、潜变量注意力和 feedback memory 推到模型结构层。

对你的问题来说，这一支文献支持“记忆内化”的工程路径：不是给 Agent 外接向量库，而是在动力系统内部用可学习状态、压缩记忆、选择性写入、局部检索和反馈通道组织历史。注意力机制在这里不再只是 Transformer 子层，而是长期自主运行系统的“可塑边界”和“资源调度”机制。

关键论文：

- Sun et al., 2023, Retentive Network: A Successor to Transformer for Large Language Models. https://arxiv.org/abs/2307.08621
- Gu and Dao, 2023, Mamba: Linear-Time Sequence Modeling with Selective State Spaces. https://arxiv.org/abs/2312.00752
- DeepSeek-AI, 2024, DeepSeek-V2, including Multi-head Latent Attention. https://arxiv.org/abs/2405.04434
- Munkhdalai et al., 2024, Leave No Context Behind: Efficient Infinite Context Transformers with Infini-attention. https://arxiv.org/abs/2404.07143
- DeepSeek-AI, 2025, Native Sparse Attention. https://arxiv.org/abs/2502.11089
- Kimi Team, 2025, Kimi Linear: An Expressive, Efficient Attention Architecture. https://arxiv.org/abs/2510.26692

2025-2026 的条目多为预印本或工业实验报告。若引用其性能数字，应标注“据作者声称，待独立复现”。结构性思想可以引用，benchmark 结论不宜作为强事实。

## 4. 地基：自创生/利害如何形式化

如果自由能最小化只是“减少预测误差”，它很容易退化成没有利害的统计优化。要让它具有非平凡的生物/系统意义，需要把 surprise/free energy 绑定到 viability：系统必须维持自身变量在可生存区间内，并通过行动、感知和学习降低未来失稳风险。

最清楚的形式化路径有三种：

1. Homeostatic prior / preferred observations：把温度、能量、损伤、压力、资源等内部变量的可行区间写入 prior preference。行动不是最大化外部奖励，而是最小化 expected free energy，其中 risk 项惩罚偏离偏好状态，ambiguity/epistemic 项驱动探索。
2. Viability constraint / vulnerable core：定义内部状态 x_int 的安全集合 V，目标不是 reward，而是最大化留在 V 内的概率，或最小化未来越界概率与不确定性。可写为 `min_pi E_q[G(pi)]`，其中 G 包含风险、歧义、信息增益和内部稳态代价。
3. Allostatic extension：不只维持当前 set-point，还根据未来预测调整 set-point。例如压力激素/能量储备变量可作为调节项，把长期生存风险映射到底层生理控制。

实证/玩具环境方面，Tschantz et al. 的 interoceptive control 模拟把 homeostatic、allostatic 和 goal-directed control 放到 active inference 生成模型中，属于最直接的 toy 证据。Khan and Lowe 2024 把 prediction error 与人工 cortisol/stress 变量耦合，模拟带人工生理的 active inference agent 在随机环境中的长期调节。Da Costa et al. 2024 则把 active inference 明确表述为 reward maximisation 之外的 agency 框架，强调 risk 和 ambiguity 的统一。

结论：地基层已有可证伪机制，但还不够接近通用 Agent。可证伪点包括：在相同环境中，带 homeostatic/allostatic prior 的 agent 是否比纯 reward/RL agent 更稳定、更少灾难性越界；当内部变量噪声、资源稀缺或传感器退化时，是否能通过主动采样和策略切换恢复 viability。

关键文献：

- Tschantz et al., 2022, Simulating homeostatic, allostatic and goal-directed forms of interoceptive control using active inference. DOI: 10.1016/j.biopsycho.2022.108266
- Khan and Lowe, 2024, Surprise! Using Physiological Stress for Allostatic Regulation Under the Active Inference Framework. https://arxiv.org/abs/2406.08471
- Da Costa et al., 2024, Active Inference as a Model of Agency. https://arxiv.org/html/2401.12917v1
- Da Costa et al., 2022, How Active Inference Could Help Revolutionise Robotics. https://www.mdpi.com/1099-4300/24/3/361

## 5. 立场：表征之战的选边与调和

本报告建议选择“温和表征主义”，更具体地说是 affordance-based active inference：内部状态可以是表征，但它们不是脱身的世界镜像，而是行动导向、任务相关、由身体-环境耦合持续校准的可操作结构。

JEPA 风格世界模型并不必然与 enactivism 冲突。冲突点在于强表征主义：如果把内部表征理解为独立于行动、身体和环境的静态世界副本，那么它确实违背 enactivism 的反表征洞见。但 JEPA 的抽象预测表征也可以被解释为“为行动保留的可压缩状态变量”：它不预测像素细节，而预测对未来行动有用的 latent feature。若这些 latent feature 通过 embodied interaction、prediction error、policy success 和 viability pressure 持续被重塑，它们更接近行动导向表征，而不是传统符号表征。

主动推理文献中已有调和框架。Ramstead、Kirchhoff 和 Friston 的 “Active inference is enactive inference” 主张，应把生成模型和识别密度理解为系统-环境耦合中的动力学关系，而不是内部小剧场。A World Unto Itself 也把 active inference 中的注意力区分为 epistemic value 和 precision weighting：前者对应主动采样世界以减少不确定性，后者对应调节感官误差信号在信念更新中的权重。Object-Based Active Inference 则给出工程化折中：对象 slot 是内部表征，但通过选择性注意、行动扰动和学习到的对象动力学获得意义。AXIOM 更进一步，以对象中心生成模型、在线扩展 mixture、Bayesian model reduction 和 active inference planning 学习游戏世界。

VERSES/AXIOM 的立场可概括为：承认内部生成模型，但要求其可解释、可审计、可在线扩展，并把模型证据最大化、主动采样和结构学习合并。它不是无表征主义，而是“可审计的行动导向生成模型”。这与 radical enactivism 不完全相容，但与温和 enactivism、生态心理学和 affordance-based active inference 可调和。

关键文献：

- Ramstead, Kirchhoff and Friston, 2020, A tale of two densities: active inference is enactive inference. https://journals.sagepub.com/doi/10.1177/1059712319862774
- Ramstead, Friston and Hipolito, 2020, Is the Free-Energy Principle a Formal Theory of Semantics? https://www.mdpi.com/1099-4300/22/8/889
- van Bergen and Lanillos, 2022, Object-based active inference. https://arxiv.org/abs/2209.01258
- Friston et al., 2022/2024, Designing Ecosystems of Intelligence from First Principles. https://arxiv.org/abs/2212.01354
- Heins et al., 2025, AXIOM: Learning to Play Games in Minutes with Expanding Object-Centric Models. https://arxiv.org/abs/2505.24784
- LeCun, 2022, A Path Towards Autonomous Machine Intelligence. https://openreview.net/forum?id=BZ5a1r-kVsf
- Assran et al., 2023, Self-Supervised Learning from Images with a Joint-Embedding Predictive Architecture. https://arxiv.org/abs/2301.08243

## 6. 非分层架构：耦合动力系统，而非流水线盒子

建议的架构不是“感知层 -> 记忆层 -> 规划层 -> 工具层”的管道，而是一组共享状态变量的耦合动力系统。可以用如下方式描述：

```text
状态变量：
  c(t)    vulnerable core: 能量、稳定性、预算、损伤、目标承诺、身份连续性
  s(t)    感觉流：外部观测、内部观测、工具反馈、社会反馈
  a(t)    行动流：身体动作、工具动作、注意动作、代码修改动作
  mu(t)   生成模型/识别密度的内部状态
  b(t)    动态边界：哪些变量被纳入“我/可控/可信/内部”
  m(t)    内化记忆：吸引子、可塑参数、对象 slot、技能动力学
  rho(t)  precision/attention 调控：各通道误差信号权重
  g(t)    局部协调图：事件、对象、技能、子策略之间的可变耦合

共同目标：
  minimize expected free energy under viability constraints
  subject to bounded compute, bounded risk, and boundary integrity
```

这些变量之间不是模块调用，而是循环耦合：

- c(t) 通过 prior preferences 决定哪些状态是风险，哪些不确定性值得探索。
- rho(t) 调节 s(t) 中哪些误差信号能改变 mu(t)，对应主动推理中的 attention/precision。
- mu(t) 预测未来感觉与内部状态，生成候选政策 a(t)。
- a(t) 改变外部世界，也改变系统自身的传感器、工具权限、代码和记忆结构。
- b(t) 决定哪些变量属于内部、边界、外部；它不是固定壳，而是由可控性、条件独立性、信任和能量代价共同决定。
- m(t) 不是外部 RAG，而是模型参数、对象 slot、技能吸引子、事件痕迹和可压缩状态的可塑动力学。
- g(t) 是根茎式局部协调图，节点和边通过事件、局部自由能变化和信息增益重写。

## 7. 横切原则：机制还是规整理想

| 概念 | 当前状态 | 机制/算法候选 | 标注 |
|---|---|---|---|
| 自创生/利害核心 | 有 toy 模型 | homeostatic/allostatic active inference, viability constraint, expected free energy | 已有可证伪机制，但非通用 Agent |
| 注意力/precision | 有数学形式和神经/机器人模型 | precision weighting, epistemic value, salience, active sampling | 已有机制 |
| 记忆内化 | 工程线索强，认知整合不足 | state-space memory, object slots, structure learning, BMR, retention/SSM | 部分机制 |
| 自指元认知 | Agent 工程已有最小实现 | Reflexion, Self-Refine, Voyager, DGM | 可证伪工程机制，但多为外部文本/代码循环 |
| 根茎编排 | 概念强，实装弱 | event-driven local rules, gossip, graph rewriting, message passing on factor graphs | 目前主要是规整理想，可提出协议 |
| 动态边界 | 数学概念与批评文献存在 | time-varying Markov blankets, DCM, structure learning, conditional independence discovery | 初步机制；“可生长边界 Agent”仍未成型 |
| 自我代码修改 | DGM 有强工程原型 | archive-based self-modifying coding agents with benchmark validation | 已有机制，但未接入 FEP/动态边界 |

### 7.1 自指元认知

Reflexion 是最小实现之一：语言 Agent 不更新权重，而把任务反馈转成反思文本，写入 episodic memory buffer，后续试验用反思改善决策。这是“元认知”的弱形式：它能反思策略，但不修改底层代码和目标函数。Voyager 在 Minecraft 中维护技能库、自动课程和迭代 prompt，强于 Reflexion，但技能仍以外部代码/文本库形式存在。DGM 是更强形式：它让 coding agent 修改自身代码，并用 SWE-bench、Polyglot 等 benchmark 验证改动，维护演化档案。

可证伪条件：

- Reflexion：若在 held-out 任务中反思记忆不能显著提高成功率，或提升来自泄漏/重复题，则失败。
- Voyager：若技能库不能迁移到新任务，或自动课程只是在已知环境中过拟合，则失败。
- DGM：若自修改在隔离 benchmark、无数据泄漏、固定预算下不能持续改进，或改进不来自自修改而来自基础模型采样，则失败。DGM 的 2026 v3 arXiv 结果仍应视为作者报告，需独立复现。

关键文献：

- Shinn et al., 2023, Reflexion: Language Agents with Verbal Reinforcement Learning. https://arxiv.org/abs/2303.11366
- Wang et al., 2023, Voyager: An Open-Ended Embodied Agent with Large Language Models. https://arxiv.org/abs/2305.16291
- Zhang et al., 2025/2026, Darwin Godel Machine. https://arxiv.org/abs/2505.22954

### 7.2 根茎编排：从隐喻到协议草案

“根茎编排”目前在 AI Agent 文献中不是成熟术语，更接近设计隐喻。若要使其可检验，可以提出一个去中心化协调协议：

1. 系统由局部节点组成：对象 slot、技能吸引子、传感器通道、工具接口、代码片段、目标承诺。
2. 每个节点维护本地 belief、precision、risk、model evidence 和邻接边。
3. 事件格式为 `event = {source, target?, type, payload, precision, delta_F, provenance, ttl}`。
4. 节点只向邻居 gossip 高价值事件：当 `expected information gain - communication cost > threshold` 或 `risk_to_core > threshold` 时传播。
5. 图重写规则包括：新增节点（现有模型解释失败）、合并节点（BMR 后冗余）、切断边（低互信息/高风险）、强化边（预测成功/协同降低自由能）。
6. 没有中央调度器；全局行为来自局部自由能下降、风险约束和边界完整性约束。

该协议可在 toy 环境中验证：比较中央 orchestrator、固定 DAG workflow 和 rhizome gossip-graph rewriting 三种系统，在任务漂移、工具故障、传感器噪声、恶意事件注入下的恢复能力、通信成本和成功率。当前应诚实标注为“规整理想 + 可实现协议草案”，不是已有成熟机制。

### 7.3 动态边界

马尔可夫毯提供边界的统计定义：内部状态与外部状态在 blanket states 条件下独立。2020 年以来的工作把它用于脑区、神经网络、尺度层级和 FEP 争论。Markov Blankets in the Brain 和 Parcels and Particles 把动态耦合与多尺度分区联系起来。Raja et al. 的 Markov blanket trick 及后续评论则提醒：马尔可夫毯不能被随意拿来作为“真实边界”的本体证明，很多时候是建模者根据目标共同构造的分区。Aguilera et al. 进一步批评 FEP 的物理推导在简单线性系统中需要很强条件，不能轻易泛化到复杂生命系统。

因此，动态边界可以建模，但要分清三层：

- 可证伪数学层：给定变量和动态方程，检测随时间变化的条件独立结构。
- 工程建模层：用结构学习、动态因果模型、互信息和可控性估计决定哪些变量纳入内部状态。
- 规整生命层：边界由系统行动和身份生成，而不只是预先给定的 Markov blanket。这部分仍未有通用可运行 Agent。

关键文献：

- Hipolito et al., 2020/2021, Markov Blankets in the Brain. https://arxiv.org/abs/2006.02741
- Friston et al., 2020/2021, Parcels and particles: Markov blankets in the brain. https://arxiv.org/abs/2007.09704
- Raja et al., 2021, The Markov blanket trick. DOI: 10.1016/j.plrev.2021.09.001
- Aguilera et al., 2021/2022, How particular is the physics of the free energy principle? https://arxiv.org/abs/2105.11203

## 8. 可检验性与实证现状

截至 2026-06-12，未发现同时满足三项条件的系统：

1. 自由能驱动的主动推理；
2. 可生长的动态边界或可变化马尔可夫毯；
3. 自指代码修改。

三者各自已有局部证据：

- (a) active inference toy agents、robotics、homeostatic/allostatic simulations 已存在；
- (b) 动态/多尺度 Markov blanket 的数学和神经建模存在，但“Agent 自己长出边界”仍弱；
- (c) DGM 证明自修改 coding agent 的工程路线可跑，但它并非自由能/自创生系统。

最可能作为第一块基石的是 (a)：homeostatic active inference with vulnerable core。理由是它给“自我维持的利害”提供目标函数，使注意、记忆、规划和边界有共同评价尺度。若先做 DGM，自修改可能很快变成 benchmark hill-climbing；若先做动态边界，没有 viability core，边界变化没有生物/系统意义。

建议的最小可行实验：

1. Toy world：二维 grid 或 small game，agent 有 energy、damage、temperature、trust、compute budget 等内部变量。
2. Objective：expected free energy + viability constraint，而非 reward maximization。记录 risk、ambiguity、epistemic value、internal deviation。
3. Attention：precision weighting 控制传感器/工具/记忆通道；可比较 full attention、sparse attention、state-space memory、attention sink。
4. Memory：不用外部向量库，采用对象 slot + recurrent state + Bayesian structure learning；允许状态空间扩展/合并。
5. Boundary：变量可被标为 internal/boundary/external/trusted/untrusted；边界变化由可控性、互信息、风险和模型证据触发。
6. Self-reference：先不允许自由代码修改，只允许修改局部策略、图重写规则或技能函数；通过 sandbox + held-out tasks 验证。
7. Baselines：LLM+RAG+orchestrator、纯 RL、固定 active inference、DGM-like code search。

可证伪指标：

- Viability：越界率、恢复时间、长期存活曲线。
- Efficiency：单位成功任务的 token/调用/计算成本。
- Robustness：传感器噪声、工具故障、任务漂移、恶意记忆注入下性能。
- Boundary quality：纳入边界的变量是否提高预测与控制，而不是无意义扩张。
- Self-modification quality：代码/规则改动在 held-out 环境中是否稳定正收益。

## 9. 通向目标的相关路径研究地图

如果把最终目标定义为“非胶水型、长期自主运行、带自我维持利害、可内化记忆/规划/技能、并具备受限自我进化能力的 Agent 认知架构”，现有研究并不是一条直线，而是几条尚未合流的路径。

### 路径 A：homeostatic / allostatic active inference

贡献：给 Agent 一个非平凡的利害核心。它把自由能最小化从一般统计拟合变成“维持内部变量在可生存区间内”的系统目标。  
代表研究：interoceptive active inference、homeostatic/allostatic control、active inference as agency。  
成熟度：有 toy model 和数学框架，是最适合作为第一块基石的路径。  
缺口：还没有接入可变边界、自我代码修改和复杂长期技能学习。

### 路径 B：precision / attention as active inference

贡献：把注意力从 Transformer 的 token 权重，提升为误差信号加权、主动采样和资源分配。  
代表研究：precision weighting、epistemic value、active sensing、salience under active inference。  
成熟度：认知理论成熟，工程实现分散。  
缺口：尚未形成可替代 LLM Agent 编排层的通用注意力控制器。

### 路径 C：efficient attention / long-context / state-space memory

贡献：为长期自主运行提供工程基础，包括稀疏注意力、线性注意力、FlashAttention、GQA、attention sinks、PagedAttention、RetNet、Mamba、Infini-attention、MLA、Native Sparse Attention 等。  
代表研究：Longformer、BigBird、Linformer、Performer、FlashAttention、StreamingLLM、GQA、Mamba、RetNet、DeepSeek-V2 MLA。  
成熟度：工程成熟度最高。  
缺口：这些机制解决计算和记忆伸缩，不自动带来“自我维持利害”或“自我边界”。

### 路径 D：object-centric / affordance-based representation

贡献：处理“表征之战”的调和问题。对象 slot、affordance、action-oriented representation 可以作为温和表征主义方案：内部表征不是世界镜像，而是可行动、可预测、可控制的结构。  
代表研究：Object-Based Active Inference、Slot Attention 系列、JEPA/I-JEPA/V-JEPA、AXIOM。  
成熟度：已有机器学习和主动推理实现。  
缺口：对象中心模型通常还没有 vulnerable core；JEPA 也未自然导出自创生目标。

### 路径 E：dynamic Markov blankets / dynamic boundaries

贡献：给“边界”一个数学语言：内部、外部、感知、主动状态之间的条件独立结构。  
代表研究：Markov Blankets in the Brain、Parcels and Particles、The Markov blanket trick、particular physics debates。  
成熟度：理论强，争议也强。  
缺口：目前更多是建模/解释框架；“Agent 在线生长和收缩自身边界”的工程系统还没有成熟。

### 路径 F：open-ended evolution / self-improving agents

贡献：让系统不只在固定任务上学习，而能生成新挑战、维护候选体档案、搜索自身改进路径。  
代表研究：POET / Enhanced POET、Voyager、Reflexion、DGM、AlphaEvolve。  
成熟度：open-ended search 和 coding-agent 自修改已有强原型。  
缺口：大多仍是外部评估器 + LLM/演化循环，不是内生自由能动力学。DGM 是自修改最相关路径，但还没有接入 homeostatic active inference 或动态马尔可夫毯。

### 路径 G：differentiable self-organization / neural cellular automata

贡献：提供非中央控制、局部规则、可再生/可修复结构的实现灵感，适合“根茎式协调”和动态边界。  
代表研究：Growing Neural Cellular Automata、differentiable self-organizing systems。  
成熟度：toy 系统很有启发，机制清晰。  
缺口：目前主要在形态生成/局部控制层面，距离 LLM-scale Agent 认知架构较远。

### 路径 H：sandboxed self-modification / verifiable code evolution

贡献：把自指修改变成工程上可控的流程：候选改动、隔离执行、benchmark 验证、回滚、档案维护。  
代表研究：DGM、AlphaEvolve、FunSearch 类验证式程序发现。  
成熟度：工程路径明确。  
缺口：目标函数多为外部 benchmark 成绩，不是系统自身 viability；容易变成“更强的优化器”，而非自我维持智能体。

### 路径合流建议

最可行的路线不是从 LLM Agent 编排框架继续堆组件，而是按以下顺序合流：

1. 先做 homeostatic active inference toy agent，建立 vulnerable core。
2. 加 precision/attention，使注意力成为风险、探索和计算预算的调控机制。
3. 用 object-centric / state-space memory 内化记忆，减少外部 RAG。
4. 用动态边界变量模拟 Markov blanket 的在线重构。
5. 用 local graph rewriting / gossip 实现根茎式协调。
6. 最后接入 DGM-style sandboxed self-modification，让系统修改局部规则或技能，而不是一开始就自由改全局代码。

这几条路径中，A 是地基，B/C/D 是认知与工程桥梁，E/G 是非分层和边界生长的理论/机制来源，F/H 是自我进化路径。当前没有一条路径单独通向目标；真正的研究贡献会来自它们的受控合成。

新增参考：

- Wang et al., 2020, Enhanced POET: Open-Ended Reinforcement Learning through Unbounded Invention of Learning Challenges and their Solutions. https://arxiv.org/abs/2003.08536
- Mordvintsev et al., 2020, Growing Neural Cellular Automata. https://distill.pub/2020/growing-ca
- Novikov et al., 2025, AlphaEvolve: A coding agent for scientific and algorithmic discovery. https://arxiv.org/abs/2506.13131

## 10. 文献证据表

下表把关键文献从“可复现机制”“概念/理论支持”“规整启发”三个层面拆开。它不是引用堆砌，而是为了判断哪些部件能直接进入最小实现，哪些只能作为研究约束。

| 路径 | 代表文献/系统 | 支持的命题 | 证据类型 | 可直接复用的机制 | 主要缺口 |
|---|---|---|---|---|---|
| Homeostatic active inference | Tschantz et al. 2022, interoceptive control | 内部稳态变量可作为主动推理偏好状态 | toy simulation / Biological Psychology | interoceptive observations, preferred ranges, homeostatic/allostatic policy selection | 任务很小，未包含代码自修改和动态边界 |
| Active inference as agency | Da Costa et al. 2024 | agency 可表述为风险与歧义最小化，而非奖励最大化 | 理论/建模论文 | expected free energy decomposition: risk, ambiguity, epistemic value | 对工程 Agent 的落地仍需具体状态空间 |
| Object-based active inference | van Bergen and Lanillos 2022 | 对象中心表征可与主动推理结合 | 模型/算法框架 | object slots, selective attention, object dynamics | 缺 vulnerable core；对象边界不等于自我边界 |
| AXIOM | Heins et al. 2025 | 可在线扩展对象中心生成模型，并用 Bayesian model reduction 精炼 | 预印本/游戏实验，据作者报告 | expanding mixture models, sparse object interactions, BMR | 仍是任务学习系统，不是自创生 Agent |
| Markov blankets in brain | Hipolito et al. 2020; Friston et al. 2020 | Markov blanket 可描述多尺度系统分区 | 理论/神经建模 | conditional independence boundary, multiscale partition | 不能直接推出“真实自我边界”；动态生长机制弱 |
| Markov blanket critique | Raja et al. 2021; Baltieri et al. 2020 | Markov blanket 在 FEP 中不能被过度本体化 | 哲学/数学批评 | 区分 instrumental blanket 与 realist blanket | 主要是约束和警告，不是实现算法 |
| Efficient attention | Longformer, BigBird, Linformer, Performer, Reformer | 注意力可以局部化、稀疏化、近似化 | 工程论文/开源实现 | sparse windows, global tokens, low-rank projection, kernel attention | 只解决计算伸缩，不给利害核心 |
| Runtime attention memory | FlashAttention, GQA, PagedAttention, StreamingLLM | 长期运行需要可控 KV/cache/attention anchor | 工程系统 | IO-aware exact attention, grouped KV heads, paged cache, attention sinks | 仍是模型运行时，不是认知边界 |
| State-space / retention memory | RetNet, Mamba, Infini-attention, MLA | 内部记忆可用递归状态/压缩潜变量替代外部检索 | 工程模型 | selective state update, retention, compressed latent memory | 目标函数仍是预测/语言建模 |
| Reflexion | Shinn et al. 2023 | 不更新权重也可用反思文本提升 Agent 表现 | Agent benchmark | verbal reflection, episodic text memory | 元认知很弱；记忆外置且文本化 |
| Voyager | Wang et al. 2023 | LLM Agent 可开放式积累可执行技能 | Minecraft 系统/开源 | automatic curriculum, skill library, iterative code improvement | 依赖 GPT-4 与外部技能库，非内生动力系统 |
| DGM | Zhang et al. 2025 | coding agent 可修改自身代码并用 benchmark 验证 | 预印本/代码仓库，据作者报告 | archive search, self-modifying code, sandbox validation | 外部 benchmark 驱动；无 FEP/viability core |
| POET / Enhanced POET | Wang et al. 2020 | 环境与 agent 可共同开放式演化 | open-ended RL | archive, paired environment-agent generation | 没有主动推理目标，也非代码自修改 Agent |
| Growing Neural Cellular Automata | Mordvintsev et al. 2020 | 局部规则可产生可修复、自组织结构 | toy differentiable self-organization | local update rules, regeneration, decentralized control | 距认知 Agent 很远，但对根茎协调有启发 |
| AlphaEvolve / FunSearch 类 | Google/DeepMind 2023-2025 | 验证式程序发现能搜索算法改进 | 工程系统/预印本/技术报告 | proposal-evaluation loop, executable verification | 目标外置；不是自我维持系统 |

判断：能立刻进入 toy 系统的只有三类机制：homeostatic active inference、precision/attention 调控、对象/状态空间记忆。DGM、POET、NCA 更适合作为后续扩展路径，而不是第一版核心。

## 11. 最小可运行架构形式化

目标不是先造一个完整通用智能体，而是造一个最小系统，使“利害、注意、记忆、边界、自我修改”都能以变量形式进入同一个闭环。

### 11.1 状态变量

设时间步为 `t`。

```text
e_t      外部环境状态，例如位置、资源、危险源、任务对象
c_t      vulnerable core，内部稳态变量，例如 energy, damage, temperature, compute_budget, trust
o_t      观测，包含外部观测 o_ext_t 与内部观测 o_int_t
mu_t     agent 的生成模型/信念状态
m_t      内化记忆状态，例如对象 slot、递归状态、技能吸引子、事件痕迹
rho_t    precision / attention 权重，决定哪些误差信号更能更新信念
B_t      动态边界变量，标记对象/工具/记忆/技能是 internal, boundary, external, trusted, untrusted
g_t      局部协调图，节点是对象、技能、事件、传感器、工具；边是预测/控制/风险关系
a_t      行动，包括环境动作、注意动作、记忆写入、边界重写、受限代码修改
```

最低实现可以把 `e_t` 做成二维 gridworld，把 `c_t` 做成 4-6 个连续内部变量，把 `B_t` 做成离散标签，把 `g_t` 做成带权图。

### 11.2 生成模型与信念更新

Agent 维护一个生成模型：

```text
p_theta(o_{t+1}, c_{t+1}, e_{t+1}, m_{t+1}, B_{t+1} | e_t, c_t, m_t, B_t, a_t)
```

近似后验：

```text
q_phi(e_t, c_t, m_t, B_t | o_{1:t}, a_{1:t-1})
```

单步变分自由能：

```text
F_t = E_q[ log q_phi(s_t) - log p_theta(o_t, s_t) ]
```

其中 `s_t = {e_t, c_t, m_t, B_t}`。`rho_t` 不作为独立模块调用，而是进入误差加权：

```text
F_t(rho_t) = Sum_i rho_{t,i} * prediction_error_i + complexity_penalty(q || p)
```

这使注意力成为信念更新的调控机制，而不是 Transformer 子层的同义词。

### 11.3 Viability-constrained expected free energy

定义内部稳态安全集合：

```text
V = { c : c_min <= c <= c_max }
```

定义越界距离：

```text
d_V(c) = Sum_j max(0, c_j - c_max_j, c_min_j - c_j)^2
```

对策略 `pi = a_t:t+H` 的目标：

```text
J(pi) =
  E_q[ Sum_{tau=t+1}^{t+H}
      G_tau(pi)
      + lambda_v * d_V(c_tau)
      + lambda_u * U(B_tau)
      + lambda_k * compute_cost(a_tau)
      + lambda_m * modification_risk(a_tau)
  ]
```

其中 expected free energy 可拆为：

```text
G_tau(pi) =
  risk_tau
  + ambiguity_tau
  - epistemic_value_tau
```

可操作化为：

```text
risk_tau          = D_KL( q(o_tau | pi) || p_preferred(o_tau) )
ambiguity_tau     = E_q[ H[p(o_tau | s_tau)] ]
epistemic_value   = I_q(s_tau ; o_tau | pi)
```

关键点：`p_preferred` 不是外部奖励，而由 vulnerable core 诱导，例如低损伤、适中能量、足够计算预算、可信边界完整性。

### 11.4 动态边界更新

边界不是哲学标签，而是一个可学习变量。对每个对象/工具/记忆/技能节点 `v`，维护：

```text
B_t(v) in {internal, boundary, external, trusted, untrusted}
```

更新依据：

```text
score(v) =
  alpha * controllability(v)
  + beta * predictive_gain(v)
  + gamma * mutual_information(v, c_t)
  - delta * risk(v)
  - eta * maintenance_cost(v)
```

若 `score(v)` 高且稳定，则把 `v` 移入 boundary/internal；若风险或维护成本过高，则降级为 external/untrusted。这样得到的是“工程动态边界”，不是强本体论的自我边界。

### 11.5 受限自我修改

第一版不允许 agent 随意改全局代码，只允许三类局部修改：

```text
1. 修改局部图重写规则
2. 修改技能函数或策略片段
3. 修改 attention/precision 调度参数
```

每次修改必须通过：

```text
proposal -> sandbox run -> held-out viability tests -> regression check -> archive or reject
```

目标不是 benchmark 分数最大化，而是：

```text
Delta = J_old - J_new
```

只有当 `Delta > epsilon` 且没有提高越界率、风险暴露、计算成本灾难性增长时，修改才被接受。

### 11.6 最小循环伪代码

```text
initialize theta, phi, m_0, B_0, g_0, vulnerable core c_0

for each time step t:
    observe o_ext_t, o_int_t
    compute prediction errors across sensors, memory, boundary, core
    update rho_t by risk, uncertainty, compute budget
    infer q_phi(e_t, c_t, m_t, B_t)
    update object/state memory m_t
    update boundary labels B_t using controllability, predictive gain, risk, cost
    rewrite local coordination graph g_t if local evidence supports it
    generate candidate policies pi_1...pi_n
    evaluate J(pi) = expected free energy + viability + boundary + compute + modification risk
    execute first action of best policy
    if self-modification action proposed:
        run sandbox and held-out viability tests
        accept only if it improves J without violating constraints
```

这个最小架构满足“非分层”的要求：注意、记忆、边界、行动和自修改不是流水线模块，而是同一个目标函数和状态更新循环中的横切变量。

## 12. 实验路线与可证伪指标

### 12.1 阶段 0：基线环境

环境：二维 gridworld 或 MiniGrid 变体。  
内部变量：`energy, damage, temperature, compute_budget, trust`。  
外部因素：食物、热源/冷源、危险区、可用工具、欺骗性记忆事件、传感器噪声。  
任务：长期存活 + 完成小目标，而不是单局 reward 最大化。

基线：

```text
B0: hand-coded policy
B1: reward-based RL
B2: fixed active inference without dynamic boundary
B3: LLM + RAG + orchestrator
B4: DGM-like external code search without vulnerable core
```

### 12.2 阶段 1：利害核心是否有效

假设：带 vulnerable core 的 active inference agent 在分布漂移和资源稀缺下，比纯 reward/RL 更少灾难性越界。

可证伪指标：

```text
viability_violation_rate
mean_time_to_failure
recovery_time_after_shock
energy_stability_variance
damage_accumulation
task_success_under_resource_scarcity
```

失败条件：若 active inference agent 只在训练分布有效，一旦传感器噪声或资源漂移就比 RL 更差，则“利害核心提供稳健性”的命题失败。

### 12.3 阶段 2：attention/precision 是否不是装饰

假设：precision weighting 能降低无关通道干扰，并在风险升高时优先采样关键传感器。

实验操作：

```text
加入传感器噪声
加入欺骗性记忆
加入高成本但高价值传感器
比较固定注意力、随机注意力、learned precision、active inference precision
```

指标：

```text
information_gain_per_compute
false_memory_susceptibility
risk_detection_latency
sensor_query_cost
belief_calibration_error
```

失败条件：若 precision 调控不能提升单位计算的信息增益，或只是学到固定通道偏好，则“认知注意力机制”没有成立。

### 12.4 阶段 3：记忆内化是否优于外部 RAG

假设：对象 slot + state-space memory 在小环境长期任务中，能以更低检索成本达到接近或优于外部向量库记忆的稳定性。

对照：

```text
external vector memory
episodic text buffer
object-centric memory
state-space recurrent memory
hybrid object + state-space memory
```

指标：

```text
memory_query_cost
long-horizon success
catastrophic_forgetting_rate
spurious_retrieval_rate
adaptation_after_environment_change
```

失败条件：若内化记忆无法支持超过短窗口的任务，或代价高于简单外部检索且无稳健性优势，则“去 RAG 化”路线暂时失败。

### 12.5 阶段 4：动态边界是否可测

假设：边界变量 `B_t` 的在线更新能在工具故障、环境对象变化、恶意输入下保护 vulnerable core，同时不阻碍有用资源纳入。

实验操作：

```text
工具从可靠变为不可靠
传感器被污染
某些外部对象变成可控制资源
记忆库注入错误事件
```

指标：

```text
boundary_precision = useful_internalized / all_internalized
boundary_recall = useful_internalized / all_useful
harmful_internalization_rate
time_to_quarantine_untrusted_node
control_gain_after_internalization
```

失败条件：若边界只会膨胀，或把危险节点纳入 internal 后无法隔离，则“动态边界”只是隐喻。

### 12.6 阶段 5：根茎协调是否优于中央编排

假设：局部 gossip + graph rewriting 在故障和任务漂移下比固定 DAG orchestrator 更稳健，通信成本也更低。

对照：

```text
central orchestrator
fixed workflow DAG
blackboard architecture
local gossip + graph rewriting
```

指标：

```text
message_count_per_success
coordination_latency
failure_localization_time
performance_under_node_dropout
graph_churn_rate
```

失败条件：若局部协议在简单任务中也显著劣于中央编排，且无法解释优势条件，则“根茎编排”应保持为规整理想。

### 12.7 阶段 6：受限自我修改是否带来真实进化

假设：受限自我修改能在 held-out viability tests 上带来稳定改进，而不是过拟合当前环境。

允许修改：

```text
skill functions
local graph rewriting rules
precision scheduling parameters
boundary scoring weights
```

禁止修改：

```text
test harness
sandbox policy
viability metric
logging and audit code
```

指标：

```text
accepted_patch_rate
heldout_viability_delta
regression_rate
compute_cost_growth
unsafe_action_rate
diversity_of_successful_modifications
```

失败条件：若改动只提高训练环境表现、破坏安全边界、或依赖测试泄漏，则“自我进化”不成立。

## 13. 原始提示词是否限制了研究范围或深度

你的提示词质量很高，优点是问题意识清楚：它避免了把 Agent 架构简化成 LLM 工具链，也强制研究同时面对自创生、自由能、表征之战、动态边界和自修改。但它确实会在几个方向上限制研究范围。

### 13.1 对“胶水架构”的批判可能过强

提示词把 LLM + RAG + 工具 + 编排层整体设为反面，这有助于寻找新范式，但也可能遮蔽一个现实：很多所谓胶水组件其实可以被重新解释为外部化认知支架。更深的研究问题不是“是否使用外部组件”，而是：

```text
一个外部组件在什么条件下仍属于 agent 的扩展边界？
什么时候它只是胶水？
什么时候它能被内化为动力系统的一部分？
```

因此，建议把“不要 RAG/向量库/编排框架”改成“第一版核心机制不得依赖它们；但可以把它们作为对照或外部 scaffold”。

### 13.2 对 enactivism 与 FEP 的二分可能太窄

提示词把生成认知/具身进路和 FEP/预测加工设为“表征之战”的两方，这是准确的哲学冲突，但可能漏掉第三类路线：

```text
生态心理学 affordance
控制论与 viability theory
autonomous systems / organizational closure
morphological computation
developmental robotics
open-ended evolution
collective intelligence / swarm cognition
```

这些路线对“非分层、动态边界、自我维持”可能比经典 Transformer 注意力论文更关键。

### 13.3 “非分层”要求容易误伤必要的尺度层级

反对“哲学分层盒子”是对的，但完全排斥层级会限制建模。生物系统并非没有层级，而是没有固定流水线式命令层级。更准确的约束应是：

```text
允许多尺度组织，但不允许固定感知-记忆-规划-行动流水线。
允许临时层级和尺度分解，但它们必须可由系统动力学重构。
```

这能把 Markov blanket、多尺度 active inference、renormalization、object hierarchy 纳入研究。

### 13.4 “自我修改代码”可能把目标过早工程化

DGM 风格代码修改很重要，但如果太早要求“改代码”，研究会偏向 coding benchmark，而不是自我维持。更合适的阶梯是：

```text
参数自调节 -> 图结构重写 -> 技能函数改写 -> 局部代码修改 -> 架构级自修改
```

这样能避免把“自我进化”缩窄为“写 Python patch 的能力”。

### 13.5 注意力机制检索可能被 Transformer 语义牵引

你最后要求“搜集 2020 年以来注意力机制论文”，这会自然把检索拉向 efficient Transformer literature。但对你的核心问题，真正关键的是广义注意力：

```text
precision weighting
active sensing
salience
resource rationality
selective memory consolidation
boundary gating
information bottleneck
```

下一轮检索应把关键词从 `attention mechanism` 扩展到 `precision`, `salience`, `active sensing`, `resource allocation`, `adaptive computation`, `selective memory`。

### 13.6 缺少安全、审计和制度化评价维度

长期自主运行和自我修改必然涉及安全，但提示词主要从认知架构出发，没有单独要求：

```text
sandboxing
audit trail
capability containment
test-set leakage prevention
rollback
modification provenance
interpretability of boundary changes
```

如果目标包含可运行系统，这些不是附加项，而是架构约束。

### 13.7 建议改写后的研究提示词

可以把原提示词升级为：

```text
研究目标：设计并评估一个最小可运行的非胶水型 Agent 认知架构雏形。
它应以 vulnerable core / viability constraint 为地基，在 active inference 框架下统一注意、记忆、行动、边界和受限自我修改。

约束：
1. 第一版核心不得依赖外部 RAG、向量数据库或固定 orchestrator；这些可作为 baseline 或 scaffold。
2. 允许多尺度组织，但不允许固定流水线层级；所有临时层级必须可被动力学重构。
3. 表征立场采用 action-oriented / affordance-based moderate representationalism。
4. 动态边界必须以可测变量实现，不得只作隐喻。
5. 自我修改按参数、图结构、技能函数、局部代码四级递进，并必须经过 sandbox 和 held-out viability tests。
6. 所有概念必须标注为：已有机制、可实现假设、规整理想。

输出：
1. 文献证据表；
2. 最小数学形式化；
3. toy environment 设计；
4. baseline 与指标；
5. 可证伪失败条件；
6. 仍无法实现的规整理想。
```

这样改后，研究范围会更宽，也更可执行：它保留你的核心哲学问题，但把它压到一个能跑、能测、能失败的工程研究计划上。

## 14. 结论：最诚实的规整理想与下一步

最诚实的结论是：非“胶水”型、自我维持、可进化 Agent 认知架构目前不是现成系统，而是一组已经部分成熟的机制需要被合成。注意力机制提供可扩展信息路由和长期上下文管理；主动推理提供统一目标函数和认知注意力解释；homeostatic/allostatic 模型提供利害地基；Markov blanket 提供边界语言但还不能直接保证动态自我；Reflexion/Voyager/DGM 提供自指改进工程证据，但尚未内化到自由能动力学。

建议研究立场是：

- 采用温和表征主义：内部表征允许存在，但必须是行动导向、affordance-based、受 viability 约束、在耦合中持续校正。
- 把“注意力”定义为 precision + epistemic action + resource allocation 的统一调控，不只引用 Transformer attention。
- 把“根茎编排”标注为规整理想，并先实现 gossip + graph rewriting + local expected free energy 的 toy 协议。
- 把“动态边界”标注为部分机制，先做可控变量集合的在线结构学习，不要宣称已实现自创生边界。
- 把 DGM 作为外层自修改实验框架，而不是系统核心；核心必须先有 vulnerable core，否则自修改没有内在利害。

下一步可行步骤：

1. 建一个 2D homeostatic active inference toy agent，明确内部变量和 expected free energy。
2. 加入 selective attention/precision weighting，使 agent 学会调节传感器和记忆通道。
3. 加入对象 slot 或局部 state-space memory，避免外部 RAG。
4. 加入动态边界变量：哪些对象、工具、技能、记忆被纳入“可控/可信/内部”。
5. 加入受限自修改：允许 agent 修改图重写规则或技能函数，但每次修改必须通过 sandbox 和 held-out viability tests。
6. 最后再比较 DGM-style archive search 与 active-inference-internal structure learning 的差异。

一句话概括：第一阶段不要试图直接造“Darwin + FEP + autopoiesis”的完整系统；先造一个会在风险中维持自身、会调节注意和边界、会把记忆作为自身动力学改变的玩具 Agent。这个系统一旦可测，才有资格讨论真正的自我代码进化。
