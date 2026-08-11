# AI Native Business Data OS 知识资产、组织权限与部署架构

> 日期：2026-05-31
> 定位：补充 `AI Native Business Data OS 技术 PRD 与架构设计`，把数据记忆、业务记忆、操作反馈沉淀为企业知识资产，并定义组织架构、权限体系、用户角色、私有化和云部署的产品架构。

---

## 1. 核心判断

AI Native Business Data OS 的长期价值不只是让 Agent 完成一次分析或一次业务动作，而是持续沉淀企业自己的知识资产：

```text
Data Memory
  + Business Memory
  + Operation Trace
  + Human Decision
  + Feedback Outcome
  -> Enterprise Knowledge Asset
```

这些资产必须绑定企业组织架构、角色权限、数据边界、审批责任和部署边界。否则系统会出现三个问题：

1. Agent 每次都重新理解业务，不能越用越懂企业。
2. 企业无法控制“谁能看、谁能问、谁能批准、谁能执行”。
3. 私有化和云部署只是基础设施选项，无法成为可信产品能力。

正确方向是把知识资产、身份权限和部署架构做成 OS Core 的一等能力，而不是项目交付时临时补丁。

---

## 2. 企业知识资产层

### 2.1 知识资产类型

| 资产类型 | 来源 | 用途 |
|---|---|---|
| Semantic Asset | 指标、实体、维度、术语、口径、别名 | 让 Agent 稳定理解业务语言 |
| Data Product Asset | DataProduct、SQL、转换、质量契约、血缘 | 可复用数据产品和可验证分析 |
| Evidence Asset | EvidenceChain、数据快照、查询、限制、置信度 | 结论可信和审计追踪 |
| Business Memory Asset | 业务规则、经验、异常案例、策略偏好 | 让 Agent 理解企业自己的经营方式 |
| Operation Asset | ActionPlan、OperationContract、OperationTrace | 业务动作可审批、可追溯、可复盘 |
| Decision Asset | 人工审批、否决、修改、理由、责任人 | 沉淀组织决策知识 |
| Feedback Asset | 执行结果、指标变化、复盘结论 | 形成闭环学习和评测样本 |
| Workflow Asset | 审批路径、处理流程、SOP、异常处置 | 让业务流程可复用 |
| Eval Asset | golden intent、golden query、风险样本、回归集 | 保证模型和 Agent 升级不退化 |

知识资产不是普通文档库，也不是简单 RAG。它必须有结构、版本、owner、权限、证据、生命周期和评测。

### 2.2 KnowledgeAsset 模型

```json
{
  "asset_id": "ka_001",
  "asset_type": "business_memory",
  "tenant_id": "tenant_001",
  "workspace_id": "sales_ops",
  "title": "大客户续约风险判断规则",
  "content": {},
  "source_refs": [
    "evidence_chain:ev_001",
    "operation_trace:op_001",
    "decision:approval_001"
  ],
  "owner": {
    "type": "user",
    "id": "u_001"
  },
  "steward": {
    "type": "role",
    "id": "data_steward"
  },
  "classification": "internal_sensitive",
  "access_policy_id": "policy_knowledge_sales_ops",
  "validity": {
    "effective_from": "2026-06-01",
    "review_after_days": 90
  },
  "version": 3,
  "status": "published",
  "quality_score": 0.86,
  "eval_bindings": ["eval_renewal_risk_001"]
}
```

### 2.3 知识资产生命周期

```text
capture
  -> normalize
  -> classify
  -> link evidence
  -> assign owner/steward
  -> review
  -> publish
  -> use in agent runtime
  -> observe feedback
  -> update or retire
```

关键规则：

- 未审核知识只能作为候选，不进入高风险业务动作。
- 业务规则类知识必须有业务 owner。
- 指标口径类知识必须有数据 steward。
- 高影响知识更新必须触发相关 eval regression。
- 被多次使用的知识资产需要质量分和过期复审。
- 被否决或证明错误的知识不得静默删除，要保留审计记录。

### 2.4 从记忆到知识资产的分层

| 层级 | 特征 | 是否可驱动业务动作 |
|---|---|---|
| Raw Memory | 对话、日志、工具输出、执行记录 | 否 |
| Candidate Knowledge | Agent 提取出的规则、经验、偏好 | 否 |
| Reviewed Knowledge | 经过 owner/steward 审核 | 可用于建议 |
| Published Knowledge Asset | 有版本、权限、证据、评测绑定 | 可用于受控业务动作 |
| Certified Knowledge Asset | 经过持续评测和生产验证 | 可用于自动化或低风险自动执行 |

---

## 3. 知识图谱与语义记忆

