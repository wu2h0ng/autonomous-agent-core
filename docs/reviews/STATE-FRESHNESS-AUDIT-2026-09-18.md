# 状态文档新鲜度审计（2026-09-18）

- **状态**：`DOCS_ONLY / AUDIT_ONLY / 不含任何能力或 release 主张`
- **审计对象**：本仓 `docs/CURRENT_STATE.yaml`、`docs/PROJECT_PLAN.md`、`docs/` 下 agent-cli/终端相关文档、`codebase_index.md`；外加**只读**审计根仓 `AI-Agent-Projects/docs/agent-cli/`。
- **审计基线**：`autonomous-agent-core` worktree `.worktrees/wt-state-audit`，分支 `docs/state-freshness-audit-20260918`，`HEAD == origin/main == 03ac66b5`（PR #69 的 merge commit，2026-09-18；该提交的 main CI 实测 success，run `35294406879`）。
- **本文的性质**：一份「诚实地图」，不是新文档层。**宁可少报，不错报**；能实测的都附命令与原始输出；不能核实的一律显式列出。
- **未做**（纪律）：不碰 `~/.agent-os/`；不修改根仓任何文件、不在根仓做任何 git 操作；不修改 `docs/CURRENT_STATE.yaml`（本轮协调者独占，改动写成 §7 的精确 diff）。

## 0. 方法、判据与证据分级

判据只有一条：**该陈述能否被今天的命令证伪**。因此本文每条都给出「文件 + 行/字段 + 原文要点 + 核查命令 + 实测输出 + 建议改法」。

证据分三级，逐条标注：

| 级别 | 含义 |
|---|---|
| **【实测】** | 我在上述基线 worktree 上今天亲自跑过命令，输出照抄 |
| **【转引】** | 我没跑，采信的是另一份文档或 CI 日志的记载（写明出处） |
| **【无法核实】** | 环境/纪律原因没有复现，或需要的运行时/凭证/机器不在本次范围内 |

一处**必须先说清的口径问题**（它本身就是本次最有价值的发现之一，见 §4.1）：

> 根仓 `TERMINAL-DISTRIBUTION-STATUS-2026-09-18.md:7` 把自己的「`apps/cli-ts/src` 内容指纹」写成 `96f3874a…` 并注明命令是 `find src -type f | sort | xargs shasum | shasum`。**【实测】**该数值只在**仓库根**运行 `find apps/cli-ts/src -type f | sort | xargs shasum | shasum` 时才出现；按文档字面写的命令（在 `apps/cli-ts` 内跑 `find src`）得到的是另一个值。`CURRENT_STATE.yaml:41` 的"更正"用的正是**字面命令**的值，于是**两份文档在比较两个不同的量**。详见 §4.1。

---

## 1. A 类：`docs/CURRENT_STATE.yaml` 中被证伪的「当前真值」

### A1. PR #69 已合并，但 pin 仍说 awaiting_approval "NOT in origin/main"

- **位置**：`docs/CURRENT_STATE.yaml:41`（pin `tui_ink_deleted_slice_k_2026_09_17` 的 CORRECTED 段）
- **原文要点**：「… but it is NOT in origin/main and still MISSING the GC/CTO gate and a contract minor-version decision」「so what is missing is **the merge into main, not the push**」
- **为什么过时**：PR #69 已于 2026-09-18 合并（merge commit `03ac66b5`，`gh pr view 69` → `state: MERGED`）。该字段现在就在 main 上。
- **核查命令与输出【实测】**：

```text
$ git show origin/main:packages/contracts/src/agent_os_contracts/surface.py | grep -n 'awaiting_approval\|SURFACE_PROTOCOL_VERSION'
14:SURFACE_PROTOCOL_VERSION = "1.1"  # E3: usage v2 cost-honesty contract on the wire
186:    awaiting_approval: bool = False

$ gh pr view 69 --json state,mergedAt,mergeCommit
{"mergedAt":"2026-09-18T01:12:55Z","mergeCommit":{"oid":"03ac66b563e689fd3c87d38eed2aae400989f6d5"},"state":"MERGED"}
```

- **同一 pin 中仍然正确的部分（不要一起改）**：四个代码位置行号全部实测命中 —— `packages/contracts/…/surface.py:186`、`apps/api_server/app.py:2703`、`apps/cli-ts/src/contracts.ts:78`、`apps/cli-ts/src/opentui/agent-tree-source.ts:92`；`SURFACE_PROTOCOL_VERSION` 确实仍是 `1.1`（见上面的输出），所以"加性字段在未升版的协议下随分支发布"这一条判断仍成立，只是范围从"分支"扩到"main"。
- **建议改法**：把「NOT in origin/main / 缺的是合并」改为「**已于 2026-09-18 经 PR #69 合并进 main（merge commit 03ac66b5）；仍缺 GC/CTO gate 与契约 minor 版本决定**」。见 §7 D1。

### A2/A3. `not merged to main` 的三处尾句

- **位置**：`:42`（pin `tui_runtime_identity_2026_09_18` 末句）、`:43`（pin `workspace_search_scan_cap_honesty_2026_09_18` 末句）
- **原文要点**：`:42`「implemented/tested on this branch; **not merged to main**, not released - that part stands.」；`:43`「implemented/tested on this branch; **not merged to main**, not released.」
- **为什么过时**：这两条 pin 描述的工作都在 PR #69 的分支 tip `203b8862` 上，而该提交已是 main 的祖先。
- **核查命令与输出【实测】**：

```text
$ git merge-base --is-ancestor 203b8862 origin/main && echo "YES ancestor" || echo NO
YES ancestor
$ git rev-list --count 203b8862..origin/main
13
$ git rev-list --left-right --count origin/tui/parity-f-code-highlight...HEAD
0       1
```

- **同一 pin 中的第二个过期点【实测】**：`:42` 里「Measured now: HEAD = **203b8862**」与「`git rev-list --left-right --count origin/tui/…...HEAD` = **0 0**」都已不成立 —— 现在 HEAD 是 `03ac66b5`，该比值是 `0 1`（`origin/tui/parity-f-code-highlight` 仍指向 `3a31a65c`，即合并的另一侧父提交）。这类"Measured now"字样的表述**没有自带时间戳锚点**，是本次审计里最容易再次变旧的一种写法。
- **建议改法**：见 §7 D2/D3。

### A4. 顶层 `status:` 同一字段内自相矛盾

- **位置**：`docs/CURRENT_STATE.yaml:70`（顶层 `status`）
- **原文要点**：同一字符串里既写「**PUSHED: false** (push requires separate founder authorization)」，又写「The integration is **PUSHED / MAIN_INTEGRATED / UNRELEASED**」。
- **为什么过时**：后者为真（SPINE-1 receipt `807a0590` 与 ADR-0059 的 `ca775d39`/`1b6b036a` 都是 main 的祖先），前者为假。
- **核查命令与输出【实测】**：

```text
$ git merge-base --is-ancestor 807a0590 origin/main && echo IN_main || echo NOT
IN_main
$ git merge-base --is-ancestor 97d15a9d origin/main && echo IN_main || echo NOT
IN_main
$ git merge-base --is-ancestor 3a70592d origin/main && echo IN_main || echo NOT
IN_main
```

- **建议改法**：`PUSHED: false (push requires separate founder authorization).` → `PUSHED: true (measured 2026-09-18: 807a0590 and ca775d39 are ancestors of origin/main 03ac66b5).` 见 §7 D4。

### A5. `identity.first_vertical` 与 `current_phase.migration` 互相矛盾

- **位置**：`:86`
- **原文**：`first_vertical: "Data Agent, locally extracted into domain_packs/data_agent under ADR-0054/SPINE-1; unpushed, unmerged and unreleased"`
- **为什么过时**：与同文件 `:98` 的 `migration.status = "G0-G7_PASS / INDEPENDENT_APPROVE / PUSHED / MAIN_INTEGRATED / UNRELEASED"` 直接冲突；实测 data agent 已在 main。
- **核查命令与输出【实测】**：

```text
$ git ls-tree -d --name-only origin/main domain_packs/
domain_packs/data_agent
domain_packs/developer_agent
```

- **建议改法**：`unpushed, unmerged and unreleased` → `pushed and main-integrated (SPINE-1 receipt 807a0590), unreleased`。见 §7 D5。

### A6. `origin_main_code_receipt` 不是 origin/main —— 键名把历史 receipt 标成了 live pin

- **位置**：`:4` `live_pins.origin_main_code_receipt: "3a70592ddee2e24af94f2da52903a5d73386b10d"`，以及在正文里复用它作为"当前 main"的 `:92`
- **原文要点**：`:92` `status: "MAIN_INTEGRATED_INSTALLABLE_AGENT_SURFACE_AT_3A70592 / TECHNICAL_APPROVE / NOT_RELEASED"`
- **为什么过时**：`3a70592d` 是 **installable Agent Surface 的评审 head**（本文件 `:141` 的 `dated_verification.exact_head` 同值；根仓 `docs/CURRENT_STATE.yaml` 里它叫 `reviewed_entrypoint_head`）。作为"能力评审 head"它没变、也不该变；作为名为 `origin_main_code_receipt` 的 live pin 它落后 main **965 个提交**。
- **核查命令与输出【实测】**：

