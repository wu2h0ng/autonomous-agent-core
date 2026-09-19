# ADR-0062: 可扩展性面（typed hooks / MCP / skills）的保守安全默认

- Status: **Draft — 待 founder 追认（PENDING FOUNDER RATIFICATION）**
- Date: 2026-09-19
- Deciders: founder（安全边界追认）；架构判断由 agent 起草，**评审等级为同模型 subagent 工作，非独立 provider 批准**（同 ADR-0061 §9 的限制，此为豁免不是满足）
- Track: Product Track（产品能力）；不得由研究证据或工程流程证据回填
- Baseline: `origin/feature/child-agent-stop-recovery-frame-gates = e9175de9`（worktree `.worktrees/ws-b-extensibility`，branch `feat/b-extensibility-20260919`）
- Upstream:
  - `docs/product/GC-TYPED-HOOKS-2026-09-18.md`（`DESIGN_ONLY / NO_IMPLEMENTATION_AUTHORITY`）
  - `docs/product/GC-MCP-FORM-AND-BOUNDARY-2026-09-18.md`（`DESIGN_ONLY / NO_IMPLEMENTATION_AUTHORITY`）
- Preserves: C6、C7、`ADR-0059`（单派发路径）、`ADR-0061`、所有历史 verdict 与 migration/release gate
- 编号核查（baseline 实测）：`docs/adr/` 在 baseline 上最高已接受编号为 `ADR-0061`（subagent fanout）；`ADR-0060` 仍仅被未合并分支占用；`ADR-0039/0040/0041` 历史重号不得复用。**0062 在 baseline 上空闲，本 ADR 占用之。**

## 1. Context

终端 Agent CLI 要长出"可扩展性"一项（typed hooks / MCP / skills）。两份 GC（`GC-TYPED-HOOKS`、`GC-MCP-FORM-AND-BOUNDARY`）把形态与边界写成了设计卡，但都明确 `NO_IMPLEMENTATION_AUTHORITY`，且列出了若干**不可逆的安全边界**需要 founder 决策（见两份 GC 的"需 founder/CTO 决策项"）。

本分片（B）的任务不是替 founder 拍板，而是：**在保守默认下把这三个面的最小骨架与 hermetic 测试先立起来**，把安全默认写成**代码里实际 enforce** 的不变量（不是只写文档），并把"待 founder 追认"显式标注。这样 founder 追认时改的是**默认开关**，而不是事后补安全。

今天的事实（baseline 实测）：

| # | 事实 | 位置 |
|---|---|---|
| F1 | 唯一派发路径是 `CapabilityBroker.invoke`；未注册能力 fail-closed | `packages/os_core/src/agent_os_core/capability.py`；`permission_gate.py:23-31` |
| F2 | 能力必须有完整 `CapabilitySpec`（risk_tier/credential_class/data_boundary 等必填） | `packages/contracts/src/agent_os_contracts/capability.py` |
| F3 | provider 凭据在 daemon 进程 env 里（`AGENT_OS_RUNTIME_PROVIDER_KEY_*` / `OPENAI_API_KEY` 等） | `GC-MCP` F11 |
| F4 | 今天**没有**任何 typed hooks / MCP client / skills 注册面 | 两份 GC §2 |

## 2. 决定（保守默认，代码 enforce）

以下默认在 `packages/os_core/src/agent_os_core/{typed_hooks,mcp_client,skills_registry}.py` 与 `packages/contracts/src/agent_os_contracts/extensibility.py` 中**实际 enforce**，并由 `tests/product/test_extensibility_*.py` 钉住：

