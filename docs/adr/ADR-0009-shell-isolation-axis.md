# ADR-0009: 罩硬化——隔离轴(ISO)与 ISO-0→ISO-1→ISO-2(轨A 预注册规格)

- Status: Accepted(2026-06-12;轨A 无保留事项,与轨C 同批开工)
- Date: 2026-06-12
- Deciders: agent(ADR-0003 协议,经 technical-architect 评审)
- Amends: ADR-0006(罩硬度从一维拆为二维)
- Relates: ADR-0007 P1.5 轨A;RR-0001 C7

## Context

technical-architect 指出:`CorrigibilityShell` 当前的"分离"是约定级。证据(已核对代码):
`Agent.__init__(shell)` 执行 `self.shell = shell`(agent.py:38),于是
`self.shell._paused = False`、`self.shell.op_resume()`、`self.shell.audit._entries.clear()`
**全部从 agent 代码可达**。ADR-0006 的 I4 不变量("op_* 不在 `Agent.__mro__`")只挡
`self.op_resume()`,挡不住 `self.shell.op_resume()`——agent 持有 shell 引用。

**术语冲突**:ADR-0006 的"Level 2"指形式化不变量(model checking)。但形式化验证
**治不了**本洞:它证明状态机逻辑无漏洞,却不能阻止同地址空间的对手**绕过状态机直接改内存**。
"逻辑正确"与"对手够不着"是两个正交维度。guardrail 的根本弱点正是后者(与被约束策略同信任域)——
所以这条轴才是"结构罩 vs guardrail"差异化的真正所在,也是 ADR-0007 把对照演示拆两处后,
对象层这一侧必须自证的东西。

## Decision: 罩硬度 = 二维(逻辑轴 × 隔离轴)

| 轴 | 含义 | 级别 |
|---|---|---|
| **逻辑轴 L**(ADR-0006 原三级,保留) | 状态机逻辑有无漏洞 | L0 约定 / L1 对抗验证(现状,38测试)/ L2 形式化不变量 |
| **隔离轴 ISO**(本 ADR 新增) | 对手能否够到罩的可变状态 | ISO-0 / ISO-1 / ISO-2(见下) |

当前罩 = **(L1, ISO-0)**。轨A 目标 = **(L1, ISO-1) 为默认运行态 + (L1, ISO-2) 为参考实现并以守卫测试钉死**。
ADR-0007 disposition 中"Level1→Level2(进程/账号边界)"一语,**正式重定义为隔离轴 ISO-0→ISO-2**,
与 ADR-0006 逻辑轴 L2(形式化)不再混淆。

### ISO-0:共享引用(现状)

agent 持有 `shell`,可经引用直接读写 `_paused`/`_forbidden`/`_snapshots`/`audit._entries` 与调用 `op_*`。

### ISO-1:能力视图(in-process,本 ADR 承诺的默认态)

- agent **不再持有 shell**。`Agent.__init__` 改收一个 `ShellView`。
- `ShellView` 只暴露 agent 的合法意图面:`paused`(只读)、`forbidden`(只读)、`observe(payload)`(只追加审计)。
  它**不持有** `_paused`/`_forbidden`/`_snapshots` 的可写引用,**不暴露** `op_*`。
- 实现:`CorrigibilityShell.view()` 返回一个 view,其内部只闭包持有"只读取 pause/forbidden 的 getter"与
  "向 audit 追加的 append"。可变状态与 `op_*` 仍在 shell 对象上,operator 持有 shell、agent 只拿 view。
- **诚实边界(必须写进代码注释与本 ADR)**:in-process Python 永不绝对隔离——
  `gc.get_objects()`、`view.__closure__`、`type.__subclasses__()` 等内省**仍可能**够到 shell 对象。
  ISO-1 的保证是"**消除直接引用路径、把规避成本从'一行'抬高到'蓄意内省'**",**不是**硬保证。
  硬保证由 ISO-2 提供。不得在文档/对外表述中把 ISO-1 说成"不可达"。

### ISO-2:跨进程(真隔离,参考实现 + 守卫测试)

- shell 跑在**独立进程**(stdlib `multiprocessing`)。agent 逻辑在 worker 进程,只持有一个连接(`Pipe`),
  经其发送 `observe(payload)`、读取 `paused`/`forbidden` 快照;`op_*` **只能在 operator/父进程调用**。
- agent 地址空间**物理上不含** pause 状态——worker 内任何内省都翻不动父进程的暂停。这才是"罩 vs guardrail"
  的可证明差异:guardrail 永远与策略同信任域,罩可跨信任域。
- 定位:**参考实现 + CI 守卫测试**,证明架构**能**达到真隔离;不必作为每个实验的默认运行态(IPC 有开销)。
  默认态用 ISO-1;ISO-2 锁住"可达性"上限。

## 预注册守卫测试(实施时落地,跑前不得改判据)

| ID | 断言 |
|---|---|
| ISO1-a | `Agent` 实例无任何属性路径可达可变 pause/forbidden/op_*;对 view `setattr`/改 `__dict__` 无法翻转 pause |
| ISO1-b | 回归:经 view 的 `paused`/`forbidden`/`observe` 行为契约不变;**现有 38 个罩测试全绿**(view 满足同契约) |
| ISO1-c | 演示对照:ISO-0 下 `agent.shell._paused=False` 生效(记录旧洞),ISO-1 下同操作无路径/无效 |
| ISO2-a | multiprocessing 参考:worker 无法影响父进程 pause(除经 operator 通道);父 `op_pause` 在 ≤1 决策步内令 worker `step` 返回 None |
| ISO2-b | 跨进程审计完整:worker 的 observe 追加进父链,`verify()` 成立;worker 不能改写既往条目 |
| ISO-honesty | 注释/文档显式声明 ISO-1 为"抬高成本非硬保证",ISO-2 为硬保证;**禁止过度声称** |

## Consequences

- `agent.py` 构造签名变更(收 view 非 shell)——**这是与轨C 共享的接缝**,触碰 `agent.py` 的改动须与轨C 串行
  (ADR-0007 接缝纪律)。建议轨A 的 ISO-1 改造先落,轨C 在其之上加上下文动作通路。
- ADR-0006 amended:罩硬度二维化;"Level 2"今后专指逻辑轴形式化,隔离用 ISO-* 指称。
- 无保留事项:纯基建硬化,agent 可决实施(待 founder 对本规格点头即开工)。
- 后续:RAP 多节点(P3)/LLM 器官(P4)启动前,默认态须达 ISO-2(降级需 founder 批,ADR-0003 保留事项)。
