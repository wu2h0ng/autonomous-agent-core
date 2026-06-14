# AI Native Business Data OS 首个业务闭环验证方案

> 日期：2026-06-02  
> 用途：定义第一个可被真实客户、真实数据和真实业务结果验证的业务闭环。  
> 场景：内容电商 / DTC 品牌的投放 ROI 异常归因与行动提案。  
> 结论：第一条闭环不验证“完整 Agent OS”，只验证一个高频高价值问题能否从业务意图进入可信证据、行动提案、审批和反馈。

---

## 1. 验证目标

首个闭环只回答一个问题：

```text
当业务负责人问“上周 ROI 为什么掉了？”
系统能否在已接入数据和已定义口径范围内，
给出可信数字、原因证据、行动建议和反馈路径？
```

成功不是“功能完整”，而是：

```text
业务用户连续两周主动使用系统判断 ROI 异常，
并至少有 1 条 ActionProposal 被采纳、拒绝或进入审批。
```

---

## 2. 目标客户与用户

### 2.1 目标客户

| 维度 | 标准 |
|---|---|
| 行业 | 内容电商、DTC、新消费品牌 |
| 规模 | 50-300 人 |
| 投放规模 | 抖音或小红书日消耗 >= ¥5 万 |
| 数据基础 | 有基础数仓、BI、广告后台、订单/ERP 数据 |
| 团队 | 数据团队 1-3 人，增长负责人或数据 VP 对 ROI 负责 |

### 2.2 核心用户

| 用户 | 角色 | 关注点 |
|---|---|---|
| 业务 VP / 增长负责人 | 业务 owner / 预算 owner | ROI 为什么掉、现在该做什么、谁负责 |
| 投放优化师 | 执行者 | 哪些计划、素材、达人需要调整 |
| 数据分析师 | MetricContract Owner / Evidence Reviewer | 指标口径、SQL、数据质量、证据可信 |
| IT / 安全 | 审计和权限 | 数据不出域、日志、权限、模型调用边界 |

---

## 3. 闭环边界

### 3.1 MVP 做什么

```text
BusinessIntent
  -> MetricContract
  -> DataRequirement
  -> QueryPlan / SQLTemplate
  -> EvidenceChain
  -> Root Cause Candidate
  -> ActionProposal
  -> Approval / Task
  -> FeedbackMetric
```

### 3.2 MVP 不做什么

| 不做 | 原因 |
|---|---|
| 自动暂停广告计划 | 高风险写操作，第一阶段只做建议和审批 |
| 全量广告平台 Connector | 先用可导出数据、API 或人工同步数据验证闭环 |
| 完整归因模型 | 先用可解释规则和指标分解，不做黑盒优化 |
| 全渠道营销 OS | 首发只做 ROI 异常这一个闭环 |
| 完整低代码和技能市场 | 与首个付费闭环无关 |

---

## 4. 业务问题定义

首个业务问题：

```text
上周 / 昨天 / 今天 ROI 为什么下降？
是哪个平台、计划、素材、达人、SKU 或库存因素造成的？
下一步应该怎么处理？
```

候选追问：

1. 和上周同期相比，ROI 下降了多少？
2. 是 GMV 降了，还是投放消耗涨了？
3. 哪个平台拖累最大？
4. 哪些计划 ROI 低于基线？
5. 哪些素材或达人表现突然下滑？
6. 是否存在库存不足、价格变化、退款升高等非投放因素？
7. 建议暂停、降预算、换素材，还是继续观察？

---

## 5. 最小数据范围

### 5.1 必需数据源

| 数据源 | 字段示例 | 用途 |
|---|---|---|
| 广告投放明细 | date、platform、campaign_id、campaign_name、ad_spend、clicks、orders、gmv | 计算 ROI、定位拖累计划 |
| 订单 / GMV | date、sku_id、order_amount、refund_amount、paid_amount | 校验 GMV、识别退款影响 |
| 商品 / SKU | sku_id、sku_name、category、price、stock_qty | 判断库存和商品因素 |
| 内容 / 达人 | creator_id、content_id、publish_time、engagement、gmv | 判断素材和达人因素 |

### 5.2 可选数据源

| 数据源 | 用途 |
|---|---|
| 库存流水 | 判断缺货、补货和履约影响 |
| 客服/售后 | 判断投诉、退货、质量问题 |
| 价格变更 | 判断促销或调价影响 |
| 竞品或平台活动 | 作为外部限制说明，不做强归因 |

### 5.3 数据接入原则

第一阶段不追求完整自动连接器。

可接受方式：

```text
API 接入
数据库只读接入
CSV / Excel 定时上传
客户提供脱敏样本
```

只要能验证闭环，不因为 Connector 完美主义拖延。

---

## 6. MetricContract 初版

### 6.1 核心指标