```text
$ git rev-list --count 3a70592d..origin/main
965
$ git merge-base --is-ancestor 3a70592d origin/main && echo IN_main || echo NOT
IN_main
```

- **判断**：这不是"值写错"，而是**键名把一个冻结 receipt 声明成了活 pin**。两类信息混在同一个 `live_pins` 段里。
- **建议改法**：把该键**改名**（`installable_agent_surface_reviewed_head`）并另加一个 `origin_main_head`；同时给 `:92` 的状态串补上 live main。见 §7 D6。

### A7. `merged_this_turn` 里两条写着 "no push"/"NOT pushed"

- **位置**：`:19`、`:20`
- **原文要点**：`:19`「P-SELFDEV-SCOPED-VERIFIER + malformed SSE delta oracle (**local no-ff merge 0705de64; no push**)」；`:20`「ADR-0059 capability execution authority merge (… merge-prep branch 97d15a9d; **committed locally, NOT pushed**)」
- **为什么过时**：`0705de64` 与 `97d15a9d` 都已是 main 的祖先（见 A4 的输出）。
- **建议改法**：两处的 push 状态改为"已随 main 推送"；该段本身是 2026-09-13 的"本轮合并"清单，建议整体移入历史或加 `as_of: 2026-09-13` 标记。见 §7 D7。

### A8. realtime-collab 两条 merge receipt 写着 "NOT pushed"

- **位置**：`:8`、`:10`
- **原文要点**：`:8`「1ea99cab (no-ff merge of feature/realtime-collab-fence-20260814 @ 4b5c2a50; APPROVE round-3; **NOT pushed**)」；`:10`「25408138 (… APPROVE round-2; **NOT pushed**)」
- **为什么过时**：
- **核查命令与输出【实测】**：

```text
$ git merge-base --is-ancestor 1ea99cab origin/main && echo IN_main || echo NOT
IN_main
$ git merge-base --is-ancestor 25408138 origin/main && echo IN_main || echo NOT
IN_main
```

- **顺带记录**：`:9`/`:11` 的 `SURFACE_NOT_IMPLEMENTED` / `SURFACE_RENDERER_NOT_IMPLEMENTED` 我**没有**证伪 —— `apps/api_server/app.py` 里确有 `SurfaceConflictProjection` 与 `WorkspaceCollaborationPreflight`（`:453-458` 等），但 `apps/cli-ts/src` 只有一处注释提到 conflict（`session-command.ts:24`），没有渲染实现。按现有证据，"事件生产者/冲突投影已实现、面渲染未实现"这一判断**看起来仍成立**，但我没有做端到端核实，**不作为结论**。
- **建议改法**：见 §7 D8。

### A9. "tests/product 有 23 个既存失败 / 仓库不绿" 已被 main 的 CI 证伪

- **位置**：
  - `:955`（`blockers.repository`）「The last repository-wide run on the prior candidate was **2616 passed/1 skipped/27 failed** … so full-suite-green is false.」
  - `:956`（`blockers.repository`）「Repository-wide Product+product_eval remains non-green at **2504 passed/1 skipped/7 failed**」
  - `:996`（`test_commands.caution`）「The 2026-07-18 responsibility integration run ended with **2504 passed, 1 skipped and 7 failed** … the repository-wide suite is not green and no Product/research claim may erase that debt.」
  - 相关：`:22`、`:26`、`:27` 的 pin 记「23 failed / 2542 passed」「tests/product 23 failed (all pre-existing) / 2518 passed」
- **为什么过时**：被 CI 的 **governed product gate** 直接证伪。该 gate 跑的就是 `pytest tests/product`，在 `03ac66b5` 上 **exit 0**。
- **核查命令与输出【实测/转引】**：

```text
$ gh run list --branch main --limit 5 --json headSha,conclusion -q '.[] | "\(.headSha) \(.conclusion)"'
03ac66b563e689fd3c87d38eed2aae400989f6d5 success
e44ef04496b48bb0137bb9fe5da4b0d1d1dd835b success
475d20cc8500fd31394663a76d6c355cbcc29c31 success
04ff1fa758b88faf3d927f9bafa0ce9841a51783 success
c5085f1451fd6f433438367ebdb7b22eba7d5b08 success

$ gh run view 35294406879 --json jobs -q '.jobs[] | "\(.name) \(.conclusion)"'
cli-ts success
test success

$ gh run view 35294406879 --log | grep -E 'tests/product collected|passed'
tests/product collected 2754 items (floor 2500)
2747 passed, 7 skipped in 200.58s (0:03:20)
tests/product: pytest exit 0, 1 skipped test(s) (bound 12)
```

  即：在 main 的 `03ac66b5` 上，`tests/product` **2754 collected / 2747 passed / 7 skipped / 0 failed / exit 0**；那 7 个 skip 全部是 Linux 上的平台条件跳过（`sandbox-exec` 缺失的 4 条 + macOS-only Seatbelt 2 条 + 双平台共同的 live-provider 1 条，见同 run 的 SKIPPED 行与 `:50` pin 记录）。
- **必须分清的边界（不要过度更正）**：
  1. `:956` 说的是 **Product + product_eval** 的合并口径；CI **只跑 `tests/product`**（`grep -n product_eval .github/workflows/ci.yml` → 无命中，`tests/product_eval/` 存在但不在 CI 内）。所以 `tests/product` 那一半被证伪，`tests/product_eval` 那一半**我没有核实**，不能替它宣布转绿。
  2. 上面所有数字都是 **Linux CI** 口径。 macOS 本机口径我没跑（见 §6）。
- **建议改法**：见 §7 D9。建议的措辞是"**在 main 的 03ac66b5 上 `tests/product` 由 CI 实测为 green（2754 collected / 2747 passed / 7 skipped / exit 0，run 35294406879）；product_eval 未在 CI 内，其状态未复核**"，而不是简单删掉债务句。

### A10. `freshness:` 块落后两个月

- **位置**：`:1031-1039`
- **原文要点**：`checked_at: "2026-07-18T18:10:10+08:00"`；`canonical_code_head: "24280fc46879a2b4a4f9884af6bf10fb179406e7"`；`prior_remote_main: "6c94bd8c…"`；`merge_base: "6c94bd8c…"`
- **为什么过时**：这是读者做新鲜度判断的**入口字段**，却指向 2026-07-18。`24280fc` 确实是 main 的祖先（不是别的分支），但早已不是 code head。
- **核查命令与输出【实测】**：

```text
$ git merge-base --is-ancestor 24280fc origin/main && echo IN_main || echo NOT
IN_main
$ git rev-parse --short origin/main
03ac66b5
$ git log -1 --format='%h %ad %s' --date=short -- docs/CURRENT_STATE.yaml
3a31a65c 2026-09-18 docs(state): close the rejected-approval defect and sharpen the pause finding
```

- **需要协调者判断的地方**：该块的 `commit_state` / `merge_scope` / `evidence_separation` 文本明确是 **Research 线**（R-W1W2-ABA-1 / B1-B5）的口径。所以它可能是有意只覆盖研究线的。**建议**：要么整体更新，要么把键改名成 `research_ledger_freshness` 并保留日期，避免被当作全仓新鲜度。见 §7 D10。

### A11. `updated:` 落后于文件实际内容

- **位置**：`:65` `updated: "2026-09-16T00:00:00+08:00"`
- **为什么过时**：文件最后一次被修改是 `3a31a65c`（2026-09-18，见 A10 输出），且文件正文含大量 `2026-09-18` 的更正段。
- **建议改法**：见 §7 D11。

### A12. provider pin 的三条 "honest limits" 已被代码取代

- **位置**：`:25`（pin `provider_native_and_persistence_2026_09_14`）末尾
- **原文要点**：「Honest limits: … **no pricing source (cost UNKNOWN); max_tokens hardcoded for Anthropic; no per-vendor rate-limit/retry policy**.」
- **为什么过时**：同一仓、同一天的 GC 文档 `docs/product/GC-PROVIDER-COMPAT-AND-TERMINAL-ADD-2026-09-14.md` 已把 Slice 6/7 记为 IMPLEMENTED，代码里也确实在。
- **核查命令与输出【实测】**：

```text
$ grep -n 'AGENT_OS_PRICING_FILE\|AGENT_OS_PROVIDER_MAX_RETRIES\|AGENT_OS_PROVIDER_MAX_TOKENS\|cost_status="KNOWN"' \
    packages/os_core/src/agent_os_core/provider.py
236:    override = os.environ.get("AGENT_OS_PRICING_FILE")
539:        env_max_tokens = _optional_int_env("AGENT_OS_PROVIDER_MAX_TOKENS")
543:        env_max_retries = _optional_int_env("AGENT_OS_PROVIDER_MAX_RETRIES")
842:            cost_status="KNOWN",

$ git log -1 --format='%h %ad %s' --date=short -S 'AGENT_OS_PRICING_FILE' -- packages/os_core/src/agent_os_core/provider.py
632f46c2 2026-09-14 provider: live smoke harness + parameters/pricing/retry (Slices 6-7)
```

