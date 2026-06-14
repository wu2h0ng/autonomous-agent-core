# Agent 角色与 Skill 配置总表 - 2026-06-13 三层研究版

## 三层路由

```text
autonomous-agent-core/
  = 对象层，主产物，通用自治智能体原型。

ai-native-business-data-agent-os/
  = 部署层，企业 Business Data Agent OS，通用核心的未来降级投影。

ai-agent-engineering-workflow/
  = 元层，开发过程治理工具，不是智能体原型，不是产品运行时。
```

## 研究型 Skills

| Skill | 角色 | 何时使用 |
|---|---|---|
| `autonomous-agent-core-cto` | 自治核心 CTO / 研究工程负责人 | `autonomous-agent-core/`、RR 文档、viability、relevance/attention、world model、corrigibility、audit、实验门 |
| `autonomous-agent-core-research-director` | 研究主任 | 研究路线、学科路由、概念漂移控制、跨学科综合 |
| `autonomous-agent-world-model-researcher` | 世界模型研究员 | world model、active inference、RL、JEPA、环境设计、规划、affordance |
| `autonomous-agent-philosophy-researcher` | 哲学研究员 | 自主性、主体性、规范性、相关性实现、可纠正性、表征、enactivism、autopoiesis |
| `autonomous-agent-math-formalization` | 数学形式化 agent | 方程、变量、不变量、控制论、概率、优化、决策理论、反例 |
| `autonomous-agent-information-theory` | 信息论 agent | 信息流、熵、互信息、通道容量、注意力分配、压缩、Ashby variety |
| `autonomous-agent-bio-cybernetics` | 生物/控制论 agent | viability、代谢、homeostasis、allostasis、autopoiesis、biosemiotics |
| `autonomous-agent-linguistics-semiotics` | 语言学/符号学 agent | 语言、意义、语用、符号、LLM-as-organ、prompt semantics、业务语义边界 |

## 计算机科学与工程型 Research Skills

| Skill | 角色 | 何时使用 |
|---|---|---|
| `autonomous-agent-computation-theory` | 计算理论 agent | 可计算性、复杂度、自动机、算法、不可判定性、近似、online algorithms、资源受限理性 |
| `autonomous-agent-computer-systems` | 计算机系统 agent | OS、runtime、调度、内存、并发、I/O、可观测性、可靠性、性能、部署约束 |
| `autonomous-agent-distributed-systems` | 分布式系统 agent | 共识、协调、一致性、复制、事件顺序、因果性、幂等、事务、消息队列、分布式工作流 |
| `autonomous-agent-data-systems` | 数据系统 agent | 数据库、数据建模、语义层、血缘、provenance、数据契约、向量/搜索索引、OLTP/OLAP、证据质量 |
| `autonomous-agent-programming-languages` | PL / 形式语义 agent | 类型系统、形式语义、DSL、解释器、契约、effect system、状态机、静态分析、形式验证 |
| `autonomous-agent-security-privacy` | 安全与隐私 agent | threat model、capability control、sandbox、secrets、审计、访问控制、prompt/tool injection、数据外泄 |
| `autonomous-agent-hci-cscw` | HCI / CSCW agent | 人机协作、operator control、approval UX、trust calibration、handoff、explainability、corrigibility interface |

## 硬件、固件与加速器适配 Research Skills

| Skill | 角色 | 何时使用 |
|---|---|---|
| `autonomous-agent-hardware-architecture` | 硬件/芯片架构 agent | CPU、GPU、NPU、TPU、RISC-V、ARM、x86、内存层级、cache、interconnect、功耗、延迟、吞吐、hardware-software co-design |
| `autonomous-agent-ai-accelerator-runtime` | AI 加速器 runtime agent | CUDA、ROCm、Metal、TensorRT、ONNX Runtime、TVM、MLIR、Triton、量化、batching、KV cache、模型服务、异构推理 |
| `autonomous-agent-firmware-edge-systems` | 固件/边缘系统 agent | firmware、driver、RTOS、MCU、embedded Linux、sensor/actuator、robotics、IoT、edge gateway、OTA、secure boot、hardware-in-the-loop |

## 更新后的既有 Skills 定位

| Skill | 新定位 |
|---|---|
| `ai-native-business-data-os-ceo` | 三层项目 CEO：同时管理通用自治核心长期技术野心与企业 OS 商业化路径 |
| `ai-native-business-data-os-cto` | 企业部署层 CTO：负责 Trusted Loop、企业产品架构、合同、eval、安全、release readiness |
| `ai-native-business-data-os-product-manager` | 企业部署层产品经理：只把已验证或已批准投影的研究成果转成产品需求 |
| `ai-native-business-data-os-pm` | 企业部署层项目经理：计划企业产品交付；自治核心研究计划默认交给研究主任/自治核心 CTO |
| `ai-native-business-data-os-development-team` | 企业部署层开发协调；遇到自治核心机制或证伪实验时先路由 |
| `ai-native-business-data-os-business-consultant` | 企业商业化顾问：区分 research thesis、已实现产品能力、企业投影假设、可对客户承诺内容 |

## 决策规则

- 研究 specialists 只能建议、批判、形式化，不覆盖 CTO gate、founder 保留决策或预注册实验门。
- 计算机领域 specialists 必须把概念翻译为机制、接口、复杂度、运行时边界、安全控制、数据契约、测试或 gate。
- 硬件/固件 specialists 必须把概念翻译为延迟、吞吐、功耗、内存、实时性、安全更新、设备边界、benchmark 或 hardware-in-the-loop test；不得把项目范围扩成造芯片、机器人或边缘硬件产品，除非 founder/CTO 明确批准。
- `autonomous-agent-core/` 不引入业务语义、不让 LLM 进入控制路径、不跨仓库 import。
- 企业 OS 不能把自治核心研究声明包装成客户可交付能力。
- 工程元层不能被误认为智能体原型或产品运行时。
