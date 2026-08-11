# AI Native Business Data OS — 工程实现完全方案

> 版本：v1.0 | 日期：2026-06-01
> 性质：工程技术选型、架构设计、功能规格、实施路线的完整参考文档
> 受众：CTO、架构师、后端/前端/AI工程师、数据工程师

---

## 一、技术栈选型（带决策理由）

### 1.1 后端核心

| 组件 | 选型 | 版本 | 决策理由 | 替代选项 |
|---|---|---|---|---|
| 语言 | Python | 3.11+ | AI/ML生态最成熟，团队学习曲线低，asyncio支持并发 | Go（性能好但AI生态弱） |
| Web框架 | FastAPI | 0.110+ | 原生async，自动OpenAPI文档，Pydantic深度集成 | Django REST（过重），Flask（功能不足） |
| 数据验证 | Pydantic v2 | 2.6+ | Contract-first的核心工具，比v1快5-50x，强制类型安全 | dataclasses（功能弱） |
| ORM | SQLAlchemy | 2.0+ | async支持完整，类型提示好，迁移生态成熟 | Tortoise ORM（生态较小） |
| 数据库迁移 | Alembic | 最新 | SQLAlchemy官方配套，支持自动生成迁移 | Flyway（Java生态，不匹配） |
| 异步任务 | Celery + Redis | 5.3+ | 成熟稳定，支持定时任务和重试，监控工具完善 | Dramatiq（更轻量），Temporal（过重，后期引入） |
| Agent框架 | LangGraph | 0.2+ | 有向图Agent支持，state管理清晰，可调试 | CrewAI（不透明），自研（短期成本高） |
| HTTP客户端 | httpx | 最新 | 原生async，兼容requests接口，连接池支持 | aiohttp |

**关键约束**：
- Agent Runtime必须通过自定义`AgentRuntime`接口包装LangGraph，外部代码不直接import LangGraph
- 所有契约对象（MetricContract、EvidenceChain等）必须是Pydantic模型，不允许dict传递
- 禁止在OS Core层import任何业务域逻辑或平台SDK

### 1.2 前端

| 组件 | 选型 | 版本 | 决策理由 |
|---|---|---|---|
| 框架 | Next.js | 14+ (App Router) | SSR/SSG灵活，RSC降低初次加载，内置routing |
| 语言 | TypeScript | 5.x strict | 与后端Pydantic对齐类型安全 |
| 样式 | Tailwind CSS | 3.4+ | 快速开发，无运行时CSS，dark mode原生支持 |
| 组件库 | shadcn/ui | 最新 | 组件可定制，不绑定版本 |
| 服务端状态 | TanStack Query | v5 | 缓存、失效、乐观更新，SSE集成方便 |
| 客户端状态 | Zustand | 4.x | 轻量，无样板代码，支持中间件 |
| 流式响应 | SSE (Server-Sent Events) | — | EvidenceChain生成过程的实时推送，比WebSocket简单 |
| 图表 | Recharts | 2.x | React原生，响应式，EvidenceChain数据可视化 |
| 代码编辑器 | Monaco Editor | — | SQL模板和MetricContract编辑，与VS Code体验一致 |

### 1.3 数据存储

| 存储 | 用途 | 关键配置 |
|---|---|---|
| PostgreSQL 16 | 主数据库：Contract、Trace、Evidence、User、Tenant | JSONB存储灵活字段；Row Level Security做租户隔离；UUID主键 |
| pgvector | 语义向量存储：MetricContract嵌入、Intent相似度、KnowledgeAsset | 维度1536（OpenAI/Qwen embed兼容）；IVFFlat索引；cosine距离 |
| Redis 7 | 会话、缓存、Celery队列、限流计数器 | Sentinel HA；TTL策略按数据类型分层；不存业务敏感数据明文 |

**PostgreSQL关键Schema设计原则**：
```sql
-- 每张业务表必须有的基础字段
id          UUID PRIMARY KEY DEFAULT gen_random_uuid()
tenant_id   UUID NOT NULL REFERENCES tenants(id)  -- 租户隔离
created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
created_by  UUID REFERENCES users(id)
is_deleted  BOOLEAN NOT NULL DEFAULT false         -- 软删除

-- Row Level Security策略（每表必须启用）
CREATE POLICY tenant_isolation ON metric_contracts
  USING (tenant_id = current_setting('app.tenant_id')::UUID);
```

### 1.4 模型层（Model Gateway设计）