- **建议改法**：把这三条 limit 换成仍然成立的限度（例如"定价源需外部文件 `AGENT_OS_PRICING_FILE`/`~/.agent-os/pricing.json` 才有 KNOWN；否则仍 UNKNOWN，绝不伪零"）。见 §7 D12。

### A13. Stage 2f 的"进行中"语气与自身后文冲突

- **位置**：`:26`（pin `stage2_path_a_migration_2026_09_15`）
- **原文要点**：同一 pin 里既写「`apps/cli/__main__.py` **is being slimmed** … in Stage 2f2-2f3」，又写「Stage 2f2 **DONE**」「Stage 2f3 **DONE**」；末句「Remaining: 2f4 (final sweep …)」也与 `docs/product/STAGE2-PATH-A-MIGRATION-PLAN-2026-09-15.md` §16「**Stage 2f4 完成**（2026-09-15）」冲突。
- **核查命令与输出【实测】**：

```text
$ grep -n '^## 1[456]\.' docs/product/STAGE2-PATH-A-MIGRATION-PLAN-2026-09-15.md
199:## 14. Stage 2f2 完成（2026-09-15）：删除 session/mandate/task/workflow/daemon CLI
207:## 15. Stage 2f3 完成（2026-09-15）：agent-os-work 入口
214:## 16. Stage 2f4 完成（2026-09-15）：最终扫描与收口
```

- **建议改法**：见 §7 D13。

---

## 2. B 类：`docs/CURRENT_STATE.yaml` 内部的自相矛盾（不依赖外部事实即可判）

| # | 位置 | 矛盾 |
|---|---|---|
| B1 | `:94` vs `:948` | `current_phase.research.label` 说「no B1-B5 acceptance」；`blockers.research` 说「B1 is unaccepted」。两者一致，**不是矛盾**（列出以示我没有误报）。 |
| B2 | `:98` vs `:86` | migration 说 PUSHED/MAIN_INTEGRATED；identity 说 unpushed/unmerged（= A5） |
| B3 | `:70` 内部 | PUSHED: false vs "is PUSHED"（= A4） |
| B4 | `:41` 的「NOT in origin/main」vs `:42`/`:43` 的分支已推 —— pin 之间对"分支 vs main"的口径已经不统一（部分已被 2026-09-18 的更正段指出，但只改了被指出的那一条） |

B2/B3 已在 A 类给出 diff；B1 明确列为"正确"，避免误报。

---

## 3. C 类：本仓其他文档

### C1. `docs/product/TUI-PARITY-CHECKLIST-2026-09-16.md` 头部状态与它自己的 §16 冲突

- **位置**：`:4`、`:5`
- **原文要点**：`:4`「**状态**：`IN_PROGRESS`（切片 A 已合并/在审；**尚不可退役 Ink**）」；`:5`「**基线**：`src/App.tsx`（Ink）为准；全屏为迁移目标。」
- **为什么过时**：同文件 `:383` 的 §16 标题就是「切片 K（2026-09-17）：**Ink 已删除，dist 已重建 —— 退役完成**」。
- **核查命令与输出【实测】**：

```text
$ ls apps/cli-ts/src/App.tsx
ls: apps/cli-ts/src/App.tsx: No such file or directory
$ grep -rn 'from "ink"' apps/cli-ts/src apps/cli-ts/test | wc -l
0
$ grep -rn 'ink\b' apps/cli-ts/package.json | wc -l
0
```

- **建议改法**：把 `:4` 改为 `DONE / INK_RETIRED_2026_09_17`，`:5` 的基线改为「冻结快照 `test/fixtures/ink-home-baseline.ts`（Ink 本体已删，快照保留为历史基线）」。

### C2. 同一 checklist 的 #3 / #17 行把**同一条测量记成两条证据**

- **位置**：`:14`（#3 行）、`:28`（#17 行）
- **原文要点**：`:18`「… `pty_theme_check.py` 现在**同时覆盖 header 与 footer**（`THEME_KEYS_CHANGED: ['header','footer']`）」；`:17`「pty `THEME_APPLIED` 断言 **footer** 的 SGR 随 `/theme mono` 变化」
- **为什么过时**：与本仓 `CURRENT_STATE.yaml:36` 自己记录的探针缺陷冲突 —— 该 pin 明确写「`Screen.token_style('ASK')` 返回**第一行**含该 token 的行，而 header 状态行就含 `ASK`，所以两个 key 读的是同一行；`THEME_KEYS_CHANGED ['header','footer']` 是 header 读数的重复，footer 声称从未真正被测过」，并指明「footer 在源码里根本没有消费者」。
- **核查命令与输出【实测】**：

```text
$ grep -rn 'theme\.footer\|theme\.border\|theme\.danger\|theme\.approvalTitle' apps/cli-ts/src | wc -l
0
$ grep -n 'token_style' apps/cli-ts/scripts/pty_theme_check.py | head -3
（脚本以 Screen.token_style 取首个含该 token 的行）
```

- **建议改法**：`:14` 改为「header 由 `pty_theme_check.py` 直接测量（`THEME_APPLIED`）；**footer 未经测量**——`theme.footer` 在 `apps/cli-ts/src` 零引用，footer 文本元素无 `fg`」；`:28` 的断言对象由 footer 改为 header。

### C3. checklist §2 结论段保留了被 §15.1 推翻的"仅 Bun"结论

- **位置**：`:32`（`## 2. 结论`）起的结论段，具体在 `:37-38`
- **原文要点**：「关键约束：全屏客户端**在 node 下起不来**（`OpenTUI native FFI is not available`，实测），**只在 bun 下运行**」
- **为什么过时**：同文件 §15.1（`:327-336`）与 `TUI-INK-RETIREMENT-PREP` §1.1 都已更正为「只对 **Node 22** 成立；Node 26.9.0 实测可用，Bun 只是 founder 选的默认」。§15 改了，§2 没回改。
- **建议改法**：`:37-38` 那一条加一句"（已于 §15.1 更正：只对 Node 22 成立）"，或在 `:32` 段首加"§2 为 2026-09-16 快照，后续更正见 §15/§16"。

### C4. checklist §16.3 说三条断言"无等价覆盖"，其实已补齐

- **位置**：`:409-411`
- **原文要点**：「…**三条无等价断言**：`backspace`（macOS `0x7f` 删前一个字符）、`ctrl-d` 前向删除、多行粘贴 CR/CRLF 归一。这三者现由 opentui `<textarea>` 原生处理，pty 脚本只是**用它**清空输入框而未断言。」
- **为什么过时**：同仓 `docs/product/TUI-INK-RETIREMENT-PREP-2026-09-17.md:232-243`（§7.4）已记「~~无等价断言~~ **已补齐（2026-09-17，commit `c745212a`）**：… 现由 `apps/cli-ts/scripts/pty_fullscreen_editor_keys.py` 在**全屏视图**上断言 … `EDITOR_KEYS_OK: True`」；`CURRENT_STATE.yaml:41`(b) 同。
- **核查命令与输出【实测】**：

```text
$ ls apps/cli-ts/scripts/pty_fullscreen_editor_keys.py
apps/cli-ts/scripts/pty_fullscreen_editor_keys.py
$ grep -rn 'BACKSPACE_DELETES_PREVIOUS\|CTRL_D_DELETES_FORWARD\|PASTE_CRLF_IS_ONE_BREAK' \
    apps/cli-ts/scripts/pty_fullscreen_editor_keys.py | wc -l
3
```
（断言存在；我**没有重跑**这个 pty 脚本，信号是否仍为 True 属于 §6。）

- **建议改法**：§16.3 改为"曾无等价断言的三项已于 `c745212a` 在全屏视图上补齐（见 `pty_fullscreen_editor_keys.py`）"。

### C5. `TUI-INK-RETIREMENT-PREP-2026-09-17.md` §5 的 P3a-2 表述

- **位置**：`:158-160`
- **原文要点**：「P3a-2（更正 2026-09-17：`awaiting_approval` 字段已在分支上实现——`21d842c5` 引入、`9dabc0e2` 改名；**未推**，且缺 GC/CTO gate 与契约 minor 版本决定，`SURFACE_PROTOCOL_VERSION` 仍为 `1.1`）」
- **为什么过时**：「未推」在写下时就已经不对（`CURRENT_STATE.yaml:41` 自己更正过），现在更进一层：**已合并 main**（见 A1）。
- **建议改法**：`未推` → `已推并已合并 main（PR #69 / 03ac66b5）`；后半句（缺 GC/CTO gate、协议仍 1.1）保持不动 —— 那部分是对的。

### C6. `AB-P3A-MULTIAGENT-TASK-TREE-2026-09-16.md` 说 P3a-2 "暂不做 / 未做"

