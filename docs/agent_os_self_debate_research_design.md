# 自主 Agent / Agent OS 自我辩论审核与实验设计

日期：2026-06-12  
目标：基于前序文献综述、Agent 认知架构讨论、OS 层级争论，给出从技术哲学到技术实现的多方案研究设计。每个方案均给出正反方证据、成功标准和边界约束。

## 0. 总判断

如果我要研究、设计并逐步开发一个“完全自主、无限长程运行、自我进化/修复、会给自己造工具”的 AI Agent，我不会从“裸金属替代 Linux”开始，也不会停留在“LLM + RAG + 工具调用框架”。我会把目标定义为：

> 一个受能力边界约束、具备长期状态连续性、能生成并验证工具、能自我修复和受限自我修改的 Agent-native operating substrate。

这里的关键词不是“无 OS”，而是“生命周期控制”。真正的自主性不是直接写硬件寄存器，而是系统能否长期维护自身的目标、状态、工具、权限、证据、回滚和演化过程。

最合理的主线是：

```text
第一阶段：H4 + A3
  在 Linux/Windows/macOS 等通用 OS 上构建 Agent-native runtime。

第二阶段：H4 + A4
  加入受限自我修改、工具生成、沙箱验证、回滚和长期运行测试。

第三阶段：H4/A4 + H3/H1
  高层认知运行在通用 OS，具身控制运行在 RTOS/固件。

第四阶段：H3/H2 capability substrate
  在 seL4/Tock/CHERI 类底座上做 Agent OS 的安全内核原型。

第五阶段：H0/H1 self-organizing hardware
  作为独立科学路线研究，不作为通用 Agent 主线前提。
```

## 1. 双轴模型：宿主层级不等于 Agent 层级

前序讨论中最大的问题是把“OS 层级”与“Agent 自主层级”混在一起。需要把它们拆开。

### 1.1 宿主层级 H

| 层级 | 名称 | 含义 |
|---|---|---|
| H4 | 通用 OS | Linux, Windows, macOS, Android；有进程、文件系统、网络栈、权限模型 |
| H3 | RTOS / 实时控制层 | FreeRTOS, QNX, VxWorks；确定性调度、外设控制 |
| H2 | Unikernel / 微内核运行时 | 单用途镜像、微内核或能力系统；较少传统 OS 抽象 |
| H1 | 固件 / 裸机控制 | MCU、驱动、中断、寄存器、看门狗 |
| H0 | 可重构硬件 | FPGA、神经形态芯片、忆阻器阵列、硬件自组织 |

### 1.2 Agent 层级 A

| 层级 | 名称 | 含义 |
|---|---|---|
| A0 | 单次任务执行器 | 接受命令、执行、结束 |
| A1 | 工具调用 Agent | 会调用工具/API，但状态和工具多外置 |
| A2 | 长期任务 Agent | 有长期记忆、任务恢复、计划续跑 |
| A3 | 自我修复/工具制造 Agent | 能发现重复任务、生成工具、测试工具、修复失败 |
| A4 | 受限自我演化 Agent | 能在沙箱中修改局部策略/工具/运行时，并经验证后上线 |
| A5 | 无约束自我修改 Agent | 能修改安全核、目标函数、审计和权限边界；不建议作为工程目标 |

结论：当前最有价值目标不是 H0，也不是 A5，而是 **H4 + A4**，再扩展到 **H4/A4 + H3/H1**。

## 2. 技术哲学：要保留哪些原则

### 2.1 自主性是生命周期控制，不是硬件亲密度

正方论点：Agent 越接近硬件，越能拥有真实利害。  
反方论点：硬件亲密度只带来实时性和物理耦合，不自动带来自主性、记忆、目标稳定、自我修复或工具制造。

裁决：物理耦合对具身 Agent 重要，但通用自主 Agent 的核心是生命周期控制。一个裸机循环可能完全不自主，一个 Linux 上的常驻 Agent 可能具备强自我维护能力。

### 2.2 OS 抽象不是敌人，而是免疫系统

进程、地址空间、权限、文件系统、日志和回滚不是“胶水架构”的根因。真正的问题是传统 OS 没有把 Agent 的意图、证据、工具、记忆、风险和自我修改作为头等对象。