```
Model Gateway 路由策略：

任务类型           首选模型          Fallback           理由
意图解析           Qwen-7B-Instruct  GPT-4o-mini        速度优先，任务简单
SQL生成            Claude Sonnet     Qwen-72B           准确率优先
EvidenceChain生成  Claude Sonnet     GPT-4o             推理能力优先
风险评估           Claude Sonnet     — (无fallback)     安全优先，不降级
嵌入向量           BGE-M3           text-embedding-3    国产模型，成本低
```

**BYO Key支持**：
- 客户Key存储在HashiCorp Vault或K8s Secret，不进代码库
- Model Gateway透传客户Key，不持久化明文
- 每次调用记录：model、token数、成本估算、data_classification，不记录prompt内容

### 1.5 基础设施

| 层次 | 工具 | 用途 |
|---|---|---|
| 容器化 | Docker + Docker Compose | 本地开发环境 |
| 编排 | Kubernetes | 生产部署，支持Hybrid场景 |
| CI/CD | GitHub Actions | 测试门控、镜像构建、Eval回归 |
| 密钥管理 | HashiCorp Vault | BYO Key、数据库密码、API密钥 |
| 可观测性 | OpenTelemetry + Grafana | 链路追踪、指标、日志聚合 |
| 错误追踪 | Sentry | 后端异常和前端错误监控 |
| 特性开关 | Unleash / LaunchDarkly | 灰度发布、A/B测试 |

---

## 二、模块架构与职责

### 2.1 代码仓库结构

```
business_data_os/
├── packages/
│   ├── os_core/                    # 核心控制面（不依赖任何外部平台SDK）
│   │   ├── intent_runtime/         # 意图解析和结构化
│   │   ├── semantic_runtime/       # MetricContract、SemanticObject管理
│   │   ├── data_product_compiler/  # 需求编译、QueryPlan生成
│   │   ├── query_runtime/          # SQL安全层、查询执行沙箱
│   │   ├── evidence_chain/         # EvidenceChain构建和存储
│   │   ├── agent_runtime/          # Agent运行时（包装LangGraph）
│   │   ├── action_governance/      # ActionProposal、审批、OperationTrace
│   │   ├── eval_harness/           # 评测框架、golden query管理
│   │   └── knowledge_memory/       # KnowledgeAsset存储和检索
│   ├── providers/                  # 数据源Provider（每个独立模块）
│   │   ├── base/                   # ProviderContract抽象基类
│   │   ├── postgresql/             # PostgreSQL provider
│   │   ├── mysql/                  # MySQL provider
│   │   ├── clickhouse/             # ClickHouse provider
│   │   ├── maxcompute/             # 阿里云MaxCompute provider
│   │   └── api_rest/               # REST API provider
│   ├── action_connectors/          # 业务系统连接器
│   │   ├── base/                   # OperationContract抽象基类
│   │   ├── dingtalk/               # 钉钉审批和消息（P0）
│   │   ├── wecom/                  # 企业微信（P1）
│   │   └── webhook/                # 通用webhook
│   └── domain_packs/               # 行业包（第一版只有content_ecom）
│       └── content_ecom/           # 内容电商Domain Pack
│           ├── metric_contracts/   # 指标定义
│           ├── golden_queries/     # 黄金查询
│           ├── business_loops/     # 黄金业务闭环
│           └── eval_pack/          # 评测样本
│
├── apps/
│   ├── api/                        # FastAPI主应用
│   │   ├── routers/                # 路由（intent、metric、evidence、action等）
│   │   ├── middleware/             # Auth、Tenant、RateLimit、Trace
│   │   └── schemas/                # API请求/响应Schema
│   ├── worker/                     # Celery Worker
│   └── web/                        # Next.js前端
│
├── infra/
│   ├── k8s/                        # Kubernetes manifests
│   ├── docker/                     # Dockerfile
│   └── terraform/                  # 云资源配置（可选）
│
├── tests/
│   ├── unit/                       # 单元测试
│   ├── integration/                # 集成测试
│   └── eval/                       # Eval测试（golden query、golden loop）
│
└── docs/
    └── decisions/                  # ADR文档（架构决策记录）
```

### 2.2 核心模块接口规范