- **位置**：`:38`、`:95`，以及头部 `:3` 的状态串
- **原文要点**：`:38`「**P3a-2（可选，暂不做）**：若确需在树内直接显示 `pending_approval_count`/`label` … 再走附加字段 `1.2`」；`:95`「树内**不显示** pending 审批计数（需 P3a-2 附加字段 `1.2`，**未做**）」；`:3`「DESIGN_ONLY / **IMPLEMENTED_IN_REVIEW** / **AWAITING_INDEPENDENT_REVIEW_AND_CTO_GATE**」
- **为什么过时**：`awaiting_approval`（即 P3a-2 的那个附加字段）现在在 main 上，且树里已经消费它（见 A1 的四行实测）。
- **需要协调者判断**：`GC-P3-MULTIAGENT-TASK-TREE-2026-09-16.md:4` 的 `DESIGN_ONLY / DOCS_ONLY / AWAITING_CTO_GATE / NO_IMPLEMENTATION_AUTHORITY` 作为"GC 层仍未被 CTO 通过"的**声明**可能是合法的；但它与"实现已在 main"并存会误导读者。我不单方面判它是过期陈述，**建议由协调者/CTO 决定**是补一句状态说明还是保留。

### C7. `STAGE2-PATH-A-MIGRATION-PLAN-2026-09-15.md` 头部状态

- **位置**：`:4`「**状态**：`DRAFT / RECOMMEND_ONLY / AWAITING_FOUNDER_SCOPE`」
- **为什么过时**：同文件 §14/§15/§16 记 Stage 2f2/2f3/2f4 全部完成（见 A13 的输出）。
- **建议改法**：改为 `EXECUTED_2026-09-15 (Stage 2a-2f4 DONE; 2f4 sweep recorded in §16)`。

### C8. `codebase_index.md`（Updated 2026-07-26）的三处结构性问题

- **`:112`（§5 `apps/cli/` 段）**：「The supported terminal entry is the npm `agentos` / `agent-os` / `agent-os-ts` bin (apps/cli-ts, **TS/Ink**)」。
  - **为什么过时**：(a) `TS/Ink` 错 —— Ink 已删（C1 实测），现为 **OpenTUI (Bun)**；(b) 漏掉正式产品名 `noem`（`docs/product/PRODUCT-NAMING-NOEM-2026-09-15.md`：npm bin 仅注册 `noem`，`agentos`/`agent-os`/`agent-os-ts` 是 **deprecated 别名**）。
  - **核查命令与输出【实测】**：

```text
$ grep -n '"bin"' -A6 apps/cli-ts/package.json | head -8
"bin": {
    "noem": "./dist/cli.js",
    "agentos": "./dist/cli.js",
    "agent-os": "./dist/cli.js",
    "agent-os-ts": "./dist/cli.js"
  },
```

- **§2 顶层地图（`:22-40`）缺 `apps/cli-ts/`**：该表列了 `apps/api_server/` 与 `apps/cli/`，**没有任何一行**指向 `apps/cli-ts/`（唯一用户入口）、`apps/runtime_daemon/`、`apps/macos/`、`domain_packs/data_agent/`。
  - **核查命令与输出【实测】**：

```text
$ ls apps/
api_server  cli  cli-ts  macos  runtime_daemon
$ grep -n 'apps/cli-ts\|runtime_daemon\|apps/macos\|domain_packs/data_agent' codebase_index.md | wc -l
0
```

- **§3 契约表（`:46-60`）缺 `surface.py`**：Surface 协议的唯一契约（`SURFACE_PROTOCOL_VERSION` 所在）不在表里；`mandate.py`/`srl_*.py`/`responsibility.py`/`outcome_portfolio.py` 等同样缺席。
  - **核查命令与输出【实测】**：

```text
$ grep -c 'surface.py' codebase_index.md
0
$ grep -n 'SURFACE_PROTOCOL_VERSION' packages/contracts/src/agent_os_contracts/surface.py
14:SURFACE_PROTOCOL_VERSION = "1.1"
```

- **§4 Agent Core 表（`:68-92`）缺 `surface_runtime.py`**：
  - **核查命令与输出【实测】**：

```text
$ ls -la packages/os_core/src/agent_os_core/surface_runtime.py
-rw-r--r--@ 1 mima1234  staff  20648 Sep 18 09:27 packages/os_core/src/agent_os_core/surface_runtime.py
$ grep -c 'surface_runtime' codebase_index.md
0
```

- **是否违反 index 自己的更新规则**：`codebase_index.md:247` 说「只在 **major module / package / public entry point / authority file** 增删或重新分类时更新」。`apps/cli-ts` 成为唯一用户入口、Ink 退役、产品改名 Noem，**都属于"公共入口变化"**，正是该更新的情形。这条我判为**过期**，而不是"index 本来就不该记这些"。
- **注意**：`codebase_index.md:157` 明确写「Test counts and verification dates live only in `docs/CURRENT_STATE.yaml`」——所以 index 里**没有**测试数字是设计意图，**不是**缺陷（避免误报）。

### C9. `docs/PROJECT_PLAN.md`（Updated 2026-08-11）

- **`:26`**：`CANONICAL-CONVERGENCE-2026-07-15` 的 `Status: FEATURE_BRANCH_READY_FOR_INDEPENDENT_REVIEW / DOCS_ONLY / NOT_MERGED`。
  - **核查【实测】**：

```text
$ git merge-base --is-ancestor 4ee868d5 origin/main && echo IN_main || echo NOT
IN_main
$ git branch -r --list 'origin/codex/canonical-convergence-*'
  origin/codex/canonical-convergence-20260715
```
  - 该分支 tip 我实测为 **ahead 119 / behind 953**（`git for-each-ref --format='%(ahead-behind:origin/main)'`），即"未合并"字面成立（它的 119 个提交不在 main），但在 main 上已有 4ee868d5。这条**我不判为假**，只列为"需要重述"：`NOT_MERGED` 与"其权威文档提交已在 main"并存会误导。
- **`:83`（P5）** `PUSHED / MAIN_INTEGRATED / UNRELEASED` —— **正确**（实测 807a0590 在 main）。
- **最大的问题（我判为过期）**：这份"authorized sequence"里 **P0-P6 没有任何一条对应终端/Agent CLI 线**，而 2026-09-13 起 cli-ts 是唯一 supported 终端入口、2026-09-17 全屏迁移与 Ink 退役完成。只读 PROJECT_PLAN 的人会得到与 CURRENT_STATE 相反的优先级图景。
  - **核查命令与输出【实测】**：

```text
$ grep -n 'cli-ts\|terminal\|TUI\|Ink' docs/PROJECT_PLAN.md
（无命中）
```
- **建议**：不在本报告内代拟 PROJECT_PLAN 的 P 项（那属于 founder/CTO 授权序列），只提请协调者补一条指向 CURRENT_STATE `active_work` 的说明，或明确标注"本文件只覆盖研究线与 SPINE，终端产品线的授权序列见 CURRENT_STATE/GC"。

---

## 4. D 类：根仓 `docs/agent-cli/`（**只读**审计）

> 根仓 `/Users/mima1234/Documents/AI-Agent-Projects/` 是另一个 git 仓库。我**没有修改**它任何文件，也**没有**在其中执行任何 git 命令；下面全部结论来自本仓 worktree 内的等价测量。

### 4.1 `TERMINAL-DISTRIBUTION-STATUS-2026-09-18.md` —— 本轮的背景件，基线确实过期

**基线字段（`:7`）**：worktree `os-sandbox`、分支 `tui/parity-f-code-highlight`、HEAD `8ab29119b25607e766c155e928875cdc46f97a7c`、`apps/cli-ts/src` 指纹 `96f3874a5e4abaa3b8b02e81fc87c168d8198060`。

- **(a) 落差【实测】**：

```text
$ git rev-list --count 8ab29119..HEAD          # HEAD = 03ac66b5 = origin/main
45
$ git rev-list --count 8ab29119..3a31a65c      # PR #69 分支 tip
44
```

  `CURRENT_STATE.yaml:41` 记录的「32」是 **203b8862** 处的值（`git rev-list --count 8ab29119..203b8862` → 32），不是当前值。

- **(b) 指纹口径不一致（本次最有价值的单一发现）【实测】**：

```text
# 在 apps/cli-ts 内，按该文档字面写的命令：
$ (cd apps/cli-ts && find src -type f | sort | xargs shasum | shasum)
59a1c6b57713dbe704e42e9e3e3b8e7d5808fd8e   # 8ab29119
e95d237b43c1f214386581127e884f7186c42764   # 203b8862
4fe8592bfac44e200eeaaeaf80618bdafaefaf94   # 03ac66b5 (= 今天的 main)

# 在仓库根，用同一算法但含路径前缀：
$ (find apps/cli-ts/src -type f | sort | xargs shasum | shasum)
96f3874a5e4abaa3b8b02e81fc87c168d8198060   # 8ab29119  ← 文档里写的值
```

  结论：文档的**数值**可靠复现（`96f3874a` 确实是 8ab29119 的 `apps/cli-ts/src` 内容指纹），但文档**写的命令**复现出另一个值；而 `CURRENT_STATE.yaml:41` 的"更正"用字面命令去比，于是它写「the same command it used … yields `e95d237b…`」——**两者不是同一个量**，该比较不能成立。两个数字各自都对，比较方法错。
  **建议**：在 §0 的基线里把命令补全为"在**仓库根**执行 `find apps/cli-ts/src -type f | sort | xargs shasum | shasum`"。