### 3.1 不是只做向量库

向量库适合召回文本片段，但企业知识资产需要图结构和契约结构：

```text
Customer
  -> owns Account
  -> has Contract
  -> has RenewalRisk
  -> affected_by Ticket
  -> managed_by SalesOwner
  -> governed_by AccessPolicy
  -> can_trigger RetentionWorkflow
```

建议组合：

| 存储 | 用途 |
|---|---|
| PostgreSQL JSONB | 契约、版本、权限、审计、资产元数据 |
| pgvector / 向量库 | 语义召回、案例检索、文档片段 |
| Graph model | 组织、实体、关系、权限、流程、因果假设 |
| Object Store | 原始文件、报告、截图、证据快照 |
| Search index | 关键词、过滤、权限感知搜索 |

初期可以用 PostgreSQL + JSONB + pgvector 表达图关系，后续再引入独立图数据库。

### 3.2 Knowledge Graph 边类型

| 边 | 含义 |
|---|---|
| `derived_from` | 知识来自某证据或数据产品 |
| `used_by` | 被某 Agent、Workflow、Action 使用 |
| `approved_by` | 被某人或角色审核 |
| `owned_by` | 业务 owner |
| `stewarded_by` | 数据 steward |
| `applies_to` | 适用业务对象、部门或场景 |
| `conflicts_with` | 与另一规则或口径冲突 |
| `supersedes` | 新版本替代旧版本 |
| `requires_policy` | 使用时需要特定策略 |
| `validated_by` | 被评测集或生产反馈验证 |

### 3.3 Agent 使用知识资产的规则

Agent 不能无差别读取全部知识。使用知识必须遵守：

1. 先按租户、workspace、组织、角色、数据域过滤。
2. 再按任务目的、风险等级、时间有效性过滤。
3. 只能使用 `published` 或更高状态的知识驱动业务动作。
4. 低质量、过期、冲突知识只能作为提示，不作为决策依据。
5. 每次使用知识资产都要写入 `KnowledgeUseTrace`。

---

## 4. 组织架构模型

### 4.1 组织对象

```text
Tenant
  -> Organization
  -> Business Unit
  -> Department
  -> Team
  -> Workspace
  -> Project
  -> User / Group / Service Account
```

### 4.2 OrgUnit 模型

```json
{
  "org_unit_id": "dept_sales_east",
  "tenant_id": "tenant_001",
  "type": "department",
  "name": "华东销售部",
  "parent_id": "bu_sales",
  "manager_user_id": "u_manager_001",
  "cost_center": "CC-SALES-EAST",
  "data_domains": ["sales", "customer", "contract"],
  "default_workspace_ids": ["sales_ops"],
  "approval_policy_id": "approval_sales_east"
}
```

组织架构不是通讯录附属功能，而是权限、审批、数据范围、成本归属、知识 owner、操作责任的共同基础。

### 4.3 与客户身份系统集成

| 集成 | 用途 |
|---|---|
| OIDC/SAML | SSO 登录和身份联合 |
| SCIM | 用户、组、组织变更同步 |
| LDAP/AD | 私有化客户目录同步 |
| 企业微信/飞书/钉钉 | 组织、审批、通知、待办 |
| IAM Role Mapping | 客户角色映射到 OS 角色 |
| Service Account | Connector、Workflow、MCP Server 的非人身份 |

必须支持：

- 多租户。
- 多组织。
- 多 workspace。
- 用户跨部门兼职。
- 临时授权。
- 离职/转岗权限回收。
- 服务账号和机器身份。
- 组织变更后的知识 owner 迁移。

---

## 5. 权限体系

### 5.1 权限模型组合

单一 RBAC 不够，建议组合：

| 模型 | 用途 |
|---|---|
| RBAC | 角色权限，如 Admin、Data Steward、Business Owner |
| ABAC | 按属性控制，如部门、地区、数据分类、时间 |
| ReBAC | 按关系控制，如客户归属、项目成员、审批链 |
| PBAC | 按策略控制，如高风险动作必须双人复核 |
| Purpose-based Access | 按使用目的控制，如分析、审计、执行、训练 |

### 5.2 标准角色

| 角色 | 权限范围 |
|---|---|
| Tenant Admin | 租户配置、身份、部署、全局策略 |
| Security Admin | DLP、密钥、审计、风险策略 |
| Data Steward | 指标、语义、数据质量、数据产品审核 |
| Business Owner | 业务规则、行动策略、审批责任 |
| Domain Pack Owner | 行业包/部门包维护 |
| Connector Admin | Provider、Action Connector、MCP Server 注册 |
| Model Admin | BYO Key、本地模型、路由和预算 |
| Workflow Admin | 工作流桥接、回调、审批路径 |
| Analyst | 创建数据产品、解释分析、管理问题集 |
| Business User | 发起业务意图、查看授权结果、处理任务 |
| Approver | 审批业务动作 |
| Auditor | 查看审计、证据链、操作记录 |
| Service Account | 自动化系统调用 |