**MetricContract（核心数据结构）**：
```python
class MetricContract(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str                        # 指标名称（英文标识符）
    display_name: str                # 展示名称（中文）
    aliases: list[str]               # 别名列表（用于意图匹配）
    formula: str                     # 计算公式（人类可读）
    sql_template: str                # 参数化SQL模板
    dimensions: list[str]            # 可下钻维度
    time_dimension: str              # 时间字段
    owner: str                       # 业务负责人
    data_sources: list[str]          # 关联ProviderContract ID
    quality_rules: list[QualityRule] # 数据质量规则
    verified_at: datetime | None     # 最后验证时间
    eval_score: float | None         # 当前eval得分
    version: int                     # 版本号

class QualityRule(BaseModel):
    rule_type: Literal["not_null", "range", "freshness", "uniqueness"]
    field: str
    params: dict
```

**EvidenceChain（核心输出结构）**：
```python
class EvidenceChain(BaseModel):
    id: UUID
    tenant_id: UUID
    created_at: datetime
    # 输入
    raw_question: str
    parsed_intent: BusinessIntent
    # 数据依据
    metric_contracts_used: list[str]     # MetricContract ID列表
    provider_contracts_used: list[str]   # ProviderContract ID列表
    sql_executed: list[SQLExecution]     # 每条SQL的执行记录
    data_quality_checks: list[QualityCheckResult]
    # 输出
    findings: list[Finding]              # 结构化发现
    conclusion: str                      # 结论摘要
    confidence_level: Literal["high", "medium", "low", "uncertain"]
    limitations: list[str]               # 限制和不确定性说明
    # 追踪
    model_calls: list[ModelCallRecord]   # 模型调用记录
    total_duration_ms: int
    created_by: UUID

class SQLExecution(BaseModel):
    sql: str
    params: dict
    row_count: int
    duration_ms: int
    data_source: str
    executed_at: datetime
```

### 2.3 SQL安全层（四层防护）

```python
class SQLSafetyLayer:
    """
    四层防护，每层都必须通过才能执行
    """
    
    def validate(self, sql: str, context: QueryContext) -> SafetyResult:
        
        # 第一层：语法解析（使用sqlglot）
        ast = sqlglot.parse_one(sql, dialect=context.dialect)
        
        # 第二层：语句类型白名单
        if not isinstance(ast, sqlglot.exp.Select):
            return SafetyResult.BLOCKED("只允许SELECT语句")
        
        # 第三层：危险模式检测
        dangerous_patterns = [
            "information_schema",
            "pg_catalog",
            "system_tables",
            "--",      # SQL注释注入
            "xp_",     # SQL Server系统程序
        ]
        for pattern in dangerous_patterns:
            if pattern.lower() in sql.lower():
                return SafetyResult.BLOCKED(f"检测到危险模式: {pattern}")
        
        # 第四层：资源限制注入
        safe_sql = self._inject_limits(sql, max_rows=10000, timeout_ms=30000)
        
        return SafetyResult.PASSED(safe_sql)
    
    def _inject_limits(self, sql: str, max_rows: int, timeout_ms: int) -> str:
        # 注入LIMIT子句（如果没有）
        # 注入查询超时（数据库级别）
        ...
```

---

## 三、工程控制体系

### 3.1 Eval框架（CI/CD门控的核心）

**原则**：没有eval的代码不能进入主干，没有eval的Agent输出不能进入企业场景。

```python
# tests/eval/golden_query/runner.py
class GoldenQueryEval:
    """
    对所有golden query执行评测，结果必须达到阈值才能通过CI
    """
    THRESHOLDS = {
        "exact_match": 0.85,        # SQL结果精确匹配率
        "metric_coverage": 0.90,    # 核心指标识别率
        "evidence_chain_rate": 1.0, # EvidenceChain生成率（必须100%）
        "safety_pass_rate": 1.0,    # SQL安全通过率（必须100%）
        "p95_latency_ms": 15000,    # P95响应时间不超过15秒
    }
    
    def run(self) -> EvalReport:
        results = []
        for query in self.load_golden_queries():
            result = self.execute_single(query)
            results.append(result)
        return self.compute_report(results)
    
    def execute_single(self, golden: GoldenQuery) -> QueryEvalResult:
        # 1. 执行系统给出答案
        response = self.agent.answer(golden.question)
        
        # 2. 比较数字结果（允许±0.1%误差）
        numeric_match = self.compare_numerics(
            response.key_metrics, golden.expected_metrics
        )
        
        # 3. 检查EvidenceChain完整性
        evidence_complete = self.validate_evidence_chain(response.evidence_chain)
        
        # 4. 检查SQL安全性
        sql_safe = all(
            self.sql_safety.validate(sql).passed 
            for sql in response.evidence_chain.sql_executed
        )
        
        return QueryEvalResult(
            golden_id=golden.id,
            numeric_match=numeric_match,
            evidence_complete=evidence_complete,
            sql_safe=sql_safe,
            latency_ms=response.duration_ms,
        )
```