- **(c) 指纹当前值【实测】**：`03ac66b5` 上该口径为 `4fe8592b…`（根口径 `7b5279c8…`）→ 文档的基线指纹已过期。

- **(d) §4「cli-ts job 只有 3 个 `run:` 步骤（`:163`/`:172`/`:177`）」【实测】：

```text
# 对 8ab29119：文档说法成立
$ git show 8ab29119:.github/workflows/ci.yml | grep -n 'run:'
163:        run: bun install --frozen-lockfile
172:        run: npm test
177:        run: npm run typecheck

# 对 03ac66b5（今天的 main）：cli-ts job 有 5 个 run 步骤，行号全变
$ grep -n 'run:' .github/workflows/ci.yml
310:        run: bun install --frozen-lockfile
332:        run: npm run test:ci        ← 已从 npm test 换成 test:ci
337:        run: npm run typecheck
365:        run: pip install "sqlglot==30.13.0" ...
372:        run: bash scripts/install_smoke.sh
```

  即"3 步"与"`:163`/`:172`/`:177`"**都已过期**；且第 2 步已不是 `npm test`（改由 `2267e62b` 切换，原因见 `CURRENT_STATE.yaml:995`）。该节由此推出的"二进制不在 CI"这个**结论仍成立**（见 (h)）。

- **(e) §1.2/§3 打包数字 —— 结构对、度量全过期【实测】**（在本仓 `03ac66b5` 上跑 `npm run pack:check`）：

```text
npm notice package size: 76.2 kB          # 文档记 64.6 kB
npm notice unpacked size: 266.9 kB        # 文档记 226.9 kB
npm notice shasum: aa3185d79bafddd5001617467031260f1b8eb067
                                          # 文档记 a57f5b091b48b5d3c1a3a43c4f72f6f8dab6d677
npm notice total files: 44                # 文档记 44  ← 仍成立
$ find dist -type f | wc -l
42                                        # 文档记 42  ← 仍成立
$ find dist -name '*.map' | wc -l
0                                         # 仍成立
```

  原因很直接：`git diff --stat 8ab29119..HEAD -- apps/cli-ts` = **18 files changed, 3648 insertions(+), 131 deletions(-)**，产物必然变大。

- **(f) §4 二进制【实测】**：

```text
$ bun run scripts/compile.ts /tmp/.../noem
  [45ms]  bundle  316 modules
 [200ms] compile
real 0m0.279s
$ ls -la noem → 76,641,906 bytes          # 文档记 76,608,882（差 +32,976）
$ file noem → Mach-O 64-bit executable arm64   # 仍成立
$ ./noem --version → 0.1.0                     # 仍成立
$ ./noem --help | grep -c update → 0           # 仍成立
```

- **(g) §1.1 / §1.2 / §3 的结构性事实仍成立【实测】**：`package.json` 的 `private: true`(:4)、`engines.bun = ">=1.4.0"`(:7-9)、`files: ["dist","!dist/**/*.map","README.md"]`(:10-14)、4 个 bin(:15-20)、脚本区间 `:21-26`、`dist/cli.js` 首行 `#!/usr/bin/env bun`、`bun ./dist/cli.js --version` 与 `node ./dist/cli.js --version` 都为 `0.1.0`、`scripts/compile.ts` **无 `--target`**（`grep -c -- "--target" scripts/compile.ts` → 0）。
- **(h) §4 的 grep 结论仍成立【实测】**：

```text
$ grep -nE "bun run scripts/compile|scripts/compile|npm pack|install -g|npm publish|scripts/e2e|e2e\.sh|--compile" .github/workflows/ci.yml
（无输出，exit 1）
```

  但**注意一个会误导读者的细节**：`scripts/install_smoke.sh`（ci.yml:372）现在会跑 `npm run pack:check`（= `npm pack --dry-run`），只是上面的模式匹配不到字符串 `npm pack`。
- **(i) §7 表格第 3 行的"缺什么"已部分失效【实测】**：原文缺项写「把 `scripts/e2e.sh`（含 pty smoke）纳入 CI，或写等价的 CI 可跑断言；**CI 需 bun + uv/Python 两个运行时**」。"CI 需 bun + uv/Python 两个运行时"**已不再是缺口**：`cli-ts` job 现在有 `actions/setup-python@v5`(:361)、`pip install "sqlglot==30.13.0" …`(:365)、`bash scripts/install_smoke.sh`(:372)，且该步骤在 run 35294406879 上记录 `[install-smoke] 8 passed, 0 failed, 8 checks run`。`scripts/e2e.sh` 本身仍未进 CI（(h) 的 grep 未命中）——**这一半仍成立**。
- **(j) §5 的 doctor 三档实测我没有复现（见 §6），且其行号引用已漂移【实测】**：文档引 `src/doctor.ts:5,39,64-65` 支撑"用故意不存在的 session id + GET，不创建状态"；现在 `PROBE_SESSION` 在 `doctor.ts:66`（`grep -n PROBE_SESSION src/doctor.ts` → `66:`、`166:`），`doctor.ts` 自 8ab29119 起 `+120` 行。四个检查项的名称与数量（descriptor/reachable/auth/protocol）**仍成立**。
- **(k) §0/§10 的"`npm test` 全量 195 例"【实测】**：现在是 **225 例**（`CURRENT_STATE.yaml:42` 与 `:995` 都记了 225，CI run 35294406879 的 `cli-ts` job 为 34 files / 225 pass / 0 fail）。

### 4.2 `TERMINAL-LINE-CONVERGENCE-PLAN-2026-09-17.md`

- **`:7` 基线 `origin/main = 45b38993`【实测】**：

```text
$ git log -1 --format='%h %ad %s' --date=short 45b38993
45b38993 2026-09-17 tui(parity-c2): textarea composer — final (multiline) with corrected docs (#64)
$ git rev-list --count 45b38993..origin/main
69
```

  落后 69 个提交，其中包含 PR #66/#69 等本方案讨论的对象。
- **`:7` 附记「parity 剩余项：`#14 ctrl+r 历史搜索`、`#16 彩色语法高亮`、`#17 主题配色`、`#18 首页/欢迎面板`」——已过期【实测】**：这四项在**同一天**由切片 E/F/G/H 关闭，`docs/product/TUI-PARITY-CHECKLIST-2026-09-16.md:14-19` 的表格四行都写 DONE，`CURRENT_STATE.yaml:36-39` 逐条记录。**例外**：`#17` 的 DONE 只覆盖 header（见 C2）。
- **§0「冻结声明：自本方案起**不再开新并行线**」——与今天的实测不符【实测】**：

```text
$ git worktree list | wc -l
28
# 其中 7 个 worktree 是 2026-09-18 新建、且都从 03ac66b5 出发：
wt-checkpoint-gc[docs/checkpoint-rewind-gc-20260918]  wt-contract-1-2[codex/contract-surface-1-2-20260918]
wt-deny-visible[codex/deny-visibility-20260918]        wt-ops-ratelimit[codex/ops-client-ratelimit-20260918]
wt-session-stop[codex/surface-session-stop-20260918]   wt-state-audit[docs/state-freshness-audit-20260918]
wt-state-pin[docs/state-merge-pin-20260918]            wt-term-eval[codex/terminal-coding-eval-20260918]

$ git for-each-ref --format='%(committerdate:short) %(refname:short)' refs/remotes/origin | awk '$1 > "2026-09-17"'
2026-09-18 origin/docs/terminal-gc-subagents-hooks-mcp-20260918
2026-09-18 origin/main
2026-09-18 origin/tui/parity-f-code-highlight
```

  我**只陈述事实**：该"冻结"作为一项过程约束今天没有成立（`docs/` 线另开了新分支 `origin/docs/terminal-gc-subagents-hooks-mcp-20260918`，head `adb18568`）。是否算违反、如何记账属协调者判断，我不代判。
- **仍然正确的部分**：§1 的分支分类（A 类 ahead 0 / B 类单提交残留）与当前 `git for-each-ref --format='%(ahead-behind:origin/main)'` 的输出**方向一致**（例：`codex/2f2-slim-work-cli-20260915` 0/146、`codex/2f1-delete-chat-20260915` 1/149、`codex/2fc-boundary-20260915` 1/152）。这是本目录里维护得最好的一份。

### 4.3 `DISTRIBUTION-SINGLE-BINARY-EVAL-2026-09-13.md` 与 `GC-TERMINAL-DISTRIBUTION-0-2026-09-13.md` —— **已带更正指针，不算未标注的过期**

