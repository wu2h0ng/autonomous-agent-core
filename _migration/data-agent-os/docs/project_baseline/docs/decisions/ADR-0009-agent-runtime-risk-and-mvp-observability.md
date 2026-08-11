# ADR-0009 Agent Runtime 自研风险与 MVP 可观测性边界

> 日期：2026-06-02
> 状态：Accepted
> 决策人：CTO

## 背景

外部评审反馈指出两个风险：

1. Agent Runtime 完全自研可能拖慢 MVP，建议短期封装 LangGraph。
2. 可观测性体系不够明确，建议 MVP 阶段即接入 OpenTelemetry，覆盖业务、质量、成本三维监控。

反馈指出的风险成立，但第一条给出的方案不能直接进入产品 Core。项目已经通过 ADR-0006 明确：Agent OS Core 必须自研，外部 Agent 框架不能成为产品运行时依赖。

## 决策

### 1. Agent Runtime 风险控制

产品 Core Runtime 继续自研，不引入 LangGraph、CrewAI、OpenAI Agents SDK 等作为生产依赖。

为了避免 MVP 被基础设施工作拖垮，采用以下控制策略：

| 风险 | 控制策略 |
|---|---|
| 自研 Runtime 复杂度过高 | 只实现最小状态机、ToolRegistry、结构化输出校验、失败重试和 TraceWriter。 |
| 成熟框架能力差距 | 允许 LangGraph 等做非生产 spike / benchmark / 对照样本。 |
| MVP 延期 | 优先收窄 Agent 自动化范围，而不是引入外部框架接管 Core。 |
| 设计闭门造车 | 把 spike 结果沉淀为自研接口、测试用例和质量门禁，不沉淀为运行时依赖。 |

LangGraph 可以研究，但不得出现在：

```text
ai-native-business-data-agent-os/packages/os_core/
ai-native-business-data-agent-os/packages/contracts/
ai-native-business-data-agent-os/apps/api_server/
product runtime dependency list
```

### 2. MVP 可观测性边界

MVP 必须具备 OpenTelemetry-compatible 的轻量可观测性边界，但不要求一开始部署完整 Grafana / Collector / APM 平台。

第一阶段必须输出四类 Telemetry：

| 维度 | MVP 指标示例 |
|---|---|
| 业务 | Trusted Loop 启动次数、EvidenceChain 生成数、ActionProposal 生成数 |
| 质量 | SQL Safety 通过率、EvidenceChain 完整率、Eval 通过率 |
| 成本 | 模型调用次数、token 数、估算成本；无模型调用时记录 0 成本原因 |
| 系统 | Trusted Loop 延迟、查询返回行数、API 错误率 |

当前实现采用：

```text
TraceEvent: 用于回放执行步骤
TelemetryEvent: 用于业务/质量/成本/系统指标
```

后续接入 OpenTelemetry 时，`TelemetryEvent` 映射为 meter/counter/histogram，`TraceEvent` 映射为 span/event。

## 影响

1. ADR-0006 继续有效。
2. CTO-APPROVAL-20260601 中“第一阶段只用应用内 Trace”的表述修正为：第一阶段使用应用内 Trace + OpenTelemetry-compatible TelemetryEvent，不强制部署完整 OTel 平台。
3. 任何 Agent 不得以“避免拖慢 MVP”为理由把外部 Agent runtime 引入产品 Core。
4. 新增 Trusted Loop 能力时，必须同时考虑 trace 和 telemetry。

## 验收标准

1. 产品代码中不得 import LangGraph。
2. Trusted Loop 结果必须输出 trace events。
3. Trusted Loop 结果必须输出 business、quality、cost、system 四类 telemetry events。
4. 成本指标不得记录密钥、token、cookie、完整 prompt 或敏感业务 payload。
5. 后续如接入 OpenTelemetry exporter，必须保持可选依赖，不能阻塞本地最小闭环运行。
