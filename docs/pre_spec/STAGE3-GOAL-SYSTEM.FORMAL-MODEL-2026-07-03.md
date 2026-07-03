# STAGE-3 FORMAL MODEL — GoalSystem + GoalConflictHandler + WriteAuthorityLedger(先于机制文件)

- Status: **FORMAL-MODEL v1(2026-07-03)**。RR-0035 critic 点名 `goal_system.py` 的更重义务:downgrade lattice 与冲突谓词先形式化。机制文件在本文件 commit 后创建,测试先行。
- Scope: object 层。**冲突解决函数的签名中不存在 organ/belief/LLM 参数——自解在类型上不可表达**(结构性,非策略性)。gate/shell/self-model 零写路径延续(I1)。

## 1. 数学对象

**GoalSpec**(冻结数据,声明式):
```
GoalSpec = (goal_id: str, requires: Map[var:int -> state:int],   # 确定性成功谓词:∧_v x[v]==s
            priority: int,                                        # 静态,声明时定
            downgrade: tuple[GoalSpec, ...])                      # 预声明降级格(有限链,可空)
```
成功谓词 sat(g, x) = ∀(v,s)∈g.requires: x[v]==s。**谓词只有合取相等形式**——表达力上界显式声明(brittleness scope:不可表达的目标必须在进入 GoalSystem 前 ESCALATE,不允许静默丢给 LLM 判断;本层无 LLM 可用,结构性成立)。

**冲突谓词(确定性,可判定)**:
```
conflict(a, b) = ∃v: v∈a.requires ∧ v∈b.requires ∧ a.requires[v] ≠ b.requires[v]
```
输出 ConflictReport(var, a_state, b_state) 或 None。可判定:有限变量集上的集合交。

**解决规则(GoalConflictHandler.resolve,纯函数)**:
```
resolve(a, b) -> Resolution ∈ { DOWNGRADED(loser'), ESCALATE }
```
1. conflict(a,b)=None → 不适用(调用方不进 resolve)。
2. loser = priority 较低者(平 priority → **ESCALATE**,不掷硬币)。
3. 在 loser.downgrade 链中找**第一个**与 winner 不冲突的 g' → DOWNGRADED(g')。
4. 链空/全冲突 → **ESCALATE**(typed ConflictReport 附带)。
**签名 = resolve(a: GoalSpec, b: GoalSpec)——无 organ、无 belief、无置信度参数;自解结构性不可表达(A4 要求)。**

**WriteAuthorityLedger**(可审计声明 + 运行时检查):
```
ALLOWED = { BELIEF_WRITE, MEMORY_WRITE, GOAL_DECOMPOSITION_WRITE,
            PROPOSAL_ORDERING_WRITE, ORGAN_PARAM_UPDATE_OFFLINE }
check(writer, authority) -> None | raises UnknownAuthority | refuses+audits
```
`gate_write` / `shell_write` / `terminal_goal_write` / `audit_write` **不在 ALLOWED 中,check 对未知权限 raise**。**诚实措辞(RR-0035 critic 采纳)**:枚举缺席只是**声明腿**;SD4 结构禁止的**载荷腿**是 (i) shell 进程隔离(shell_ipc,agent 无写柄)与 (ii) gate 为冻结纯函数(无可达参数面)。本模块提供第三腿:**可审计的权限申报面**,让任何新写通道必须显式申报、未申报即拒绝+审计。

## 2. 不变量(各有测试)

- **I11 自解不可表达**:resolve 签名无 organ/belief 参;inspect 级测试锁定。
- **I12 确定性降级**:同输入同输出;降级只走预声明链;平 priority 必 ESCALATE。
- **I13 漏检不可能(在谓词表达力内)**:conflict() 对共享变量不同要求必报;合取相等谓词的冲突判定完备。
- **I14 权限封闭**:表达 gate/shell/terminal-goal/audit 写权限 → raise;未申报 writer → 拒绝 + 审计事件。
- **I15 表达力边界诚实**:无法表达为合取相等的目标在构造 GoalSpec 时即报错(不静默近似)。

## 3. could-fail gate(A4)

对抗目标冲突 battery:冲突对 → typed ConflictReport + ESCALATE 或预声明降级;**自解 = FAIL(结构不可能,由 I11 锁)**;**漏检 = FAIL**(I13);平 priority 掷硬币 = FAIL(I12)。

## 4. scope 与不主张

- priority/downgrade 链是**声明式治理输入**(founder/运营声明),不是学习对象——本层没有"目标学习"。
- 不解决目标**内容**的正当性(那是 principal 的事);只保证冲突被检测、解决被声明约束、权威面被申报。
- E7(受宪法约束的目标细化)仍是 founder-gated(IGI packet);本片只交付 E7 之下的机械底座。