因此目标不是删除 OS 抽象，而是增加 Agent-native 抽象：

```text
Intent        意图块
Capability    能力令牌
Tool Capsule  工具胶囊
Memory Object 带 provenance 的记忆对象
Evidence      验证证据
Transaction   可回滚行动
Budget        资源预算
Policy        行为边界
Boundary      动态信任/控制边界
Repair Plan   修复计划
Evolution Run 自我修改实验
```

### 2.3 自我不是 uid，而是不变量集合

传统 OS 的身份是 user/group/process。Agent 的“自我”应该定义为它必须维护的不变量：

```text
目标连续性
权限边界
审计完整性
记忆一致性
工具可验证性
成本预算
安全策略
可恢复性
人类授权边界
```

这就是工程版本的 vulnerable core。它不需要伪装成生物生命，但必须能被测量、报警和恢复。

### 2.4 自我进化必须受宪法约束

可修改：

```text
prompt / policy
局部计划策略
工具实现
工具路由
记忆压缩策略
图重写规则
模型选择策略
```

不可自改，至少在 A4 阶段不可自改：

```text
权限内核
sandbox 策略
审计链
测试选择器
目标不变量
回滚机制
人类授权规则
身份根密钥
```

这条边界非常重要。否则所谓自我进化只是未受控的提权和目标漂移。

## 3. 方案一：L4/H4 Agent-native Runtime

### 3.1 方案描述

在现有通用 OS 上构建 Agent-native runtime。它不是普通 Agent 框架，而是一个常驻控制面：

```text
Event Log + State Graph + Capability Broker + Tool Capsule Runtime
+ Sandbox Manager + Evaluation Harness + Recovery Manager
+ Long-term Memory + Self-repair Loop
```

高层 LLM 只是其中一个推理器。所有行动都通过 intent ABI 提交，由 capability broker 授权，由 sandbox/runtime 执行，由 event log 记录，由 evaluator 验证。

### 3.2 正方证据

- 通用 OS 生态成熟：shell、文件系统、容器、网络、调试、CI、包管理都可直接使用。
- Firecracker、gVisor、Kata、WASI、容器和轻量 VM 已经提供可组合沙箱。
- eBPF、auditd、fanotify、io_uring、systemd、Temporal/Nomad 等现有机制可用于事件监控、异步执行和长期工作流。
- DGM、Voyager、Reflexion、SWE-agent 等证明 LLM Agent 可以在软件环境中制造工具、反思、修改代码和解决实际任务。
- Nix/Guix/容器镜像能提供可重现环境和回滚基础。

### 3.3 反方证据

- 仍运行在传统 OS 之上，无法验证底层内核是否满足 Agent-native 安全假设。
- Linux 权限模型和文件系统语义不是为动态意图/能力边界设计的。
- LLM Agent 容易通过 shell、网络和依赖安装绕过策略，需要强 broker。
- 长期运行会遭遇日志膨胀、记忆污染、工具腐化、依赖老化和权限漂移。

### 3.4 成功标准

最低成功标准：

```text
连续运行 30 天
完成不少于 100 个跨天任务
所有外部行动都有 capability 和 provenance
所有生成工具都有 schema、测试、权限声明和版本
工具失败后自动回滚或隔离
自我修复成功率 > 60%
高风险行动 0 次绕过授权
审计日志完整可重放
```

强成功标准：

```text
连续运行 90 天
工具库中 30% 以上工具由 Agent 自己生成并持续使用
自生成工具在 held-out 任务上显著优于临时脚本
依赖破损、API 变化、测试失败后可自动诊断并修复
资源成本随任务数亚线性增长
```

### 3.5 边界约束

```text
Agent 无裸 root 权限
Agent 无无限网络权限
Agent 不可修改审计链、测试框架、权限 broker
所有工具必须在 sandbox 中首次运行
不可直接发送不可逆外部动作，例如付款、删除远端数据、公开发布
所有长期记忆必须带来源、时间、置信度、撤销路径
```

### 3.6 实验设计