- 两份文档正文里确有被取代的陈述：前者 `:36`/`:43`「npm 全局（**需 Node ≥ 20**）」「**27 文件**干净 tarball」，后者 `:23`「Node ≥20 声明」。
- **但两处都已在 2026-09-18 就地加了指针**：前者 `:49-51`（§7）明确写「该文 §8 记录了两处事实差异：tarball 今天为 **44 文件**；CLI 已于 `55f8e3b8` 切到 Bun，`engines.bun>=1.4.0` → 本文 §5/§6 的「npm 全局（需 Node ≥ 20）」**已被取代**」；后者 `:41` 同样写了更正。
- **结论**：**我不把它们报为"过期缺陷"**。这正是"不要为了显得有产出而把正确的东西报成过时"该拦住的误报。唯一可提的小事：更正只加在文件中部/尾部，**没有同步头部状态行**——读者若只看 head 仍会拿到旧口径（同 C1/C7 的形状）。

### 4.4 其他根仓 agent-cli 文档

- `CURRENT-STATE-DELTA-TUI-2026-09-13.md`：头部已自我声明 `PROPOSED_DELTA / NOT_APPLIED`，正文里的 `NOT_MERGED / NOT_PUSHED / NOT_MERGED` 状态串（`:16`/`:23`/`:30`/`:41`）是 2026-09-13 的建议快照，且当时就注明了"待单一写者合并"。**性质**：一份从未被应用、且其建议已被 2026-09-13 之后的实际决策超越的提案。**不判为"假陈述"**，但建议在头部加一句"本 delta 未采纳，勿作为状态引用"。
- `CLI-TS-PARITY-LOG-2026-09-13.md:3`（`PR_6_OPEN / NOT_MERGED`）、`CLI-TS-DEPTH-LOG-2026-09-14.md:3`（`NOT_PUSHED / NOT_MERGED`）、`CONTEXT-SESSION-0-LOG-2026-09-14.md:5`（`NOT_PUSHED / NOT_MERGED`）、`OS-SANDBOX-0-RESULT-2026-09-14.md:4`、`GC-OS-SANDBOX-0`/`CP-AB-OS-SANDBOX-0:4`: 这些都是**日期化的日志/结果件**，状态行带 `COMMITTED_<sha> / BRANCH <name>` 锚点，属于合法的历史记录。**我没有逐条核实**它们的 PR 是否后来合并（那会是 41 份文档的第二轮工作），故**不报为过期**，只在 §6 记为未审计。

---

## 5. 仍然正确的陈述（明确列出，避免误报）

以下是我**实测确认仍然成立**、**不要**在修 freshness 时一起改掉的：

1. **PR #69 相关的四个代码位置行号全部命中**：`packages/contracts/…/surface.py:186`、`apps/api_server/app.py:2703`、`apps/cli-ts/src/contracts.ts:78`、`apps/cli-ts/src/opentui/agent-tree-source.ts:92`（见 A1 输出）。
2. **`SURFACE_PROTOCOL_VERSION` 仍为 `1.1`**，main 与 `origin/tui/parity-f-code-highlight` 一致；因此「加性字段在未升版的协议下发布」这一判断成立（变的只是"分支"→"main"）。
3. **realtime-collab 的 `SURFACE_NOT_IMPLEMENTED` / `SURFACE_RENDERER_NOT_IMPLEMENTED` 未被证伪**：`app.py` 有 conflict projection / collaboration preflight，`apps/cli-ts/src` 无 conflict 渲染（唯一命中是 `session-command.ts:24` 的注释）。
4. **`CURRENT_STATE.yaml:41` 的 STALE-POINTER NOTE 方向正确**：根仓那份 status 件确实落后于代码（我只修正了它的两个数字/口径，见 §4.1(a)(b)）。
5. **根仓 status 件 §1.1/§1.2/§3/§4/§6 的全部结构性事实**：dist=42（全 `.js`、0 个 `.map`）、tarball `total files: 44`、不含 `src/test/scripts`、`private: true`、`engines.bun>=1.4.0`、`files` 三元组、4 个 bin、shebang `#!/usr/bin/env bun`、`node`/`bun` 下 `--version` 都为 `0.1.0`、`compile.ts` 无 `--target`、自更新 0 命中、编译产物 Mach-O arm64（见 §4.1(e)(f)(g)(h)）。
6. **`codebase_index.md:157`「测试数字只存在于 CURRENT_STATE」是设计意图**，index 里没有测试数字**不是**缺陷。
7. **`docs/product/PROJECT_PLAN.md:83`（P5 `PUSHED / MAIN_INTEGRATED / UNRELEASED`）正确**；`:158`（Data Agent donor 物理保留）正确。
8. **`GC-TUI-FULLSCREEN-MIGRATION-2026-09-15.md` 的 §2 更正块（`:24-32`）与 `TUI-INK-RETIREMENT-PREP` 的 §1.1/§7 更正块**：都已就地标注为"更正/历史"，**不算过期**。
9. **`docs/product/TUI-PARITY-CHECKLIST` 的 #11（vim 信号失效）与 §14（浮层渲染缺陷）**：两处都把"所引信号已失效/被撤回"写在原位，是**本仓最诚实的两处写法**，不要改。
10. **`CURRENT_STATE.yaml:50`（tool_failure_visibility_round2 的 macOS 2712/1 vs Linux 2706/7 平台差异、CI run 35272942676 的记录）与 `:45`（CI 文件集 gate）**：方法学与结论我未发现错误；`:45` 里"161/161 已过期"的自我更正方向也是对的（**该文件集计数我没有复测** —— 并发写者正在向 `tests/product` 加用例，本机计数不可比，见 §6）。

---

## 6. 无法核实 / 明确不主张

1. **本机全量 `tests/product` 结果**：我没有跑（约 200s+，且**本 worktree 之外的写者正在并发向 main 之外的树加用例**会污染可比性）。因此 A9 用的是 **CI 证据**，其口径是 **Linux runner、head 精确绑定 03ac66b5**。macOS 本机数字我**没有**主张。
2. **`tests/product_eval` 的状态**：该目录存在（`tests/` 下有 `product_eval`）但**不在 CI 内**（`grep -n product_eval .github/workflows/ci.yml` 无命中）。所以 `CURRENT_STATE.yaml:956` 的 "Product+product_eval" 里 **product_eval 那一半我没核实**，不宣布转绿也不宣布仍红。
3. **根仓 status 件 §1.3 的 `~/.local/bin/{noem,agentos,agent-os,agent-os-ts}` 是否 link 到源码**：不在我的工作目录内、且我不读取用户 home 下的安装物 —— **未核实**。
4. **根仓 status 件 §2 的 `npm view @agent-os/cli-ts version` → 404**：未复测（registry 网络按已知情况不稳定，且该结论另有 `package.json:4 private: true` 的实测支撑 —— 这一半成立）。
5. **根仓 status 件 §1.2 的 `npm install -g --prefix /tmp/... ` 与"无 Bun 时 exit 127"**：未复测（需要真装全局包）。**纪律原因**：§5 的三档 `doctor` 实测我**故意没有复现** —— 它会启动真实 daemon 并可能触及默认 store（`~/.agent-os/`），本仓已有一次真实 provider 打到默认 store 的事故记录，我不重复。
6. **pty 行为脚本的信号值**：C4/C5 引用的 `EDITOR_KEYS_OK` 等 pty 信号我**只核实了断言存在**，**没有重跑**脚本（会起 hermetic daemon，时间成本高且与本次审计目标无关）。
7. **根仓 `docs/agent-cli/` 其余 ~37 份日期化日志/结果件的 PR 合并状态**：未逐条核实。
8. **`docs/product/GC-P3` 的 `AWAITING_CTO_GATE` 是否已成过期陈述**：属 gate/授权判断，见 C6，我把它留给协调者/CTO。
9. **根仓 `docs/CURRENT_STATE.yaml`**（`updated: 2026-09-15`，`latest_integration.agent_os_main: a0c7a604`）：**不在我声明的范围内**（只读、且该文件当前带未提交编辑）。顺带观察：`a0c7a604` 已是 main 的祖先，落后于 03ac66b5；**我不为它出 diff**，仅在此转引。
10. **今天新落盘的 PR #70（head `adb18568`）三份 GC**（`GC-SUBAGENTS-AND-FANOUT-2026-09-18.md`、`GC-TYPED-HOOKS-2026-09-18.md`、`GC-MCP-FORM-AND-BOUNDARY-2026-09-18.md`）：它们**晚于我的基线 03ac66b5**，我的 worktree 里看不到（`ls docs/product/GC-SUBAGENTS*` → 不存在）。**未审计，也不报为"缺失"**。

---

## 7. `docs/CURRENT_STATE.yaml` 建议 diff（**未执行**；协调者独占该文件）

格式：`行号 | 旧 → 新`。长行只给出**被替换的子串**（前缀 `…`/后缀 `…` 表示上下文保留）。所有新值都可用 §1–§4 里的命令复现。