### 5.3 资源权限矩阵

| 资源 | 读 | 写/编辑 | 执行 | 审批 | 管理 |
|---|---|---|---|---|---|
| DataProduct | 按数据域和 workspace | Data Steward/Analyst | Agent runtime | 不适用 | Data Steward |
| EvidenceChain | 与来源数据同权限 | 系统写入 | Agent 可引用 | 不适用 | Auditor/Admin |
| KnowledgeAsset | 按分类和组织 | Owner/Steward | Agent 按策略使用 | Owner/Steward | Knowledge Admin |
| BusinessAgent | 按 workspace | Domain Owner | Business User/Workflow | Business Owner | Admin |
| OperationContract | 按 domain | Connector/Admin | ActionRuntime | Security/Business Owner | Admin |
| OperationTrace | 相关 owner/auditor | 系统写入 | 不适用 | 不适用 | Auditor |
| MCP Server | 按 registry scope | Connector Admin | Agent/ToolRuntime | 高风险工具需审批 | Admin |
| Model Key | 不可读明文 | Model Admin | ModelGateway | Security | Admin |

### 5.4 数据和知识权限继承

```text
Tenant policy
  -> Organization policy
  -> Workspace policy
  -> Data domain policy
  -> Asset policy
  -> Runtime context policy
```

运行时必须同时检查：

- 用户是谁。
- 用户属于哪个组织、角色、项目。
- 访问目的是什么。
- 访问的数据/知识分类是什么。
- 是否跨部门、跨地区、跨租户。
- 是否用于模型调用、业务动作、训练或导出。
- 是否需要审批或脱敏。

### 5.5 审批和职责分离

高风险场景必须支持：

- manager approval。
- data steward approval。
- business owner approval。
- security approval。
- dual control。
- segregation of duties。
- delegated approver。
- break-glass emergency access。

示例：

```text
预算调整 > 5%
  -> Marketing Owner approval
预算调整 > 20% 或金额 > 10000
  -> Marketing Owner + Finance approval
涉及客户敏感数据导出
  -> Data Steward + Security approval
不可回滚动作
  -> Business Owner + Auditor notification
```

---

## 6. 知识资产与权限的运行时链路

```text
User Intent
  -> IdentityContext
  -> OrgContext
  -> PurposeContext
  -> PolicyEngine
  -> KnowledgeAsset retrieval
  -> DataProduct compilation
  -> EvidenceChain
  -> BusinessAgent plan
  -> ApprovalRoute
  -> OperationTrace
  -> FeedbackAsset
```

关键对象：

| 对象 | 说明 |
|---|---|
| IdentityContext | 用户、角色、组、服务账号 |
| OrgContext | 部门、团队、上级、成本中心、审批链 |
| PurposeContext | 分析、审计、执行、训练、导出 |
| AccessDecision | 允许、拒绝、脱敏、需审批、只读 |
| KnowledgeUseTrace | 哪个 Agent 在什么目的下使用了哪个知识资产 |
| ApprovalRoute | 根据组织和风险生成审批路径 |
| FeedbackAsset | 执行结果沉淀为知识候选 |

---

## 7. 私有化与云部署架构

### 7.1 部署形态

| 部署形态 | 控制面 | 数据面 | 适用场景 |
|---|---|---|---|
| Public SaaS | 我方云 | 我方云或客户 API | 中小企业、低敏数据 |
| Dedicated SaaS | 我方云独立租户 | 我方云独立资源 | 中大型企业、隔离要求较高 |
| Hybrid SaaS | 我方云 | 客户 Connector 在内网 | 企业内网系统多、不开放入站 |
| Customer VPC | 客户云 VPC | 客户云 VPC | 数据不出云账号 |
| On-prem Private | 客户机房 | 客户机房 | 强合规、内网系统 |
| Air-gapped | 离线环境 | 离线环境 | 政企、金融高敏 |
| Edge/Local Bridge | 本地轻量代理 | 本地文件/浏览器/桌面 | 个人工作站和部门工具 |

### 7.2 控制面/数据面分离

```text
Control Plane:
  tenant config
  identity mapping
  policy
  metadata
  contract registry
  billing/quota
  marketplace

Data Plane:
  data query
  file processing
  model invocation
  connector execution
  action execution
  evidence storage
```