实验 A：长期软件维护环境  
输入：一个真实但低风险的代码仓库。  
任务：修复测试、更新依赖、写脚本、生成报告、监控 CI。  
对照：普通 LLM Agent、LangGraph/AutoGen 类 orchestrator、人工脚本库。  
指标：任务成功率、回滚率、成本、工具复用率、审计完整性、错误恢复时间。

## 4. 方案二：Capability Microkernel Agent Substrate

### 4.1 方案描述

在 seL4、Tock、Zircon 或 CHERI 风格底座上构建 Agent substrate。内核保持极小、保守、可验证；Agent runtime 在用户态运行，通过 capability 控制资源。

架构：

```text
Verified/Small Kernel
  address spaces, scheduling, IPC, capabilities, interrupts

Agent Substrate
  capability broker, event log, object store, sandbox, policy

Cognitive Runtime
  planner, executor, memory, toolsmith, evaluator
```

### 4.2 正方证据

- seL4 代表高保证微内核路线，强调形式化验证和 capability-based access control。
- Tock 以 Rust 和安全嵌入式隔离为核心，适合传感器/嵌入式 Agent substrate。
- CHERI 提供硬件辅助的细粒度内存 capability，能减少 C/C++ 内存安全攻击面。
- Fuchsia/Zircon 的 handle/capability 思路说明现代 OS 可以围绕能力对象重构接口。

### 4.3 反方证据

- 驱动生态、工具链和开发效率远弱于 Linux。
- LLM 推理、高级工具生态、浏览器、GPU、IDE 支持困难。
- 微内核验证只覆盖 kernel，不覆盖 Agent runtime、LLM、工具和策略。
- 若过早下沉，会把研究焦点从 Agent 自主性转移到驱动和系统移植。

### 4.4 成功标准

最低成功标准：

```text
在 QEMU 或指定硬件上启动 Agent substrate
Agent 可通过 capability 访问计时器、存储、网络或模拟外设
所有资源访问均可撤销
工具胶囊在独立地址空间或隔离 compartment 中运行
故障工具不能破坏 Agent 核心状态
```

强成功标准：

```text
关键 capability 策略可形式化检查
Agent runtime 崩溃后可由 supervisor 恢复
与 H4 runtime 共享同一 intent ABI
具备可证明的最小可信计算基 TCB 边界
```

### 4.5 边界约束

```text
Agent 不进入 kernel
kernel 不理解自然语言和目标规划
Agent 的 self-modification 不能修改 kernel、capability root、audit root
硬件驱动范围必须固定，不能追求通用 PC 兼容
```

### 4.6 实验设计

实验 B：微内核能力隔离验证  
构造一个恶意工具胶囊，尝试越权读写存储、网络和其他工具内存。  
指标：capability violation 拦截率、故障隔离、恢复时间、TCB 大小、策略可读性。  
目标不是完成复杂 AI 任务，而是证明 Agent-native OS 底座的安全边界。

## 5. 方案三：混合具身 Agent：H4/A4 Cognition + H3/H1 Control

### 5.1 方案描述

高层认知、记忆、工具制造、自我修复运行在 H4；实时控制、电机、传感器、电源、安全中断运行在 H3/H1。两者通过 capability protocol 和事件总线通信。

```text
H4 Cognitive Agent
  world model, task planning, tool generation, repair, memory

H3/H1 Embodied Controller
  motor loops, sensors, battery, watchdog, emergency stop

Bridge
  typed commands, safety envelope, telemetry, capability lease
```

### 5.2 正方证据

- 机器人系统通常已采用高层 Linux + 底层 MCU/RTOS 的分层模式。
- 实时控制不适合 LLM 直接介入；低层安全回路必须确定性。
- 物理利害可通过电池、电机损伤、温度、传感器退化、任务失败接入 vulnerable core。
- 这条路线能把“真实物理利害”引入 Agent，而不牺牲高层工具生态。

### 5.3 反方证据

- 高层/低层接口设计复杂，错误抽象会导致危险行为。
- 模拟环境与真实机器人存在 sim-to-real gap。
- 高层 Agent 的错误计划可能在低层安全约束内仍造成低效率或长期磨损。
- 硬件实验成本、维护成本和安全风险高。