**CI/CD集成（GitHub Actions）**：
```yaml
# .github/workflows/eval-gate.yml
name: Eval Gate

on: [push, pull_request]

jobs:
  golden-query-eval:
    runs-on: ubuntu-latest
    steps:
      - name: Run Golden Query Eval
        run: pytest tests/eval/golden_query/ -v --tb=short
      
      - name: Check Thresholds
        run: python scripts/check_eval_thresholds.py
        # 如果任何指标低于阈值，CI失败，PR不能合并

  sql-safety-scan:
    runs-on: ubuntu-latest
    steps:
      - name: SQL Safety Regression
        run: pytest tests/eval/sql_safety/ -v
        # 任何SQL安全回归都是blocking issue
```

### 3.2 可观测性体系（三个维度）

**业务可观测（每日必看）**：
- EvidenceChain生成成功率
- Intent识别准确率（基于用户反馈）
- ActionProposal采纳率
- 用户活跃问题数（核心北极星指标）

**质量可观测（每周review）**：
- Golden Query通过率趋势
- 按MetricContract分类的失败率
- SQL Safety拦截率（异常上升需告警）
- P95/P99响应时间趋势

**成本可观测（每月review）**：
- 每个EvidenceChain的模型成本
- 每个租户的Token用量
- 按任务类型的模型调用分布

```python
# 所有关键操作都需要OpenTelemetry追踪
from opentelemetry import trace

tracer = trace.get_tracer("os_core.evidence_chain")

async def build_evidence_chain(intent: BusinessIntent) -> EvidenceChain:
    with tracer.start_as_current_span("evidence_chain.build") as span:
        span.set_attribute("tenant.id", intent.tenant_id)
        span.set_attribute("intent.type", intent.type)
        
        with tracer.start_as_current_span("evidence_chain.sql_generate"):
            sql = await self.generate_sql(intent)
        
        with tracer.start_as_current_span("evidence_chain.sql_execute"):
            result = await self.execute_sql(sql)
        
        span.set_attribute("evidence.confidence", evidence.confidence_level)
        span.set_attribute("evidence.row_count", result.row_count)
```

### 3.3 租户隔离（四层保障）

```
层1 - 应用层：所有查询强制注入 tenant_id 过滤
层2 - ORM层：SQLAlchemy事件钩子自动注入租户过滤
层3 - 数据库层：PostgreSQL Row Level Security Policy
层4 - 网络层：Kubernetes NetworkPolicy隔离租户命名空间（企业部署）
```

### 3.4 特性开关（渐进交付）

```python
# 每个高风险功能都通过特性开关控制
class FeatureFlags:
    ACTION_PROPOSAL_ENABLED = "action_proposal.enabled"
    AUTO_EXECUTION_ENABLED = "action_proposal.auto_execute"
    KNOWLEDGE_ASSET_ENABLED = "knowledge_asset.enabled"
    MCP_GATEWAY_ENABLED = "mcp_gateway.enabled"

# 使用方式
if feature_flags.is_enabled(FeatureFlags.ACTION_PROPOSAL_ENABLED, tenant_id):
    action_proposal = await generate_action_proposal(evidence_chain)
```

---

## 四、功能设计（按阶段）

### Phase 0（第1-4周）：数据基础

**目标**：让系统能连上数据源，理解指标。

| 功能模块 | 关键交付 | 验收标准 |
|---|---|---|
| ProviderContract CRUD | 连接数据源，验证连通性 | 能连接客户MaxCompute/MySQL，执行测试查询 |
| MetricContract管理UI | 创建/编辑/版本化指标口径 | 配置5个核心指标，带owner和formula |
| Schema探索 | 自动扫描数据源，推荐表/字段 | 展示可用表清单，字段注释可显示 |
| SQL模板管理 | 创建和测试参数化SQL | 10个SQL模板可参数化执行并返回正确结果 |

### Phase 1（第5-12周）：可信问数MVP（核心交付）

**目标**：业务用户用自然语言问问题，得到带EvidenceChain的可信答案。

**P0功能**：

1. **Intent Intake（意图输入）**
   - 自然语言输入框，支持中文
   - 实时意图解析反馈（"我理解您在问ROI…"）
   - 推荐问题展示（冷启动引导）