| 指标 | 定义 | 口径 owner | 风险 |
|---|---|---|---|
| ROI | GMV / AdSpend | 数据负责人 | GMV 是否含退款必须明确 |
| AdSpend | 广告消耗金额 | 投放负责人 | 平台口径与财务口径可能不一致 |
| GMV | 支付金额或成交金额 | 业务负责人 + 数据负责人 | 是否剔除退款、取消订单 |
| RefundRate | RefundAmount / GMV | 数据负责人 | 退款滞后导致短期不准 |
| CampaignROI | CampaignGMV / CampaignSpend | 投放负责人 | 归因窗口必须固定 |
| StockRisk | 低库存 SKU 对 GMV 的影响 | 供应链负责人 | 库存数据新鲜度 |

### 6.2 ROI MetricContract 示例

```yaml
metric_id: roi
name: ROI
aliases:
  - 投产比
  - 广告ROI
formula: gmv / ad_spend
grain:
  - date
  - platform
  - campaign_id
unit: ratio
owner: data_lead
business_owner: growth_vp
quality_contract:
  min_data_freshness: "T+1 or better"
  ad_spend_must_be_positive: true
  gmv_definition_required: true
evidence_template:
  required_sources:
    - ads_performance
    - order_summary
  required_fields:
    - ad_spend
    - gmv
    - date
limitations:
  - "退款存在滞后，短周期 ROI 需标注限制"
  - "不同广告平台归因窗口可能不同"
action_candidates:
  - reduce_budget
  - pause_campaign_for_review
  - replace_creative
  - investigate_stock_or_refund
feedback_metrics:
  - roi_after_24h
  - roi_after_48h
  - spend_change
  - gmv_change
```

---

## 7. EvidenceChain 模板

每次正式回答必须包含：

| 字段 | 内容 |
|---|---|
| question | 用户原始问题 |
| intent | 结构化业务意图 |
| metric_contracts | 使用哪些指标契约 |
| time_window | 查询时间窗口 |
| data_sources | 使用的数据源 |
| sql_or_query_plan | SQL / 查询计划 |
| result_summary | 数字摘要 |
| comparison_baseline | 对比基线，例如昨日、上周同期、历史均值 |
| root_cause_candidates | 候选原因及证据 |
| confidence | 高 / 中 / 低 |
| limitations | 数据限制、口径限制、归因限制 |
| action_proposals | 可讨论行动建议 |
| reviewer | 数据或业务审核人 |

置信度规则：

| 置信度 | 条件 | 输出 |
|---|---|---|
| 高 | 指标口径已确认、数据新鲜、SQL 命中模板、结果通过校验 | 可给结论和行动建议 |
| 中 | 数据完整但归因存在限制 | 给结论、限制说明和建议复核项 |
| 低 | 指标口径未确认或关键数据缺失 | 不给确定结论，只给需要补充的数据 |

---

## 8. ActionProposal 模板

### 8.1 行动类型

| 行动 | 风险等级 | MVP 处理 |
|---|---|---|
| 降低某计划预算 10%-20% | R2 | 生成建议 + 人工确认 |
| 暂停低 ROI 计划并复核 | R3 | 生成建议 + 审批 |
| 替换素材或达人 | R2 | 生成任务 |
| 检查库存风险 SKU | R1 | 生成任务 |
| 调整价格或促销策略 | R4 | 只生成高风险建议，不执行 |

### 8.2 ActionProposal 字段

```yaml
action_id: action_001
title: "降低计划A预算20%，观察24小时"
reason: "计划A ROI=0.8，低于过去7日均值2.1，贡献今日消耗的18%"
evidence_chain_id: ev_001
risk_level: R2
expected_effect: "减少低效消耗，预计24小时节省预算约¥8,000"
approval_required: true
approver_role: growth_vp
rollback_or_compensation: "24小时后若ROI恢复，可逐步恢复预算"
feedback_metrics:
  - roi_after_24h
  - spend_after_24h
  - gmv_after_24h
```

---

## 9. 闭环流程

```text
Step 1: 业务 VP 提问
“上周 ROI 为什么掉了？”

Step 2: IntentParser 识别
intent = roi_drop_root_cause_analysis
time_window = last_week
baseline = previous_week

Step 3: MetricContract 绑定
ROI = GMV / AdSpend
确认 GMV 是否含退款

Step 4: QueryPlan 执行
查询广告消耗、GMV、退款、计划、素材、达人、SKU、库存

Step 5: EvidenceChain 生成
展示 ROI 下降幅度、数据来源、SQL、口径、限制

Step 6: Root Cause Candidate
识别主要拖累因素，例如计划A消耗升高但转化下降、素材B疲劳、SKU C库存不足

Step 7: ActionProposal
生成 1-3 个可讨论行动建议

Step 8: Approval / Task
业务负责人确认或拒绝，生成钉钉/飞书任务

Step 9: Feedback
24/48小时后回看 ROI、消耗、GMV、库存变化

Step 10: KnowledgeAsset
沉淀本次决策、结果和复盘为可复用策略
```

---