部署策略：

- SaaS 可以由我方托管控制面和数据面。
- Hybrid 由我方托管控制面，客户侧运行数据面 Connector。
- Private/VPC 由客户托管控制面和数据面。
- Air-gapped 需要离线控制面、离线许可证、离线模型和离线升级包。

### 7.3 部署 Profile

```json
{
  "deployment_profile": "hybrid_saas",
  "control_plane": "business_data_os_cloud",
  "data_plane": "customer_network_connector",
  "identity": "customer_oidc",
  "secret_store": "customer_vault",
  "model_mode": "byo_key_or_private_model",
  "data_residency": "customer_region",
  "audit_sink": "customer_siem",
  "upgrade_mode": "managed_with_customer_window"
}
```

### 7.4 云部署要求

云部署必须具备：

- tenant isolation。
- per-tenant encryption key。
- region selection。
- data residency policy。
- quota and budget。
- audit export。
- backup and restore。
- deployment health check。
- model provider allowlist。
- connector allowlist。

### 7.5 私有化部署要求

私有化必须具备：

- Helm chart / Docker Compose / 离线镜像。
- 私有对象存储适配。
- 私有数据库适配。
- 私有模型服务适配。
- 客户 IAM/Vault/SIEM 集成。
- license server 或离线 license。
- 灾备和备份策略。
- 升级前 compatibility check。
- 安全基线扫描。
- 运维 runbook。

### 7.6 Air-gapped 要求

Air-gapped 不是“不能联网的普通私有化”，它需要：

- 离线模型包。
- 离线 embedding/rerank。
- 离线文档解析。
- 离线 license。
- 离线 vulnerability database snapshot。
- 离线 eval pack。
- 离线升级包签名验证。
- 审计日志离线导出。

---

## 8. Monorepo 新增模块建议

```text
business_data_os/
  knowledge_assets/
    asset_registry/
    knowledge_graph/
    memory_extractor/
    review_workflow/
    knowledge_use_trace/
  org_identity/
    tenant_model/
    org_sync/
    role_mapping/
    access_policy/
    approval_route/
  deployment_profiles/
    saas/
    hybrid/
    customer_vpc/
    on_prem/
    air_gapped/
  data_boundary/
    classification/
    purpose_access/
    masking/
    residency/
```

与现有模块关系：

- `semantic_runtime/` 负责语义理解，`knowledge_assets/` 负责资产化、版本和治理。
- `policy_engine/` 执行策略，`org_identity/` 提供组织和身份上下文。
- `operation_trace/` 记录操作，`knowledge_assets/` 提取可复用经验和反馈。
- `network_plane/` 提供连接，`deployment_profiles/` 定义部署拓扑和运维基线。

---

## 9. 产品能力清单

MVP 阶段至少需要：

1. Tenant / Workspace / User / Group / Role 基础模型。
2. OIDC 登录和角色映射。
3. KnowledgeAsset registry。
4. EvidenceChain 到 KnowledgeAsset 的候选提取。
5. 人工 review/publish 流程。
6. 知识资产权限和版本。
7. Agent 使用知识资产的 trace。
8. SaaS 和 Hybrid deployment profile。
9. Connector Agent 基础部署。
10. Audit export。

企业试点阶段需要：

1. SCIM/LDAP/企业 IM 组织同步。
2. RBAC + ABAC + ReBAC 组合策略。
3. 数据分类和目的访问控制。
4. 审批路径自动路由。
5. Knowledge graph 关系和冲突检测。
6. 私有化部署模板。
7. 客户 Vault/SIEM/IAM 集成。
8. 灾备、备份、升级 runbook。

平台阶段需要：

1. 知识资产 marketplace / sharing。
2. Domain Pack 内置知识资产模板。
3. 跨部门知识复用和权限隔离。
4. 多部署形态统一运维。
5. KnowledgeAsset eval score。
6. 知识资产生命周期自动治理。

---

## 10. 决策检查清单

新增功能进入设计前必须回答：

1. 它产生的数据或记忆是否应该沉淀为 KnowledgeAsset？
2. 这个知识资产的 owner、steward、classification 是谁？
3. 哪些组织、角色、目的可以使用它？
4. 它是否能驱动 Business Agent 动作？
5. 如果能驱动动作，是否需要更高审核等级？
6. 它是否有版本、过期时间和评测绑定？
7. 它是否会跨部门或跨租户传播？
8. 它在 SaaS、Hybrid、Private、Air-gapped 部署下的数据边界是什么？
9. 组织架构变化时，它的 owner 和权限如何迁移？
10. 它被证明错误时如何撤回、禁用和追踪影响？