2. **MetricContract路由**
   - 基于语义相似度匹配最相关的MetricContract
   - 别名和同义词扩展
   - 匹配结果展示（"使用了ROI指标定义v2"）

3. **SQL生成与安全**
   - 三层策略：golden query直接命中 → 模板参数化 → 模型生成+验证
   - SQL安全层四层防护
   - 失败时降级："当前问题需要数据团队配置才能回答"

4. **EvidenceChain生成**
   - 完整EvidenceChain结构（问题、意图、口径、SQL、来源、质量、结论、限制）
   - 置信度分级展示
   - 每个数字可点击查看来源SQL

5. **Answer展示**
   - 结构化结论展示
   - 图表（Recharts，支持趋势/对比/分布）
   - EvidenceChain折叠展示（可展开查看详情）
   - 用户反馈按钮（有用/不有用/有问题）

6. **Eval Harness**
   - Golden Query管理界面（增删改查）
   - 自动化eval运行
   - 历史eval结果对比
   - 失败case标记为regression

**P1功能（Phase 1后半段）**：

7. **历史查询管理**：查询记录、复用、分享

8. **MetricContract自学习**：根据使用频率和失败case自动推荐改进

### Phase 2（第13-22周）：行动提案

**目标**：把可信洞察转化为可审批的行动提案。

**P0功能**：

1. **ActionProposal生成**
   - 基于EvidenceChain自动生成行动候选
   - 每个提案包含：行动描述、原因引用（EvidenceChain引用）、风险等级、审批建议、观察窗口、反馈指标
   - 风险分级：R1（纯读取）→ R5（高风险写操作）

2. **钉钉审批集成（P0 Action Connector）**
   - ActionProposal推送到钉钉审批流
   - 审批结果回流到OperationTrace
   - 审批状态在Intent Workspace实时更新

3. **OperationTrace**
   - 记录ActionProposal从生成到审批到执行的完整链路
   - 与EvidenceChain关联（证据→行动）
   - 可导出（合规审计用）

4. **执行反馈采集**
   - 行动执行后收集业务结果
   - 结果与EvidenceChain关联（闭环）
   - 反馈数据进入KnowledgeAsset

### Phase 3（第23-36周）：知识资产与多租户

**目标**：让系统越用越懂企业，支持多客户规模化。

**关键功能**：
1. **KnowledgeAsset管理**：指标口径变更历史、决策案例、SOP沉淀
2. **Domain Pack提取**：从首发客户抽象可复用的内容电商Pack
3. **多租户控制台**：租户管理、用量统计、计费基础
4. **Hybrid部署支持**：Connector Agent（驻客户内网）、数据不出域的EvidenceChain生成
5. **RBAC权限体系**：角色、权限、数据访问范围的细粒度控制

---

## 五、12个月实施路线图

### Month 1-2：地基

**工程目标**：搭建基础设施，完成可运行的空框架。

关键任务：
- [ ] 确定最终技术选型，写ADR
- [ ] 建立仓库结构（monorepo，模块边界清晰）
- [ ] PostgreSQL schema设计（MetricContract、ProviderContract、EvidenceChain核心表）
- [ ] FastAPI框架搭建（Auth、Tenant、Trace中间件）
- [ ] Model Gateway v1（支持Claude + Qwen两个provider）
- [ ] SQL安全层完整实现（四层防护，100%测试覆盖）
- [ ] CI/CD流水线（GitHub Actions，单元测试+集成测试）
- [ ] 本地开发环境（Docker Compose一键启动）

**里程碑**：工程师本地可以运行完整系统，SQL安全层测试全绿。

### Month 3-4：核心闭环

**工程目标**：完成Intent→EvidenceChain的第一个完整闭环。

关键任务：
- [ ] Intent Runtime v1（NL→结构化BusinessIntent）
- [ ] MetricContract语义匹配（基于pgvector嵌入）
- [ ] DataProduct Compiler v0.1（Intent→SQL Template路由）
- [ ] NL2SQL生成管道（三层策略）
- [ ] EvidenceChain Builder v1
- [ ] Golden Query Eval框架（30个初始样本）
- [ ] 基础前端：Intent输入框 + EvidenceChain展示
- [ ] MetricContract管理UI

**里程碑**：30个golden query通过率≥85%，每个答案有完整EvidenceChain，P95响应<15秒。

### Month 5-6：用户可用

**工程目标**：完成产品MVP，可以给参照客户试用。