## 10. 验收标准

### 10.1 功能验收

| 指标 | MVP 目标 |
|---|---|
| 核心问题正确率 | 30 条 golden question >= 90%，进入生产前 >= 95% |
| 数字一致性 | 与数据团队人工核对一致 |
| EvidenceChain 完整度 | 必填字段覆盖率 >= 95% |
| 首答速度 | 已沉淀核心问题 P95 <= 30 秒；复杂归因可异步 |
| ActionProposal 可用性 | 至少 1 条建议可进入业务讨论或审批 |
| 限制说明 | 低/中置信场景必须说明限制，不允许强行结论 |

### 10.2 业务验收

| 指标 | MVP 目标 |
|---|---|
| 自主使用 | 连续 2 周，业务用户每周主动使用 >= 3 次 |
| 采纳行为 | 至少 1 条 ActionProposal 被采纳、拒绝或进入审批 |
| 响应周期 | 从 1-2 天缩短到小时级或分钟级 |
| 客户资产 | >= 10 条 MetricContract，>= 10 条 EvidenceChain 历史 |
| 复盘闭环 | 至少 1 次 24/48 小时反馈复盘 |

### 10.3 付费验收

| 指标 | 判断 |
|---|---|
| 业务 owner 明确 | 必须有 |
| 预算 owner 明确 | 必须有 |
| POC 转付费条件明确 | 必须有 |
| 客户愿意继续使用 | 必须有 |
| 客户只愿免费试用 | 失败信号 |

---

## 11. Golden Questions

首批 15 条用于客户发现和 POC：

1. 上周 ROI 为什么下降？
2. 今天 ROI 和昨天相比怎么样？
3. 哪个平台拖累最大？
4. 哪些广告计划 ROI 低于基线？
5. 哪些计划花了钱但 GMV 没起来？
6. 哪些素材最近 7 天表现变差？
7. 哪些达人转化突然下降？
8. ROI 下降是因为 GMV 降了，还是消耗涨了？
9. 是否有库存不足导致投放效率下降？
10. 退款率上升是否影响了 ROI？
11. 如果要减少低效消耗，优先处理哪些计划？
12. 哪些计划建议继续观察，不建议立刻停？
13. 本周应该替换哪些素材？
14. 哪些 SKU 需要联动库存或补货？
15. 24 小时后应该看哪些反馈指标？

---

## 12. POC数据包要求

客户进入 POC 前必须提供：

| 材料 | 最低要求 |
|---|---|
| 广告投放数据 | 最近 30 天，按 date / platform / campaign 粒度 |
| 订单数据 | 最近 30 天，至少包含 GMV、退款、SKU |
| 商品数据 | SKU、类目、价格、库存 |
| 指标口径 | ROI、GMV、AdSpend、退款口径 |
| 现有报表 | 至少 3 张常用报表或 Excel |
| 现有 SQL | 有则提供，无则由数据团队说明口径 |
| 审批路径 | 哪些动作谁确认 |

如果客户无法提供以上材料，不进入正式 POC。

---

## 13. 风险与边界

| 风险 | 处理 |
|---|---|
| ROI 口径未统一 | 先做 MetricContract workshop，不直接生成结论 |
| 广告平台数据滞后 | EvidenceChain 中标注数据新鲜度 |
| 退款滞后影响短期 GMV | 限制说明中标注，不做强结论 |
| 客户要求自动暂停广告 | MVP 拒绝自动执行，只做审批建议 |
| 数据团队抵触 | 让其担任 MetricContract Owner 和 Evidence Reviewer |
| 客户要求连接所有系统 | 回到单一闭环，拒绝范围扩张 |

---

## 14. Go / No-Go

### Go

继续投入产品工程和 POC：

- 客户愿意提供真实数据。
- 业务 owner 每周参与评审。
- 数据 owner 愿意确认指标口径。
- 至少一个 ROI 异常问题能产生可信证据链和行动建议。
- POC 成功后存在明确付费可能。

### No-Go

停止当前客户或当前场景：

- 客户只愿意看 demo。
- 客户不给真实数据。
- 没有业务 owner。
- 只想做通用问数。
- POC 范围不断扩张。
- 无预算 owner 或采购路径。

### Pivot

调整但不推翻方向：

- ROI 场景数据太乱，但库存或客服场景更清晰。
- 内容电商客户不愿付费，但 DTC / 零售客户更强。
- 行动建议暂时无法进入审批，但 EvidenceChain 可先成为业务复盘工具。

---

## 15. 与现有文档关系

本文件是首个业务闭环的验证方案，配套：

- `02_竞争格局与商业化/AI_Native_Business_Data_OS_90天客户发现计划.md`
- `02_竞争格局与商业化/AI_Native_Business_Data_OS_GTM九问与POC转付费销售手册.md`
- `05_业务问题与评测样本/黄金业务闭环样本.md`
- `05_业务问题与评测样本/黄金查询样本.md`

