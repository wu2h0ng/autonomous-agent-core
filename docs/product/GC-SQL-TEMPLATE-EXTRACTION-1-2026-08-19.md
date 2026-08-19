# GC-SQL-TEMPLATE-EXTRACTION-1 — 生产 SQL 模板自动提取

- Date: 2026-08-19
- Track: Product (Agent OS canonical repo, feature branch TBD)
- Requirement class: **P** (primary), serving **U**: "operator connects a real warehouse and gets working, governed domain pack templates without hand-writing SQL"; **A** (secondary): extracted templates must pass SQL Safety gate and remain operator-approved.

## Problem

当前 Domain Pack Synthesis 只生成固定形状的简单模板（`SELECT date, SUM(col) ... GROUP BY date LIMIT :limit`）。但真实生产系统（如 ECS AutoBaseGet）的 SQL 查询是复杂的：

- 多步临时表（`CREATE TEMPORARY TABLE ... AS SELECT ...`）
- 变量声明（`SET @run_day = ...`）
- 多表 JOIN
- 条件逻辑（`CASE WHEN`）
- 聚合嵌套

手写这些模板是 operator toil，且容易出错。需要从生产 SQL 文件中自动提取可复用的参数化模板。

## Proposal

一个两阶段的模板提取管道：

```text
Stage 1: SQL 文件解析（只读）
  → 解析 .sql 文件，识别语句序列
  → 提取变量声明（@var）为参数
  → 识别最终 SELECT 输出（临时表链的末端）

Stage 2: 模板合成（proposal-only）
  → 将参数化 SQL 转换为模板契约
  → 每个模板通过 DataSQLSafetyChecker 自检
  → 生成 PackCandidateMetric（复用现有 synthesis 契约）
  → 操作员批准后 materialize
```

## Non-goals

- 不自动执行生产 SQL（只读解析，不运行）
- 不修改生产 SQL 文件
- 不支持存储过程/触发器/事件
- 不处理动态 SQL（EXECUTE IMMEDIATE 等）

## Trust boundary

- 解析器只读 SQL 文件内容，不执行任何语句
- 变量（`@var`）映射为命名参数（`:var`），不保留字面值
- 每个提取的模板必须通过 DataSQLSafetyChecker 自检
- 操作员批准是显式行为（命名 metric 列表）

## Acceptance

- Tests (written first): SQL 文件解析、变量提取、临时表链识别、参数映射、safety gate 自检、proposal 生成
- Real entry points: `agent-os extract-templates --sql-dir <path>` CLI 命令
- Failure paths: 无法解析的 SQL → 跳过并记录；无最终 SELECT → 跳过；safety gate 拒绝 → 不进入 proposal

## Boundaries

- OS Core 保持 driver-free：SQL 解析用 sqlglot（纯 Python），不连数据库
- Evidence ceiling: internal product capability; no autonomy/release claim
- DEPLOYMENT_PUSH stays HOLD

## Dependencies

- 当前分支 `codex/spine1-data-agent-mysql-20260819` 已合并（提供 MySQL capability + synthesis 基础设施）
- sqlglot 已在依赖中（用于 SQL safety 解析）

## Open questions

1. 复杂 SQL 的 safety gate：当前 `DataSQLSafetyChecker` 只支持单条 SELECT。多步临时表链需要扩展 checker 或拆分为多个模板。
2. 参数类型推断：`@run_day` 是日期类型，但解析器无法从 SQL 推断。需要操作员在批准时确认参数类型。
3. 模板粒度：一个 .sql 文件可能包含多个独立查询。是提取整个文件为一个模板，还是拆分为多个？
