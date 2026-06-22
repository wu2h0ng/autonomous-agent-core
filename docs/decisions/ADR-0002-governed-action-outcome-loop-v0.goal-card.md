# Goal Card — Governed-Action Outcome Loop v0

> 配套 ADR: `ADR-0002-governed-action-outcome-loop-v0.md`。任务实际起跑时，由 runner 在 `.agent_runs/{run_id}/` 创建 `goal_card.md` + `messages.jsonl`（task-local 审计层，受纪律门保护）。本文件为 ADR 同级的规划稿。

- Objective: 在 Customer-0（FaSoLa）上把**一条可逆 R4 治理动作 loop 端到端闭合**，并把 operator 独占的因果结果回灌为知识修订。
- Business value: 跨过只读洞察的商品化红海，进入只读竞品结构上进不来的"受治理动作→可度量结果"赛道；产出第一句竞品跟不了的话——"动作让数字动了 $X，错了可一键回滚，系统无法自我记功"。
- Task type: backend + eval（spec by Claude, core code by Codex）
- Risk level: R3（工程变更中高风险；演示动作为 R4 级但可逆、全程受治理；不做 R4/R5 自动执行）
- Owner: CTO（spec/裁决: Claude）；CEO 授权: founder
- Max agent retries: 2

## Scope Include
- ai-native-business-data-agent-os/packages/contracts（OperationContract 增 dry_run/idempotency_key；adoption 事件增因果指标 delta）
- ai-native-business-data-agent-os/packages/os_core（trusted_loop 治理执行分支、action_connectors/action_record、adoption、promote_from_adoption）
- ai-native-business-data-agent-os/apps/api_server（保留已存在 `POST /adoptions`；新增 CLI `adopt`；HTTP/CLI 共同接收 causal attribution）
- ai-native-business-data-agent-os/examples/<fasola>（端到端闭环的域专属装配）
- ai-native-business-data-agent-os/evals（D6 区分度 golden eval）

## Scope Exclude
- autonomous-agent-core/（任何跨仓 import；G-Eco / G10 结果不得在本 OS 宣称）
- R4/R5 自动执行（保持 proposal→approval→governed-execute，人审在环）
- D7：Monitor/Initiative 主动告警、学习型 MetricContract、知识衰减、对 Genie/CAN 的正确性 benchmark（各需独立 Goal Card）
- 已落地底座的重写：grounding 不变量、operator 独占通道、wirehead 隔离、corrigibility 壳（复用，勿动）

## Required Outputs
- ADR-0002（已起草）+ SPEC.md（D1–D6 契约 delta）
- D6 eval 先行（红）→ 实现转绿
- D2 dry-run + D3 幂等键：契约 + 连接器 + 运行时分支 + 测试
- D1 因果结果归因（operator 侧供给）+ D4 CLI `adopt` / causal attribution 摄入界面
- D5 审批后恢复执行入口：pending approval 经 operator approve 后才可 dry-run/snapshot/execute
- D5 FaSoLa 端到端 run + trace 产物 + 一次真实 rollback 演示
- CURRENT_STATE.yaml / code_index.md / ADR 状态同步

## Required Checks
- 测试在以下情况必须失败：grounding 被绕过、运行时自铸 EXTERNAL_ADOPTION、rollback 空操作、知识无 adoption 而晋升、同 idempotency_key 双写
- 负路径有测试：不安全/未授权/缺审批/已暂停 → 动作不执行
- OS Core 域无关：os_core 不 import FaSoLa 客户逻辑（ADR-0007）
- 无新增 skeleton/TODO/stub 而无对应真实实现（边界 #16）
- OperationTrace + RunTrace + adoption ledger 均更新
- 声明边界：仅 P5 治理 + 受治理动作；不宣称 autonomous/G-Eco
- 进入实现前过 CEO→Product→Architecture→CTO Gate（硬边界 #1，中高风险）