### 2.1 typed hooks
1. **默认关（opt-in）**：空 registry 或全局 kill-switch `AGENT_OS_HOOKS_DISABLED=1` 时，dispatcher 不 spawn 任何子进程、不发任何记录，基线行为逐字节一致。
2. **仓内/工作区来源默认禁**：hook 来源只允许 operator-owned 文件；来源落在 workspace 根下时注册直接 fail-closed（`HookConfigurationError`）。
3. **隔离进程**：hook **绝不**在 daemon 进程内执行。每次 dispatch 用 `subprocess.run` 起一个短命子进程，stdin 给 JSON 事件快照，stdout 收 JSON 结果；daemon 进程不 `exec`/`eval` hook 代码。
4. **不是 MCP/skills 载体**：hook 配置与快照里没有 tool/skill/executor 句柄；v1 返回值恒为 observer（`None` 语义），不暴露工具/技能。
5. **完整性**：hook 字节 sha256 不符 → 该 hook 不载入并记 `SKIPPED/FAILED`。

### 2.2 MCP
1. **仅本机 stdio**：transport 锁定 `stdio`；网络/SSE/HTTP 在类型层与运行时都不接受。
2. **强制 env 白名单**：spawn server 子进程时只传显式 allow-list 内的 env 名；`FORBIDDEN_SUBPROCESS_ENV_NAMES`（`OPENAI_API_KEY`/`ANTHROPIC_API_KEY`/…）**绝不继承**，即使误列进 allow-list 也被剥离。
3. **tier 上限**：每个 MCP 工具标注 tier（1=只读安全，2=本地写，3=有副作用/外部影响）；**tier≥3 必须走正常审批流程**，adapter 在 preflight/execute 处对未批准的 tier≥3 抛 `McpTierRequiresApproval`，绝不自动执行。server 自报等级只能升、不能降我们的 tier。
4. **默认关**：`enabled=False`（默认）时绝不 spawn，零后台连接/握手。
5. **typed capability**：发现的每个工具经 `McpCapabilityAdapter.specs()` 注册为完整 `CapabilitySpec`（Form B 教训：注册齐全，探针可 list + call）。

### 2.3 skills
1. **opt-in**：skill 必须显式 `enabled=True` 才注册/广告；未声明或 disabled 的 skill 永不加载。
2. **model-agnostic**：skill 只携带 name/description/input_schema/tier，不绑任何 provider/model。
3. **tier≥3 需审批**：stub runner 对 tier≥3 skill 拒绝调用。
4. **全局 kill-switch** `AGENT_OS_SKILLS_DISABLED=1` 隐藏全部 skill。

## 3. 与权威脊的关系

- 不新增第二条派发路径：MCP/skill 调用仍经 `CapabilityBroker`（本 ADR 不触碰 `agent_loop`/`task_service`/`child_agent`，那是分片 A；接线留待组合根）。
- 不动 `PolicyKernel`/`permit`/C7 的签名与逻辑。
- hooks 只在窗外观察，不进入 `[reserve, seal]` 效果窗。

## 4. 未做 / 诚实边界

- **没有 live provider key**：MCP 多厂商/真机只能 hermetic 验证（stub stdio server），标 **NOT_MET**；不声称"支持 MCP"或 parity。
- hooks 的 P2（`HookDeny` 纯收紧）未做；本切片只做 observer。
- skills 只有注册/发现 + stub 调用；真实 skill 执行路径未接线。
- 同模型 subagent 工作是**豁免不是满足**：`builder_id != reviewed_by`、无独立 provider 批准，依据是 founder 2026-09-18 接受过该等级。

## 5. 仍需 founder 追认的决策项

1. hooks 隔离进程（而非同进程 operator-trusted）是否最终形态。
2. MCP 是否仅本机 stdio（本 ADR 选 stdio）；env 白名单是否即最终策略。
3. MCP 工具 tier 上限（本 ADR 选 tier≤2 默认、tier≥3 必审批）。
4. hooks/skills 默认关是否即为发布默认。

## 6. 声明分级

`specified: 本 ADR + 两份 GC` / `implemented: 最小骨架（hermetic）` / `tested: hermetic` / `integrated: NO（未接组合根）` / `verified: NO` / `released: NO`。
**不得**据此声称可扩展性能力已可用、market parity 或自主性。