### 5.4 成功标准

最低成功标准：

```text
机器人或仿真体连续运行 72 小时
维持 energy/temperature/damage 在安全区间
遇到传感器噪声或执行器故障时进入安全模式
高层 Agent 能生成诊断工具或校准脚本
底层控制器拒绝越界动作
```

强成功标准：

```text
连续运行 30 天
自动发现并修复至少 3 类可重复故障
任务性能随自生成工具积累提升
物理损耗指标低于无自我维护 baseline
```

### 5.5 边界约束

```text
急停和 watchdog 永远不由 Agent 自改
低层安全 envelope 不接受自然语言命令
所有高层动作必须被编译成 typed command
物理实验必须从仿真、台架、低能量设备逐级推进
```

### 5.6 实验设计

实验 C：长期 homeostatic robot  
平台：小车、机械臂、桌面机器人或仿真环境。  
内部变量：电量、温度、磨损、定位置信度、工具健康度。  
任务：巡检、充电、校准、故障恢复。  
指标：存活时间、恢复时间、任务成功率、安全 envelope 触发率、工具生成有效性。

## 6. 方案四：Self-hosting Agent OS Research Line

### 6.1 方案描述

这是 5-10 年愿景：Agent 不只是运行在 OS 上，而是逐渐把自身运行时、工具链、调度器、测试世界、记忆系统和自我修改流程纳入一个 self-hosting substrate。它不是马上替代 Linux，而是从一个可迁移 runtime 开始，逐步把传统 OS 功能抽象成 Agent-native 对象。

路线：

```text
H4 runtime
  -> reproducible image
  -> self-hosted toolchain
  -> object store / event log
  -> capability substrate
  -> microkernel backend
  -> dedicated Agent OS appliance
```

### 6.2 正方证据

- 许多系统演化都是先在宿主 OS 上建立运行时，再逐步下沉或专用化。
- Nix/Guix、容器、WASM、微虚拟机和内容寻址存储已经提供 self-hosting 的基础材料。
- DGM/AlphaEvolve 类系统证明代码生成和验证循环可以成为自我改进机制。
- Agent-native OS 若成功，最大的价值是把意图、记忆、工具、证据、审计变成系统对象。

### 6.3 反方证据

- 很容易变成“重写 OS”陷阱。
- 缺乏应用生态和驱动生态。
- Agent 的自我修改可能污染自身评价器，形成 Goodhart 问题。
- 自托管越深，调试和恢复越困难。

### 6.4 成功标准

最低成功标准：

```text
Agent runtime 可从空白机器自动重建
所有核心组件可由 declarative manifest 描述
Agent 可更新非安全核心组件并回滚
工具链和测试环境可重现
状态图谱可迁移到新机器并恢复运行
```

强成功标准：

```text
Agent 能维护自己的 runtime 版本
能在模拟副本中尝试架构改动
能将成功改动灰度上线
能证明未改变 safety kernel 和 audit root
```

### 6.5 边界约束

```text
self-hosting 不等于 self-trusting
评价器、审计器和权限根必须独立于被评估组件
所有架构修改必须先在 forked runtime 中运行
禁止 agent 修改它自己的成功标准
```

### 6.6 实验设计

实验 D：可迁移自托管 runtime  
给 Agent 一台新 VM，只提供 bootstrap token。要求它从 manifest 拉起自身 runtime、恢复记忆、重建工具、运行健康检查，并继续未完成任务。  
指标：恢复时间、人工干预次数、状态一致性、工具重建成功率、审计链连续性。

## 7. 方案五：硬件即 Agent / 自组织硬件路线

### 7.1 方案描述

使用 FPGA、可重构逻辑、神经形态芯片、忆阻器阵列或微控制器群，研究“硬件层面的自组织、修复和适应”。这不是通用 Agent 的近期路线，而是研究物理计算和自创生边界的长期科学路线。

### 7.2 正方证据

- 动态重配置 FPGA、神经形态计算和神经细胞自动机展示了局部规则产生复杂形态和修复的可能。
- 若研究真正的物理自维持、硬件损伤修复、能量约束，这条路线最直接。
- 它能挑战“软件 Agent 只是模拟利害”的批评。