**D1** `:41` —— pin `tui_ink_deleted_slice_k_2026_09_17` CORRECTED 段

```text
old: … it is NOT in origin/main and still MISSING the GC/CTO gate and a contract minor-version decision …
     … so what is missing is the merge into main, not the push - SURFACE_PROTOCOL_VERSION is still 1.1 on both the remote branch tip and main …
new: … it was MERGED into main on 2026-09-18 (PR #69, merge commit 03ac66b5) and still MISSING the GC/CTO gate and a contract minor-version decision …
     … so what was missing was the merge into main, which has now happened; SURFACE_PROTOCOL_VERSION is still 1.1 on both origin/main and the historical branch tip …
```

**D2** `:42` —— pin `tui_runtime_identity_2026_09_18` 末两处

```text
old: Measured now: HEAD = 203b8862, `git rev-list --left-right --count origin/tui/parity-f-code-highlight...HEAD` = 0 0,
     `gh pr view 69` head=203b886206f7de0d003d5bc13c768f8710fead1f, mergeable MERGEABLE, mergeStateStatus CLEAN,
     reviewDecision EMPTY …, state OPEN. implemented/tested on this branch; not merged to main, not released - that part stands.
new: Measured 2026-09-18 after the merge: PR #69 was MERGED (merge commit 03ac66b563e689fd3c87d38eed2aae400989f6d5),
     `git branch -r --contains 203b8862` includes origin/main, and `git rev-list --left-right --count
     origin/tui/parity-f-code-highlight...origin/main` = 0 1. implemented/tested/integrated on main; not released.
```

**D3** `:43` —— pin `workspace_search_scan_cap_honesty_2026_09_18` 末句

```text
old: implemented/tested on this branch; not merged to main, not released.
new: implemented/tested; merged to main via PR #69 (03ac66b5, 2026-09-18); not released.
```

**D4** `:70` —— 顶层 `status`

```text
old: PUSHED: false (push requires separate founder authorization).
new: PUSHED: true (2026-09-18 measurement: the SPINE-1 receipt 807a0590 and the ADR-0059 merge heads ca775d39 /
     1b6b036a are all ancestors of origin/main 03ac66b5).
```
（同一字符串后部已有的 "The integration is PUSHED / MAIN_INTEGRATED / UNRELEASED" 保持不变。）

**D5** `:86` —— `identity.first_vertical`

```text
old: first_vertical: "Data Agent, locally extracted into domain_packs/data_agent under ADR-0054/SPINE-1; unpushed, unmerged and unreleased"
new: first_vertical: "Data Agent, locally extracted into domain_packs/data_agent under ADR-0054/SPINE-1; pushed and main-integrated (SPINE-1 receipt 807a0590), unreleased"
```

**D6** `:4` + `:92` —— 把冻结 receipt 与 live main 分开

```text
old:   origin_main_code_receipt: "3a70592ddee2e24af94f2da52903a5d73386b10d"
new:   installable_agent_surface_reviewed_head: "3a70592ddee2e24af94f2da52903a5d73386b10d"
       origin_main_head_2026_09_18: "03ac66b563e689fd3c87d38eed2aae400989f6d5"

old: :92  status: "MAIN_INTEGRATED_INSTALLABLE_AGENT_SURFACE_AT_3A70592 / TECHNICAL_APPROVE / NOT_RELEASED"
new: :92  status: "MAIN_INTEGRATED_INSTALLABLE_AGENT_SURFACE (capability review head 3a70592d; live origin/main 03ac66b5 as of 2026-09-18) / TECHNICAL_APPROVE / NOT_RELEASED"
```
（`:136` 的 `dated_verification.exact_head: 3a70592d…` **保持不动** —— 那是能力评审的历史锚点。）

**D7** `:19`、`:20` —— `merged_this_turn`

```text
old: :19 … (local no-ff merge 0705de64; no push)
new: :19 … (local no-ff merge 0705de64; since pushed: 0705de64 is an ancestor of origin/main 03ac66b5)

old: :20 … (wave2a spine into main; merge-prep branch 97d15a9d; committed locally, NOT pushed)
new: :20 … (wave2a spine into main; merge-prep branch 97d15a9d; pushed: ancestor of origin/main 03ac66b5)
```
（该段整体是 2026-09-13 的"本轮"清单，建议同时在段首加 `as_of: "2026-09-13"`。）

**D8** `:8`、`:10` —— realtime-collab receipts

```text
old: :8  realtime_collab_fence_merge_receipt: "1ea99cab (… APPROVE round-3; NOT pushed)"
new: :8  realtime_collab_fence_merge_receipt: "1ea99cab (… APPROVE round-3; pushed: ancestor of origin/main 03ac66b5)"

old: :10 realtime_collab_m1b_merge_receipt: "25408138 (… APPROVE round-2; NOT pushed)"
new: :10 realtime_collab_m1b_merge_receipt: "25408138 (… APPROVE round-2; pushed: ancestor of origin/main 03ac66b5)"
```

**D9** `:955`、`:956`、`:996` —— 仓库级绿/红

```text
old: :955 … The last repository-wide run on the prior candidate was 2616 passed/1 skipped/27 failed; dated fixture expiry, frozen-source/environment drift and ledger contamination remain explicit, so full-suite-green is false.
new: :955 … Superseded 2026-09-18: on origin/main 03ac66b5 the governed product gate (pytest tests/product) is CI-green
        (run 35294406879: 2754 collected / 2747 passed / 7 skipped / exit 0; the 7 skips are Linux platform-conditional).
        The historical 2616/1/27 figure describes a 2026-07 candidate and must not be quoted as the current state.

old: :956 … Repository-wide Product+product_eval remains non-green at 2504 passed/1 skipped/7 failed; five failures reproduce on the no-feature baseline and two elapsed/order-sensitive tests pass targeted, but the debt must not be called green.
new: :956 … On 2026-09-18 the tests/product half is CI-green at 03ac66b5 (see above). tests/product_eval is NOT in CI
        (grep -n product_eval .github/workflows/ci.yml → no match), so that half is UNREVIEWED, not green and not red.
        The historical 2504/1/7 figure describes a 2026-07-18 run.

old: :996 caution: "The 2026-07-18 responsibility integration run ended with 2504 passed, 1 skipped and 7 failed. …
        but the repository-wide suite is not green and no Product/research claim may erase that debt."
new: :996 caution: "The 2026-07-18 responsibility integration run ended with 2504 passed, 1 skipped and 7 failed (dated record).
        As of 2026-09-18 the governed tests/product gate is CI-green at origin/main 03ac66b5; tests/product_eval is outside CI
        and its state is unreviewed. No Product/research claim may cite either figure without its date and suite scope."
```

**D10** `:1031-1039` —— `freshness:`

```text
old: freshness:
       checked_at: "2026-07-18T18:10:10+08:00"
       branch: "main"
       canonical_code_head: "24280fc46879a2b4a4f9884af6bf10fb179406e7"
new: research_ledger_freshness:            # renamed: this block is the Research-line freshness record
       checked_at: "2026-07-18T18:10:10+08:00"
       branch: "main"                       # historical; live main is 03ac66b5 (2026-09-18)
       canonical_code_head: "24280fc46879a2b4a4f9884af6bf10fb179406e7"   # ancestor of origin/main, not the head
```
（或者：若不改名，则至少把 `canonical_code_head` 换成一个带日期的新字段，并把 `checked_at` 更新为 2026-09-18。）

**D11** `:65`

```text
old: updated: "2026-09-16T00:00:00+08:00"
new: updated: "2026-09-18T00:00:00+08:00"
```

**D12** `:25` —— provider pin 的 honest limits

```text
old: Honest limits: Anthropic/Gemini streaming verified only against hermetic stubs, not live vendors; macOS `security -w`
     exposes the key via argv unless the keyring extra is installed; no pricing source (cost UNKNOWN); max_tokens
     hardcoded for Anthropic; no per-vendor rate-limit/retry policy.
new: Honest limits: Anthropic/Gemini streaming verified only against hermetic stubs, not live vendors; macOS `security -w`
     exposes the key via argv unless the keyring extra is installed. Superseded 2026-09-14 by the Slice 6-7 commit 632f46c2:
     a pricing source exists via AGENT_OS_PRICING_FILE / ~/.agent-os/pricing.json (provider.py:236) and cost_status is
     KNOWN only when one resolves, otherwise it stays UNKNOWN (provider.py:842) - never a false zero; max_tokens is
     configurable via AGENT_OS_PROVIDER_MAX_TOKENS (provider.py:539, Anthropic default 4096) and retries are bounded via
     AGENT_OS_PROVIDER_MAX_RETRIES (provider.py:543). Still not claimed: live-vendor verification.
```

**D13** `:26` —— Stage 2f 语气