关键任务：
- [ ] 完整Intent Workspace前端（历史、图表、反馈）
- [ ] 推荐问题系统（基于客户数据自动生成）
- [ ] Schema探索功能（自动扫描数据源）
- [ ] MetricContract学习和改进流程
- [ ] 基础用户管理（登录、权限、多用户）
- [ ] Eval Dashboard（历史趋势、失败分析）
- [ ] Sentry错误监控接入
- [ ] 第一个参照客户的ProviderContract配置

**里程碑**：参照客户开始日常使用，每周自主提问≥10次，golden query覆盖率≥90%。

### Month 7-9：行动闭环

**工程目标**：完成ActionProposal + 钉钉审批的完整链路。

关键任务：
- [ ] ActionProposal生成器（基于EvidenceChain）
- [ ] 风险评估引擎（R1-R5分级）
- [ ] 钉钉Action Connector（审批流集成）
- [ ] OperationTrace v1
- [ ] 执行反馈采集UI
- [ ] KnowledgeAsset基础存储
- [ ] OperationTrace导出（CSV/JSON）
- [ ] 第二个参照客户接入

**里程碑**：至少一个ActionProposal被真实采纳，有完整的从EvidenceChain到OperationTrace的审计链路。

### Month 10-12：规模化准备

**工程目标**：完成多租户硬化，准备正式商业化。

关键任务：
- [ ] 多租户控制台（管理员视图）
- [ ] 用量统计和配额管理
- [ ] RBAC权限体系完整实现
- [ ] 性能优化（P95 < 10秒，并发支持20+ QPS）
- [ ] Hybrid部署方案（Connector Agent）
- [ ] 安全审查和渗透测试
- [ ] 运维手册和SRE规程
- [ ] Domain Pack v0.1提取（内容电商）
- [ ] 正式定价和计费模块

**里程碑**：支持5个以上租户并发使用，Hybrid部署可以演示，完成一次正式安全审查。

---

## 六、关键ADR摘要（架构决策记录）

| ADR | 决策 | 理由 | 影响 |
|---|---|---|---|
| ADR-001 | Agent Runtime包装LangGraph而非直接使用 | 防止被框架锁死，保留替换能力 | 多一层封装，短期开发成本+5% |
| ADR-002 | SQL安全层四层防护必须100%通过 | 任何绕过都是信任危机 | 不允许"safe_mode=False" |
| ADR-003 | EvidenceChain是不可选的 | 没有证据链的输出只是AI草稿 | 任何答案必须有evidence_chain字段 |
| ADR-004 | 第一版ActionProposal只生成，不自动执行 | 降低企业信任门槛 | 钉钉审批是必须的，不是可选的 |
| ADR-005 | PostgreSQL+pgvector作为MVP数据底座 | 避免过早引入向量数据库复杂性 | >500万向量后需评估迁移 |
| ADR-006 | OS Core不能import domain_packs | 防止行业逻辑污染核心 | domain_packs通过Provider接口注入 |
| ADR-007 | 所有契约对象必须是Pydantic模型 | 类型安全，自动验证，文档化 | 不允许dict传递业务对象 |
| ADR-008 | Eval Gate是CI/CD的强制门控 | 没有eval的代码不进主干 | eval通过率下降时PR自动阻塞 |
| ADR-009 | 租户隔离必须在DB层实现RLS | 应用层隔离有绕过风险 | 每张表必须启用RLS |
| ADR-010 | 前3个月不引入Temporal | 异步任务用Celery就够，避免过早复杂化 | 有长时间工作流需求时重新评估 |

---

## 七、技术债务台账（初始版）

| 债务ID | 内容 | 接受理由 | 偿还触发条件 | 预计偿还成本 |
|---|---|---|---|---|
| TD-001 | LangGraph直接依赖（非完全自研Runtime） | 快速交付 | Agent框架成为性能/功能瓶颈 | 3-4个工程月 |
| TD-002 | pgvector（非独立向量数据库） | 减少运维复杂度 | 向量>500万或召回P95>500ms | 2个工程月+数据迁移 |
| TD-003 | OPA权限引擎接口预留但未实现 | MVP不需要 | 第二个企业客户有自定义权限需求 | 3-4个工程月 |
| TD-004 | OpenLineage接口预留但未实现 | MVP不需要 | DataProduct数量>50个 | 1-2个工程月 |
| TD-005 | 企业微信审批未实现（只有钉钉） | 精力集中 | 有客户明确需要企微审批 | 1个工程月 |
| TD-006 | Temporal工作流未引入 | 过早 | 有>30分钟长时间运行任务需求 | 2-3个工程月 |