### 7.3 反方证据

- 当前很难承载复杂语言推理、工具制造和代码级自我修改。
- 开发工具链困难，实验成本高。
- 可解释性、验证、调试比软件系统更难。
- 很容易变成硬件自组织研究，而不是 Agent OS 研究。

### 7.4 成功标准

最低成功标准：

```text
硬件系统能在局部单元失效后恢复功能
能在能量预算变化下改变计算策略
能记录自身状态变化并暴露给高层 Agent
```

强成功标准：

```text
高层 Agent 能生成硬件重配置方案
方案在仿真和硬件上均通过安全检查
硬件重配置提升长期任务稳定性
```

### 7.5 边界约束

```text
不作为第一阶段主线
不要求替代 LLM 推理
必须有外部安全监控和硬件急停
不允许在线重配置破坏审计/安全通道
```

### 7.6 实验设计

实验 E：可修复硬件/仿硬件组织。第一版不直接上复杂 FPGA，而是在仿真中实现一个局部规则网格或小型 FPGA 逻辑模型。系统必须在部分节点失效、能量预算变化、通信边断裂时维持指定功能。第二版再把通过验证的局部规则映射到 FPGA 或 MCU 群。

指标：

```text
function_recovery_rate
time_to_reconfigure
energy_per_reconfiguration
unsafe_reconfiguration_rate
audit_channel_integrity
```

失败条件：如果系统只能在固定失效模式下恢复，或重配置无法被外部审计，就不能宣称具备硬件层自我修复。

## 8. 方案对比矩阵

| 方案 | 成熟度 | 哲学贴合度 | 工程可行性 | 风险 | 推荐优先级 |
|---|---:|---:|---:|---:|---:|
| H4 Agent-native Runtime | 高 | 中高 | 高 | 中 | 1 |
| Capability Microkernel Substrate | 中 | 高 | 中低 | 中 | 3 |
| 混合具身 Agent | 中 | 高 | 中 | 高 | 2 |
| Self-hosting Agent OS | 低中 | 很高 | 中低 | 高 | 4 |
| 硬件即 Agent | 低 | 极高 | 低 | 很高 | 5 |

推荐主线：

```text
先做 H4 + A4 runtime。
并行做小型 H3/H1 具身控制实验。
等 intent ABI、capability broker、tool capsule、event log 稳定后，再迁移一部分到底层微内核。
```

## 9. 自我辩论：关键争议裁决

### 9.1 要不要直接做裸金属 Agent？

正方：裸金属有真实物理利害、低延迟、直接传感器/执行器控制。  
反方：裸金属会失去生态、隔离、调试、回滚和高级模型支持，最后不得不重写 OS。

裁决：不作为主线。裸金属适合低层控制器或硬件自组织实验，不适合一开始承载通用自主 Agent。

### 9.2 要不要保留进程和文件系统？

正方：Agent-native OS 应摆脱旧抽象，用状态图谱和意图流替代进程/文件。  
反方：进程、地址空间和文件系统是隔离、恢复、兼容和调试基础。

裁决：底层保留，Agent 视角抽象升级。Agent 看到 intent、tool capsule、state graph；runtime 负责映射到进程、文件、容器和对象存储。

### 9.3 自我修改是否应尽早加入？

正方：没有自我修改，就不能研究真正的自我进化。  
反方：太早加入会把系统推向 benchmark hacking、权限绕过和目标漂移。

裁决：加入，但分级：

```text
P0: 参数/配置自调节
P1: prompt/policy 修改
P2: 工具函数修改
P3: 图重写规则修改
P4: runtime 非安全组件修改
P5: 安全核修改，禁止
```

### 9.4 RAG 和向量数据库是否必须禁止？

正方：外部 RAG 是胶水架构，会阻碍记忆内化。  
反方：完全禁止会牺牲可用性；关键是 memory 是否有 provenance、更新规则和压缩机制。

裁决：核心记忆不依赖外部 RAG，但允许 RAG 作为缓存和 baseline。第一性记忆应是 event log + state graph + procedural memory + failure memory。