```text
old: apps/cli/__main__.py is being slimmed to the local-authority CLI (work/selfdev) in Stage 2f2-2f3.
new: apps/cli/__main__.py was slimmed to the local-authority CLI in Stage 2f2-2f3 (both DONE 2026-09-15).
old: Remaining: 2f4 (final sweep incl. stale agent_cli string references + doc/state closure).
new: 2f4 (final sweep incl. stale agent_cli string references + doc/state closure) is DONE 2026-09-15 -
     see docs/product/STAGE2-PATH-A-MIGRATION-PLAN-2026-09-15.md §16.
```

**D14（可选，一致性）** `:989` vs `:995`

```text
old: :989 test_commands.product: "PYTHONPATH=packages/contracts/src:packages/os_core/src:. uv run --extra product-test pytest tests/product -q"
new: :989 保持不动，但在 :995 的 ci 字段里注明 CI 用的是 "PYTHONPATH=src:packages/contracts/src:packages/os_core/src" 顺序
     （两者等价，但读者会以为不一致）
```

### 不出的 diff（有意）

- `:9`/`:11` realtime-collab 的 `*_NOT_IMPLEMENTED`：证据不足以证伪（§5.3）。
- `:34`-`:40` 的切片 D-J pin 的测试计数（162/187/209…）：**都是带日期的历史记录**，改动会伪造历史；只有被当作"当前值"引用时才需要澄清（对应建议：在文件顶部或 `test_commands` 处加一句"pin 内计数均为该日快照，当前 CI 计数见 `test_commands.ci`"）。
- `docs/PROJECT_PLAN.md` 新增 P 项：属 founder/CTO 授权序列，不由审计代拟（见 C9）。

---

## 8. 附：本次实测命令与原始输出（可复现清单）

全部在 `.worktrees/wt-state-audit`（`HEAD == origin/main == 03ac66b5`）执行；未启动任何 daemon，未触碰 `~/.agent-os/`。

```text
git rev-parse HEAD                                      → 03ac66b563e689fd3c87d38eed2aae400989f6d5
git rev-parse origin/main                               → 03ac66b563e689fd3c87d38eed2aae400989f6d5
gh pr view 69 --json state,mergedAt,mergeCommit         → MERGED / 2026-09-18T01:12:55Z / 03ac66b5
gh run list --branch main --limit 5 --json headSha,conclusion   → 03ac66b5 success（及 e44ef044/475d20cc/04ff1fa7/c5085f14 success）
gh run view 35294406879 --json jobs -q '.jobs[] | "\(.name) \(.conclusion)"'  → cli-ts success / test success
gh run view 35294406879 --log | grep 'tests/product collected|passed'
                                                        → 2754 collected (floor 2500) / 2747 passed, 7 skipped / exit 0

git merge-base --is-ancestor 203b8862 origin/main      → YES
git merge-base --is-ancestor 807a0590 origin/main      → YES
git merge-base --is-ancestor 97d15a9d origin/main      → YES
git merge-base --is-ancestor 1ea99cab origin/main      → YES
git merge-base --is-ancestor 25408138 origin/main      → YES
git merge-base --is-ancestor 0705de64 origin/main      → YES
git merge-base --is-ancestor 3a70592d origin/main      → YES
git merge-base --is-ancestor 24280fc  origin/main      → YES
git merge-base --is-ancestor 4ee868d5 origin/main      → YES
git rev-list --count 3a70592d..origin/main             → 965
git rev-list --count 203b8862..origin/main             → 13
git rev-list --count 8ab29119..HEAD                    → 45
git rev-list --count 8ab29119..203b8862                → 32
git rev-list --count 45b38993..origin/main             → 69
git rev-list --left-right --count origin/tui/parity-f-code-highlight...HEAD → 0 1

git show origin/main:packages/contracts/src/agent_os_contracts/surface.py | grep -n 'awaiting_approval|SURFACE_PROTOCOL_VERSION'
                                                        → 14:1.1 / 186:awaiting_approval
git ls-tree -d --name-only origin/main domain_packs/   → domain_packs/data_agent, domain_packs/developer_agent
grep -n awaiting_approval apps/cli-ts/src/contracts.ts apps/api_server/app.py apps/cli-ts/src/opentui/agent-tree-source.ts
                                                        → contracts.ts:78 / app.py:2703 / agent-tree-source.ts:92

# 指纹口径（见 §4.1b）
(cd apps/cli-ts && find src -type f | sort | xargs shasum | shasum)          → 4fe8592bfac44e200eeaaeaf80618bdafaefaf94
(find apps/cli-ts/src -type f | sort | xargs shasum | shasum)                → 7b5279c85d9d10ac7c37525064c66eab8ce7dc7e
# 同两条命令在 8ab29119 的 archive 上：59a1c6b5… / 96f3874a…（后者 = 根仓文档所记值）

grep -n 'run:' .github/workflows/ci.yml                → 310/332/337/365/372（cli-ts job 共 5 步）
git show 8ab29119:.github/workflows/ci.yml | grep -n 'run:' → 163/172/177（3 步，与文档一致）
grep -nE "bun run scripts/compile|scripts/compile|npm pack|install -g|npm publish|scripts/e2e|e2e\.sh|--compile" .github/workflows/ci.yml
                                                        → 无输出，exit 1
grep -n timeout-minutes .github/workflows/ci.yml        → :28 (test,30) / :278 (cli-ts,20)
grep -n product_eval .github/workflows/ci.yml           → 无命中

bun install --frozen-lockfile                           → 59 packages installed, exit 0（bun.lock 未变）
npm run pack:check                                      → 44 files / 76.2 kB / 266.9 kB / shasum aa3185d7…, exit 0
find dist -type f | wc -l                               → 42 ；find dist -name '*.map' | wc -l → 0
head -1 dist/cli.js                                     → #!/usr/bin/env bun
bun ./dist/cli.js --version ; node ./dist/cli.js --version → 0.1.0 / 0.1.0
bun run scripts/compile.ts /tmp/.../noem                → 316 modules / 0.279s / 76,641,906 bytes / Mach-O 64-bit arm64
/tmp/.../noem --version ; --help | grep -c update       → 0.1.0 / 0
grep -c -- "--target" scripts/compile.ts                → 0
grep -rniE "self.?update|selfupdate|auto.?update" src test | wc -l → 0

grep -n 'AGENT_OS_PRICING_FILE|AGENT_OS_PROVIDER_MAX_RETRIES|AGENT_OS_PROVIDER_MAX_TOKENS' packages/os_core/src/agent_os_core/provider.py
                                                        → 236 / 543 / 539
git log -1 --format='%h %ad %s' --date=short -S 'AGENT_OS_PRICING_FILE' -- packages/os_core/src/agent_os_core/provider.py
                                                        → 632f46c2 2026-09-14 provider: … (Slices 6-7)
grep -n 'theme\.footer|theme\.border|theme\.danger|theme\.approvalTitle' apps/cli-ts/src | wc -l → 0
grep -n PROBE_SESSION apps/cli-ts/src/doctor.ts         → 66 / 166
ls apps/cli-ts/src/App.tsx                              → No such file or directory
grep -rn 'from "ink"' apps/cli-ts/src apps/cli-ts/test | wc -l → 0
ls -la packages/os_core/src/agent_os_core/surface_runtime.py → 20648 bytes
grep -c 'surface.py' codebase_index.md                  → 0
grep -c 'surface_runtime' codebase_index.md             → 0
grep -n 'cli-ts|terminal|TUI|Ink' docs/PROJECT_PLAN.md  → 无命中
git worktree list | wc -l                               → 28
git for-each-ref --format='%(committerdate:short) %(refname:short)' refs/remotes/origin | awk '$1 > "2026-09-17"'
                                                        → 4 条（含 origin/docs/terminal-gc-subagents-hooks-mcp-20260918）

git status --short                                      → 空（本报告落盘前；构建产物 dist/ 已在验证后删除）
pgrep -f 'python -m apps\.runtime_daemon'               → 9909/9910/9912/9921
  ps -o pid,ppid,command → 全部属于**另一个 workstream** 的 worktree
  `.worktrees/wt-session-stop`（`/tmp/wtstop/…`），非本任务所起，未终止、不应终止
```

---

## 9. 一句话结论

`docs/CURRENT_STATE.yaml` 的**内容层**在 2026-09-18 被维护得很勤（含大量主动更正段），但**它没有在 PR #69 合并后做一次全局重述**：凡是写着 "not merged to main / not pushed" 的地方现在都错了（8 处），顶层 `status`、`identity.first_vertical` 与 `freshness` 块各自自相矛盾或落后两个月；`tests/product` 的"23 个既存失败"已被 main 的 CI（2754 collected / 2747 passed / 7 skipped / exit 0）证伪。`codebase_index.md` 的结构性缺口（缺 `apps/cli-ts`、缺 `surface.py`、`TS/Ink` 措辞）比任何数字过期都更影响读者。根仓那份分发现状件**方向正确**（结构事实基本都还对），需要修的是**基线、三个打包数字、CI 步数与"CI 缺 Python 运行时"这一条**——外加一个真正值得修的方法学问题：它的**指纹命令与指纹数值不是同一个量**。
