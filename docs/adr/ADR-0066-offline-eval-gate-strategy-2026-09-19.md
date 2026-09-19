# ADR-0066: 离线 eval 门禁策略（recorded/replay 为门禁臂，live 臂不进门禁）

- Status: **Decided**（founder 裁决 6，2026-09-19：gating eval 用录制/重放确定性臂，无 key 可跑；live 臂显式 optional、永不进 CI 门禁）
- Date: 2026-09-19
- Deciders: founder（门禁形态）；架构判断由 agent 起草，**评审等级为同模型 subagent 工作，非独立 provider 批准**（同 ADR-0061 §9：此为豁免不是满足）
- Track: Product Track（评测/门禁）；不得由研究证据回填
- Baseline: `origin/main = 04377dc3`（worktree `.worktrees/ws-p3-eval-release`，branch `feat/p3-eval-release-20260919`）
- Preserves: ADR-0061、ADR-0067（可扩展性保守默认，集成时由重号 0062 改编号）、所有历史 verdict、`tests/product_eval/_quarantine.py` 的"无静默 skip"纪律
- 编号核查（本 worktree 实测）：起草时 `docs/adr/` 出现两份 `ADR-0062`（extensibility 与 surface-protocol，后者随 #101 入 main）；`ADR-0063/0064/0065` 由 L4（checkpoint/minisign/版本分发）占用；本 ADR 编号为 `ADR-0066`。aggregate 集成时，extensibility 那份重号已重编号为 `ADR-0067`，surface-protocol 保留 `ADR-0062`。

## 1. Context

`tests/product_eval` 是产品评测套件。基线（`04377dc3`）上它是 **849 passed / 121 skipped**：121 个 skip 全部来自中央 quarantine manifest `_quarantine.py`，分四桶：

| 桶 | 数量 | 依赖 |
|---|---|---|
| cross_repo（跨仓 runner contract） | 83 | 兄弟仓 `ai-agent-engineering-workflow` pinned worktree（commit `50eb4d27...`），该 commit 对象在 fresh clone/CI 中**不存在** |
| docker | 27 | 真 Docker daemon + SRL falsifier 的固定不可变 worker image |
| live_provider | 2 | 绑定的 live provider 配置快照（base_url/model/api_key） |
| drift_research_candidate | 7 | 故意冻结的 DESIGN_ONLY 研究锚，绑定已漂移，需 re-freeze（**不应动**） |

问题：门禁臂要么依赖不存在的跨仓资产、要么依赖真 Docker、要么依赖 live key——fresh clone 的 CI 上 121 项是 skip，等于这部分逻辑**没有在门禁里真跑**。

## 2. Options Considered

| 选项 | 内容 | 判断 |
|---|---|---|
| A. 保持 quarantine，CI 接受 121 skip | 不改 | 拒绝：跨仓 runner contract 的 83 项实际测的是**消费侧**逻辑（fail-closed schema 校验、typed authority binding、receipt 内容寻址/突变拒绝），可 hermetic，不该永久 skip |
| B. 在 CI 里 checkout 兄弟仓 pinned commit | CI 跨仓 clone | 拒绝：pinned commit `50eb4d27...` 对象不存在；且门禁不应依赖另一个仓的存在 |
| C. vendor 兄弟仓关键资产 + cassette 重放臂（本 ADR） | 把 runner contract surface vendored 成本仓 fixture；terminal-coding eval 加 recorded/replay JSON 臂；docker 能本地化就本地化，不能就 quarantine | **选定** |
| D. live 臂进门禁 | 无 key 不跑 | 拒绝：live 臂是单次观测，且会把"门禁绿"与"有 key/有账单"耦合 |

## 3. Decision

### 3.1 跨仓 runner contract hermetic 化（已落地）
- 在 `tests/product_eval/fixtures/hermetic_runner/` vendor 了 recorded runner：closed `TeamEvent` schema、public record builder、以及写同样 `.agent_runs/<run_id>/{approval_requests,approvals,agent_events}.jsonl` 布局的 `init/permission/team event` CLI。
- conftest 的 `hermetic_runner` session fixture 把它包成干净 git 仓（pinned branch 名），autouse fixture 把 5 个测试模块的 `RUNNER_WORKTREE/RUNNER_PYTHON/RUNNER_BRANCH/RUNNER_HEAD`（含默认 kwarg 绑定）指向它。
- 结果：83 项中 **80 项转绿**；剩 **3 项**断言 runner **就是**那个真实兄弟仓（`.git` common_dir 路径、baked receipt 的 pinned SHA）——hermetic fixture 无法是那个外部仓，按 §3.4 保留 quarantine。

### 3.2 recorded/replay（cassette）离线 terminal-coding 臂（已落地）
- `product_evals/terminal_agent_eval/cassette.py`：`CassetteProvider(DeterministicProvider)` 从 **JSON fixture**（`tests/product_eval/fixtures/terminal_coding_cassette/reference.json`）逐步骤重放 `(text, tool_proposals)`，驱动**真实** `AgentOSApplication → AgentLoop → CapabilityBroker` 全回路。
- 新测试 `tests/product_eval/test_terminal_coding_eval_replay.py`：无任何 key、无网络，断言 cassette 臂跑出完整 work split（4/4 work、2/2 refusal）、0 unsafe action、`E2_CONTROLLED_SIMULATION`（**不**冒充 `E3_REAL_PROVIDER`）。
- cassette 是**数据制品**（不是 Python plan），可从真实 model 运行重新生成而不碰 harness。

### 3.3 live 臂永不进门禁
- `test_terminal_coding_eval_live.py` 的 live 臂是 opt-in（`@pytest.mark.skipif(not live_provider_available())`），**不计入 CI 门禁**；它产出的是单次观测，无阈值断言。门禁信号是 §3.2 的 cassette 确定性臂。

### 3.4 quarantine 卫生（reason + owner + review_by）
- 确实缺资产的保留 quarantine，**但每条必须带 `reason` + `owner` + `review_by`（复核到期日）**，由 conftest 的 `pytest_collection_modifyitems` 打印进 skip reason。无 owner/无到期日的 quarantine 视为静默永久 skip。
- drift_research_candidate 7 项**故意冻结不动**（DESIGN_ONLY re-freeze 由研究线负责）。
- docker 27 项：部分已用 monkeypatch subprocess.run（不需真 daemon）；`real_*` 与 receipt-wiring 仍需真 daemon+image，按 owner=`agent-os/srl`、`review_by=2026-10-19` 保留，待"用 fake docker subprocess 本地化"后解封。

## 4. Consequences / 可逆性

- **门禁绿的含义变诚实**：cross_repo 80 项现在是 fresh clone 上真跑的确定性测试，不再是 skip；cassette 臂是无 key 可跑的门禁信号。
- **可逆**：hermetic fixture 是 vendored 副本，真实兄弟仓在 exact SHA 时 `_real_sibling_runner()` 优先用真仓；cassette 臂是新增测试，不删旧 offline arms。
- **不做的主张**：cassette 臂**不是**模型能力证据（它重放录制的 reference plan）；不据此声称 parity/autonomy；live 臂仍为唯一能力观测源。
- **owner 复核责任**：每条 quarantine 的 `review_by` 到期须重新裁定（解封/再 hermetic/顺延），不得无限期 silent skip。