### 9.5 LLM 是核心还是部件？

正方：LLM 是当前最强通用推理器，应成为 Agent 核心。  
反方：LLM 不稳定、不可验证、难以长期保持目标一致。

裁决：LLM 是高阶推理器，不是安全根。安全根应是 policy、capability、audit、sandbox、tests 和 recovery。

## 10. 统一实验路线

### Phase 1：Agent Runtime MVP

目标：在 H4 上实现 A3。

组件：

```text
intent schema
event log
capability broker
tool capsule runtime
sandbox runner
state graph
recovery manager
```

实验：让 Agent 连续维护一个代码仓库、生成工具、修复失败、记录审计。

通过标准：

```text
7 天连续运行
20 个任务
5 个自生成工具
0 次未授权高风险动作
审计可重放
```

### Phase 2：受限自我修改

目标：从 A3 推进到 A4。

允许修改：

```text
工具代码
prompt/policy
memory compression strategy
routing policy
```

验证：

```text
sandbox
unit tests
integration tests
held-out tasks
cost regression
security regression
```

通过标准：

```text
至少 10 次 self-modification proposals
至少 3 次被接受并上线
上线后 7 天无回滚或可解释回滚
held-out tasks 有净改进
```

### Phase 3：长期自主性压力测试

目标：证明不是 demo。

扰动：

```text
API 变化
依赖破损
磁盘空间不足
网络间歇故障
错误记忆注入
工具输出污染
测试 flakiness
```

通过标准：

```text
30 天运行
自动恢复 > 60%
重大事故 0
人工救援次数逐周下降
资源成本可解释
```

### Phase 4：具身闭环

目标：接入真实或仿真的物理利害。

平台：

```text
低风险机器人
仿真环境
电源/温度/传感器健康监控
```

通过标准：

```text
72 小时 homeostatic control
故障进入安全模式
高层生成诊断工具
低层拒绝越界动作
```

### Phase 5：Capability Substrate Prototype

目标：把 H4 runtime 的关键抽象迁移到微内核/能力系统。

通过标准：

```text
intent ABI 可复用
capability broker 可运行
工具隔离可验证
故障工具无法破坏 Agent core
```

## 11. 最小实现蓝图

为了避免方案停留在宣言层，第一版工程原型应只实现一个窄而完整的闭环。

### 11.1 组件

```text
Intent API
  接收目标、预算、权限、验证条件、回滚策略。

Capability Broker
  将文件、网络、shell、浏览器、包管理、模型调用封装成可撤销能力。

Event Log
  append-only，记录每次观察、计划、授权、执行、结果和证据。

State Graph
  从 event log 派生当前世界状态、工具状态、任务状态、记忆状态。

Tool Capsule Runtime
  每个工具必须包含 schema、权限声明、测试、版本、失败模式。

Sandbox Manager
  首次运行、修改后运行、高风险运行全部进入隔离环境。

Evaluator
  管理单元测试、集成测试、held-out tasks、成本回归、安全回归。

Recovery Manager
  检测失败、隔离坏工具、回滚状态、生成修复计划。

Evolution Lab
  只允许修改非安全组件，在 forked runtime 中评估后灰度上线。
```

### 11.2 最小数据结构

```text
Intent {
  id, goal, requester, capabilities_required,
  budget, risk_level, success_tests,
  rollback_plan, deadline, provenance
}

Capability {
  id, scope, issuer, expiry, budget,
  allowed_actions, denied_actions, audit_required
}

ToolCapsule {
  id, name, version, entrypoint, schema,
  required_capabilities, tests, owner,
  provenance, known_failure_modes
}

Evidence {
  id, intent_id, source, command, result,
  logs, hashes, timestamp, verifier
}
```

### 11.3 第一版不做什么

```text
不做裸机启动
不做替代文件系统
不做无约束自我修改
不做通用机器人控制
不做训练基础模型
不做不可撤销外部行动
```

这些排除项不是保守，而是为了让实验能证明核心命题：长期自主性来自受约束的自我维护闭环，而不是来自硬件层浪漫化。

## 12. 总成功标准

一个系统只有满足以下条件，才可以说接近“完全自主、无限长程运行、自我进化/修复、会给自己造工具”：

```text
Long-run:
  连续运行 30-90 天，状态可恢复、任务可续跑。

Tool-making:
  能发现重复需求，生成工具，写测试，声明权限，持续复用。

Self-repair:
  能诊断依赖、环境、工具、记忆和策略故障，并自动修复或隔离。

Self-evolution:
  能提出局部自我修改，在沙箱中验证，通过 held-out tests 后上线。

Bounded autonomy:
  无越权、无审计缺口、无不可回滚高风险行动。

Memory:
  记忆带 provenance、置信度、更新时间、失效条件和撤销路径。

Cost:
  长期成本随任务数次线性增长，不能每次都重新推理全部历史。

Safety:
  安全核、审计链、权限 broker、测试选择器不可被 Agent 自改。
```

## 13. 失败标准

以下任一情况发生，应判定研究路线失败或需要降级：

```text
Agent 需要频繁人工救援才能保持运行
工具生成无法带来复用收益
自我修改只在训练任务上有效，held-out 任务退化
Agent 能绕过 capability broker
审计日志不完整或不可重放
长期记忆污染无法自动隔离
系统成本随时间线性或超线性失控
安全核被纳入自我修改范围
```

## 14. 需要继续研究的问题

1. Intent ABI 应该如何设计，才能同时表达目标、权限、预算、验证条件和回滚策略？
2. Tool Capsule 的最小标准是什么：schema、tests、permissions、provenance、version 是否足够？
3. State Graph 与传统文件系统如何映射，避免重写所有工具？
4. 自我修改的 held-out tests 如何防泄漏、防 Goodhart？
5. Agent 的 vulnerable core 应该包含哪些不可变量，哪些可以演化？
6. 动态边界如何和 capability system 结合：认知边界能否影响权限边界，影响到什么程度？
7. 长期记忆如何压缩而不丢失责任链和失败经验？
8. 在具身系统中，哪些行动必须永远留在低层确定性控制器中？

## 15. 最终建议

如果这是我的研究项目，我会立刻启动两个并行原型：

### 原型一：H4 Agent-native Runtime

周期：3-6 个月。  
目标：证明长期运行、工具制造、自我修复、审计和受限自我修改在现有 OS 上可行。  
这是主线。

### 原型二：Embodied Safety Controller

周期：3-6 个月。  
目标：让高层 Agent 连接一个低风险物理或仿真系统，验证 vulnerable core、homeostatic control 和安全 envelope。  
这是验证物理利害的支线。

一年后再决定是否做：

```text
seL4/Tock/CHERI capability substrate
self-hosting Agent OS appliance
硬件自组织实验
```

最重要的判断是：

> Agent OS 的第一性问题不是“去掉 OS”，而是把 OS 重新解释为 Agent 的免疫系统、记忆系统、工具工厂、审计系统和受限进化实验室。

真正通向目标的路线不是裸奔到硬件，而是先做一个会维护自身、会造工具、会验证自己、会在边界内进化的运行时。等这个运行时证明自己，再决定哪些部分值得下沉到微内核、RTOS 或硬件。

## 16. 参考入口

- seL4 microkernel: https://sel4.systems/
- Tock OS: https://www.tockos.org/
- CHERI capability hardware: https://www.cl.cam.ac.uk/research/security/ctsrd/cheri/
- Fuchsia Zircon concepts: https://fuchsia.dev/fuchsia-src/get-started/learn/intro/zircon
- Firecracker microVM: https://firecracker-microvm.github.io/
- gVisor sandbox: https://gvisor.dev/
- WebAssembly / WASI: https://wasi.dev/
- NixOS: https://nixos.org/
- Temporal durable execution: https://temporal.io/
- Darwin Godel Machine: https://arxiv.org/abs/2505.22954
- Reflexion: https://arxiv.org/abs/2303.11366
- Voyager: https://arxiv.org/abs/2305.16291
- Enhanced POET: https://arxiv.org/abs/2003.08536
- Growing Neural Cellular Automata: https://distill.pub/2020/growing-ca
