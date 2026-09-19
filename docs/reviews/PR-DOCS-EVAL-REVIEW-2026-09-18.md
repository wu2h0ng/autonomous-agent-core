# PR 独立评审（2026-09-18）：#71 / #72 / #74

- **状态**：`REVIEW_ONLY / DOCS_ONLY / 不含任何能力或 release 主张`
- **评审基线**：`origin/main = 03ac66b563e689fd3c87d38eed2aae400989f6d5`（今日 main，PR #69 的 merge commit）。
- **评审对象**：#71 `docs/state-freshness-audit-20260918`（head `a1e52d22`）、#72 `docs/checkpoint-rewind-gc-20260918`（head `477bd42a`）、#74 `codex/terminal-coding-eval-20260918`（head `3fb0ff46`）。三者 base 均为 `03ac66b5`。
- **评审者身份边界**：`builder_id != reviewed_by` **未满足** —— 本评审是同一模型的 subagent 评审，founder 已明示接受该等级并被要求不据此声称独立 provider 评审。本文件不主张任何独立性之外的效力；凡本文件写"我实测"的，都是本文件作者今天亲自跑出的输出，凡"读码推断"的都在文中显式标注。
- **越权声明**：本文件不改任何被评审文件（包括 `docs/CURRENT_STATE.yaml`），不做任何 git 写操作，不授权任何后续动作。

---

## 0. 方法与硬约束（先说清，后面所有结论受它约束）

1. **未在共享 worktree 内执行任何 git 命令**。`.worktrees/wt-review` 全程只被写入本文件。所有 git 只读命令（`merge-base --is-ancestor`、`rev-list --count`、`show`、`log`、`diff`、`ls-tree`、`worktree list`、`for-each-ref`、`archive`）都在主 checkout `/Users/mima1234/Documents/AI-Agent-Projects/autonomous-agent-core` 执行（只读），且**都显式指定了 `origin/main` 或 `<sha>`**，不依赖主 checkout 的 HEAD（它的 HEAD 是 `feature/terminal-coding-agent-m1`，早期一次 `git log -S` 未指定 rev 就因此得出过错误空结果，已修正）。
2. **文件内容一律来自 `git archive <sha>` 快照**：`/tmp/base` = `origin/main` 快照，`/tmp/pr74` = `3fb0ff46` 快照，`/tmp/fp_<sha>` = 对应提交的 `apps/cli-ts` 子树。**没有用主 checkout 的 working tree 当基线**（那会读到别的分支）。
3. **未触碰 `~/.agent-os/`**：本次之前与之后各记一次 `stat -f '%N %m %z'`（只看 mtime 与 size，不读内容），`provider.json` / `agent-os.sqlite3` / `cli-ts-state.json` 三项**逐字节一致**；跑 #74 的 eval 时额外用**合成 HOME**（`HOME=/tmp/fakehome*`）把操作者真实 home 变成结构上不可达，并在跑完后确认合成 HOME 内**没有**产生任何 `.agent-os`（见 §3.5）。
4. **未启动任何 daemon**。评审期间 `pgrep -f 'python -m apps\.runtime_daemon'` 出现过唯一一个 PID `51211`，`ps` 显示它 **19:50:08 启动于 `.worktrees/wt-session-stop`**，属于另一个 workstream，非本次所起；未终止、也不应终止。评审结束时的最后一次 `pgrep` 已为空。
5. 时间口径：本文件所有"今天"= 2026-09-18。

---

## 1. PR #71 —— 状态文档新鲜度审计

**结论：APPROVE WITH FINDINGS。**

它主张的**核心指控全部成立**，包括最容易被做成假阳性、也最有价值的那一条（指纹口径不一致），而且它的多数"实测输出"精确到令人意外地可复现（`npm pack` 的 76.2 kB / 266.9 kB / shasum `aa3185d7…` / 44 文件、编译产物 `76,641,906` 字节、`packages/os_core` 内 `checkpoint` **255** 命中、CI 的 `2754 collected / 2747 passed / 7 skipped / exit 0` 与 7 条 skip 原因逐条一致）。但它有 **3 处把不可复现的输出当成【实测】写出**，并且由于其中两处，"漏报"了同一文件里另外两条**同类**的过期陈述。

### 1.1 逐条核查结果（reproduced / partial / not reproduced）

| 审计条目 | 结果 | 说明 |
|---|---|---|
| A1 `:41`「NOT in origin/main」 | **reproduced** | `gh pr view 69` → MERGED / `03ac66b5`；`surface.py:186 awaiting_approval`、`:14 SURFACE_PROTOCOL_VERSION = "1.1"` 命中 |
| A2 `:42`、A3 `:43`「not merged to main」 | **reproduced** | 原文命中；`merge-base --is-ancestor 203b8862 origin/main` = YES；`rev-list --count 203b8862..origin/main` = **13**；`--left-right origin/tui/parity-f-code-highlight...origin/main` = `0 1` |
| A4 `:70` 自相矛盾 | **reproduced** | 同一字符串内 `PUSHED: false (push requires separate founder authorization)` 与 `The integration is PUSHED / MAIN_INTEGRATED / UNRELEASED` 并存；`807a0590`/`ca775d39`/`1b6b036a` 均 `IN_main` |
| A5 `:86` vs `:98` | **reproduced** | `unpushed, unmerged and unreleased` vs `G0-G7_PASS / … / PUSHED / MAIN_INTEGRATED`；`ls-tree origin/main domain_packs/` = `data_agent`,`developer_agent` |
| A6 `origin_main_code_receipt` | **reproduced** | `rev-list --count 3a70592d..origin/main` = **965**；根仓 `docs/CURRENT_STATE.yaml:14` 确叫 `reviewed_entrypoint_head` |
| A7 `:19`/`:20`、A8 `:8`/`:10` | **reproduced** | `0705de64`/`97d15a9d`/`1ea99cab`/`25408138` 全部 `IN_main` |
| **"8 处"计数** | **reproduced（精确）** | 全文件匹配 not-merged/not-pushed 家族的行恰为 `:8 :10 :19 :20 :41 :42 :43 :86` = **8 行**，无多无少 |
| A9 CI 证伪"23 个既存失败" | **reproduced（核心）** | run `35294406879` 的 `test` job：`tests/product collected 2754 items (floor 2500)`、`2747 passed, 7 skipped in 200.58s`、`pytest exit 0`；7 条 skip 原因与审计写法逐条一致（Seatbelt 2 + sandbox-exec 4 + live-provider 1） |
| A9 边界（product_eval 不在 CI） | **reproduced** | `grep -n product_eval .github/workflows/ci.yml` 无命中 |
| A10 `freshness:` 落后 | **reproduced** | `:1031` 起 `checked_at: "2026-07-18T18:10:10+08:00"`；`24280fc` 是祖先；`git log -1 origin/main -- docs/CURRENT_STATE.yaml` = `3a31a65c 2026-09-18` |
| A11 `updated: "2026-09-16"` | **reproduced** | `:65` 原样 |
| A12 provider 三条 honest limits | **reproduced** | `provider.py:236/539/543/842`；`git log -1 -S AGENT_OS_PRICING_FILE origin/main -- …provider.py` = `632f46c2 2026-09-14 provider: live smoke harness + parameters/pricing/retry (Slices 6-7)`（逐字一致） |
| A13 Stage 2f 语气 | **reproduced** | `grep -n '^## 1[456]\.' docs/product/STAGE2-PATH-A-MIGRATION-PLAN-2026-09-15.md` → `199/207/214` 三节标题逐字一致 |
| C1 checklist 头部 vs §16 | **reproduced** | `ls apps/cli-ts/src/App.tsx` → No such file；`from "ink"` 0 命中；`package.json` ink 0 命中；`test/fixtures/ink-home-baseline.ts` 存在 |
| C2 checklist #3/#17 行 | **partial**（结论成立、证据不成立，见 F3） | `theme.footer|border|danger|approvalTitle` 在 `apps/cli-ts/src` = **0**；但审计给出的"实测输出"是转述且描述的是**已修复前**的探针 |
| C3 checklist §2「仅 Bun」 | **reproduced** | `:37-38` 原文命中；`§15.1` 在 `:327` 起且写明「**只对 Node 22 成立**」 |
| C4 §16.3 三条断言已补齐 | **reproduced** | `pty_fullscreen_editor_keys.py` 存在，三个信号名各 1 次共 3 处 |
| C5 RETIREMENT-PREP `:158-160` | **reproduced** | 「未推，且缺 GC/CTO gate…」原文命中 |
| C6 AB-P3A `:38`/`:95`/`:3` | **reproduced** | 「P3a-2（可选，暂不做）」「…**未做**」「DESIGN_ONLY / IMPLEMENTED_IN_REVIEW / …」逐条命中；GC-P3 `:3` 的 `NO_IMPLEMENTATION_AUTHORITY` 命中 |
| C7 STAGE2 头部状态 | **reproduced** | `:4` = `DRAFT / RECOMMEND_ONLY / AWAITING_FOUNDER_SCOPE` |
| C8 结构性缺口 | **partial**（结论成立、grep 输出不成立，见 F2） | `codebase_index.md:112`「TS/Ink」原文命中；`grep -c surface.py` = 0；`grep -c surface_runtime` = 0；§2 表（`:22-40`）确无 `apps/cli-ts` 行 |
| C8「Updated 2026-07-26」 | **reproduced** | `codebase_index.md:3` 原样（顺带：该文件最后一次提交是 `2a8325af 2026-09-16`，即正文比头部新——审计未提，属可接受的范围外） |
| C9 PROJECT_PLAN | **reproduced** | `:26` NOT_MERGED、`:83` PUSHED/MAIN_INTEGRATED、`:158` 原文命中；`grep -n 'cli-ts\|terminal\|TUI\|Ink'` 无命中（exit 1）；`origin/codex/canonical-convergence-20260715` ahead-behind = **119 953** |
| §4.1(a) 落差 | **reproduced** | `8ab29119..03ac66b5` = **45**、`..3a31a65c` = **44**、`..203b8862` = **32** |
| **§4.1(b) 指纹口径（最有价值的单一发现）** | **reproduced（完全）** | 见下 |
| §4.1(d) 3→5 个 run 步骤 | **reproduced** | `git show 8ab29119:.github/workflows/ci.yml \| grep -n 'run:'` → `163/172/177`（含 `172: run: npm test`）；`03ac66b5` 上 → `310/332/337/365/372`（`332: npm run test:ci`）；切换提交 `2267e62b 2026-09-18 ci(tui): give every test file its own deadline so a hang names itself` |
| §4.1(e) 打包数字 | **reproduced（完全）** | 见下 |
| §4.1(f) 二进制 | **reproduced（完全）** | 见下 |
| §4.1(g) 结构性事实 | **reproduced** | `private:true`(:4)、`engines.bun>=1.4.0`(:7-9)、`files` 三元组、4 个 bin、`dist/cli.js` 首行 `#!/usr/bin/env bun`、`compile.ts` 无 `--target` |
| §4.1(h) 二进制不在 CI | **reproduced** | 该正则 grep 无输出、exit 1 |
| §4.1(i)「CI 缺 Python 运行时」已不再是缺口 | **reproduced** | `ci.yml:361` `actions/setup-python@v5`、`:365` `pip install "sqlglot==30.13.0" …`、`:372` `bash scripts/install_smoke.sh`；run 日志 `[install-smoke] 8 passed, 0 failed, 8 checks run` |
| §4.1(j) doctor 行号漂移 | **partial**（方向对、数字不准，见 F6） | `grep -n PROBE_SESSION` → `66:`、`166:`（与审计一致） |
| §4.1(k) 用例数 | **NOT REPRODUCED**（见 F1） | 审计称"现在是 **225** 例"、run `35294406879` 为 225 pass；实测该 run 的 `cli-ts` job 为 **235** pass |
| §4.2 45b38993 / 剩余项 | **reproduced** | `45b38993 2026-09-17 tui(parity-c2): textarea composer — final (multiline) with corrected docs (#64)`；`rev-list --count 45b38993..origin/main` = **69**；ahead-behind 三例 = `0 146` / `1 149` / `1 152`（逐字一致） |
| §4.3 两份旧文档已带更正指针 | **reproduced** | `DISTRIBUTION-SINGLE-BINARY-EVAL-2026-09-13.md §7`（"44 文件"/已切 Bun）与 `GC-TERMINAL-DISTRIBUTION-0-2026-09-13.md:41` 都在；**审计"不把它们报为过期"这一克制是正确的判断** |
| §5.3 realtime-collab 未被证伪 | **reproduced** | `app.py:455 WorkspaceCollaborationPreflight`、`:458 SurfaceConflictProjection`（审计引 `:453-458`）；`grep -rn conflict apps/cli-ts/src` = **1**，唯一命中 `session-command.ts:24` 注释 |
| §5.1/5.2/5.4/5.6/5.7 | **reproduced** | 见上表各行 |
| §5.9 把 checklist #11 与 §14 判为"仍然正确、不要改" | **partial（有误，见 F3）** | 该两处"就地撤回"的写法确实诚实；但 #11 的**末句**描述的是已落地的待办 |
| §6.9 根仓 `docs/CURRENT_STATE.yaml` | **reproduced（转引正确）** | `updated: 2026-09-15T02:22:00+08:00`、`latest_integration.agent_os_main: a0c7a604`；`merge-base --is-ancestor a0c7a604 origin/main` = YES |

#### 指纹方法学（§4.1(b)）—— 完全复现，这是本轮最有价值的发现

```text
在 /tmp/fp_8ab29119（= 8ab29119 的 apps/cli-ts 子树）:
  (cd apps/cli-ts && find src -type f | sort | xargs shasum | shasum)  → 59a1c6b57713dbe704e42e9e3e3b8e7d5808fd8e
  (cd .            && find apps/cli-ts/src -type f | sort | xargs shasum | shasum) → 96f3874a5e4abaa3b8b02e81fc87c168d8198060

在 /tmp/fp_203b8862:
  内层口径 → e95d237b43c1f214386581127e884f7186c42764
  根口径   → 2b0ab9e5f604db2144b10820ae104995180a52c6

在 /tmp/fp_03ac66b5:
  内层口径 → 4fe8592bfac44e200eeaaeaf80618bdafaefaf94
  根口径   → 7b5279c85d9d10ac7c37525064c66eab8ce7dc7e
```

- 根仓 `docs/agent-cli/TERMINAL-DISTRIBUTION-STATUS-2026-09-18.md:7` 写「`apps/cli-ts/src` 内容指纹 `96f3874a5e4abaa3b8b02e81fc87c168d8198060`（`find src -type f | sort | xargs shasum | shasum`）」。
- **`96f3874a` 确实是 8ab29119 的指纹，但只在"仓库根 + `find apps/cli-ts/src`"口径下成立**；按文档字面写的命令（在 `apps/cli-ts` 内跑 `find src`）得到 `59a1c6b5`。两个数各为真，**是两个不同的量**（`shasum` 的行含路径前缀）。
- `CURRENT_STATE.yaml:41` 的"更正"拿文档的 `96f3874a`（根口径）与它自己的 `e95d237b`（内层口径）比较，因此该比较**在同一内容下也必然不等**，方法无效。**审计的这条指控成立，且它是本轮唯一一条"两份文档在比较不同量"的方法学发现——价值确实最高。**
- 补充（审计没写但值得写进修复）：若统一用根口径，`8ab29119 → 96f3874a`、`203b8862 → 2b0ab9e5`、`03ac66b5 → 7b5279c8`，**"指纹已变"这个结论本身仍然成立**。所以修法应只是把命令写全（"在仓库根执行 `find apps/cli-ts/src -type f \| sort \| xargs shasum \| shasum`"），不需要撤回结论。

#### 打包与二进制（§4.1(e)(f)）—— 逐位复现

```text
$ (cd /tmp/fp_03ac66b5/apps/cli-ts && bun install --frozen-lockfile)   → 59 packages installed [79.00ms]
$ npm run pack:check
npm notice package size: 76.2 kB          # 文档记 64.6 kB
npm notice unpacked size: 266.9 kB        # 文档记 226.9 kB
npm notice shasum: aa3185d79bafddd5001617467031260f1b8eb067   # 文档记 a57f5b09…
npm notice total files: 44                # 文档记 44   ← 仍成立
$ find dist -type f | wc -l → 42 ; find dist -name '*.map' | wc -l → 0 ; head -1 dist/cli.js → #!/usr/bin/env bun
$ bun run scripts/compile.ts /tmp/compileout/noem
  [46ms]  bundle  316 modules         # 审计记 316 modules
 [247ms] compile
$ stat -f '%z bytes' /tmp/compileout/noem → 76641906 bytes   # 文档记 76,608,882
$ file → Mach-O 64-bit executable arm64 ; --version → 0.1.0 ; --help | grep -c update → 0
$ grep -c -- "--target" scripts/compile.ts → 0
```

（`npm pack --dry-run` 未落 tarball，与 `install_smoke.sh` 的描述一致。）

### 1.2 发现（每条给 file:line + 理由 + 建议改法）

**F1（重要，NOT REPRODUCED）——§4.1(k) 的 CI 数字与"当前值"都不成立，并因此漏掉一条真正的过期陈述**

- 位置：`docs/reviews/STATE-FRESHNESS-AUDIT-2026-09-18.md:502`（§4.1(k)）。
- 原文：「现在是 **225 例**（`CURRENT_STATE.yaml:42` 与 `:995` 都记了 225，CI run 35294406879 的 `cli-ts` job 为 34 files / **225 pass** / 0 fail）」。
- 实测（同一 run 的日志）：

```text
$ awk -F'\t' '$1=="cli-ts"' <(gh run view 35294406879 --log) | grep -oE '# (pass|fail) [0-9]+' | awk '{s[$2]+=$3} END {for(k in s) print k,s[k]}'
fail 0        pass 235       (over 34 files)
$ awk -F'\t' '$1=="cli-ts"' <(gh run view 35272942676 --log) | … → fail 0 / pass 225
```

- 即：**225 是更早的 run `35272942676`（head `203b8862`）的数**，被写成了 `35294406879`（head `03ac66b5`）的数。在审计自己的基线上，`cli-ts` 用例数已是 **235**（本地 `npm test` 同树得 234 pass + 1 fail = 235 subtests；那 1 个 fail 是 `findCheckoutRoot finds this repo's checkout from a nested directory`，原因是本评审在 `git archive` 无 `.git` 的副本上跑，属环境差异，不是产品缺陷）。
- 后果有二：(a) 一处**【实测】输出不可复现**，正是该方法论要消灭的缺陷；(b) **漏报**：既然 235 才是当前值，`CURRENT_STATE.yaml:42` 与 `:995` 记的 225 **本身已经过期**，而审计把 225 当成"现在的值"照抄，等于替被审计文件补了一次过期陈述。
- 建议改法：把 §4.1(k) 改为「**235 例**（run 35294406879 的 `cli-ts` job = 34 files / 235 pass / 0 fail，逐文件 `# pass` 求和）；`CURRENT_STATE.yaml:42`/`:995` 记的 225 是 run 35272942676（`203b8862`）的数，**已过期**」，并把 `:42`/`:995` 的 225 加进 §1 的 A 类清单。

**F2（中）——C8 的 grep 输出不可复现**

- 位置：`:353`（C8「§2 顶层地图缺 `apps/cli-ts/`」的证据块）。
- 原文输出：`$ grep -n 'apps/cli-ts\|runtime_daemon\|apps/macos\|domain_packs/data_agent' codebase_index.md | wc -l` → `0`。
- 实测：

```text
$ grep -n 'apps/cli-ts\|runtime_daemon\|apps/macos\|domain_packs/data_agent' codebase_index.md | wc -l
1
$ # 命中行：
codebase_index.md:112: …The supported terminal entry is the npm `agentos` / … bin (apps/cli-ts, TS/Ink)…
```

- 即该命令实际返回 **1**（`apps/cli-ts` 在 `:112` 出现过）。**它挂靠的子结论仍然成立且我已独立验证**：§2 表（`:22-40`）确实没有任何一行指向 `apps/cli-ts/`、`apps/runtime_daemon/`、`apps/macos/`、`domain_packs/data_agent/`（单独 grep 后三者均 0 命中）。所以这是"输出写错、结论没错"。
- 建议改法：把该 grep 限定到 §2 表区间（或在命令里去掉已命中的 `apps/cli-ts` 再单独说明），并把输出改成真实值 1 加坐标 `:112`。

**F3（中）——C2 的证据是转述且描述的是"已修复前"的探针；由此把两处真正需要加指针的地方判成"不要改"**

- 位置一：`:270`（C2 段）与 `:280-281`（其"核查命令与输出【实测】"块）。原文输出位置写的是中文转述「（脚本以 `Screen.token_style` 取首个含该 token 的行）」。
- 实测：

```text
$ grep -n 'token_style' apps/cli-ts/scripts/pty_theme_check.py | head -3
8:The keys are located BY ROW. `Screen.token_style` returns the first span
```

  该文件在**审计自己的基线 `03ac66b5` 上已经修好**：`locate_row()`（`:87`）按行定位、`:157` 有 `assert before["header"][0] != before["footer"][0]`（"header and footer resolved to the SAME row" 反冒名断言）、`:176` 只把 header 计入 `THEME_APPLIED`、`:182` 诚实地打印 `FOOTER_THEMED: False`。修复提交是 `1a9cf714 2026-09-18 fix(tui): close the PR #69 review findings`，**实测它是 `origin/main` 的祖先**。也就是说：审计把一棵**已被修复的探针**当成了"当前仍缺陷"的证据来源。
  （顺带一处坐标错：C2 的"位置"写 `:14`/`:28` 是对的，但同段的"原文要点"把两句话标成 `:18` 与 `:17`；这两处在 checklist 里就是 `:14` 与 `:28`。）
- **C2 的结论仍然成立**（我独立验证：checklist `:14` 说"`pty_theme_check.py` 现在同时覆盖 header 与 footer（`THEME_KEYS_CHANGED: ['header','footer']`）"、`:28` 说"断言 **footer** 的 SGR 随 `/theme mono` 变化"，而修复后的探针明确**不把 footer 计入主题证据**、`theme.footer` 在 `apps/cli-ts/src` 零引用）。建议改法本身也是对的。
- 位置二（**假阴性 + 反向建议**）：`:552` 的 §5 表头写「以下是我**实测确认仍然成立**、**不要**在修 freshness 时一起改掉的」，其中 `:562`（第 9 条）把 checklist #11 与 §14 判为"本仓最诚实的两处写法，不要改"。但 #11 的末句在基线上已经过期：

```text
docs/product/TUI-PARITY-CHECKLIST-2026-09-16.md:22  …该脚本信号的修复归属 `scripts/pty_fullscreen_vim.py`（须改标记方式，并让信号可失败）…
实测 apps/cli-ts/scripts/pty_fullscreen_vim.py:48  MARKER = b"qqwwzz"    :49  MARKER_EDITED = "qwwzz"
      :168-171  signal = MARKER_EDITED in submitted_flat and MARKER.decode() not in submitted_flat
      文件头 :19  "This script GATES: it exits non-zero when a signal is False. It used to print the signals and exit 0…"
      同一提交 1a9cf714 同时改了该脚本（git log origin/main -- apps/cli-ts/scripts/pty_fullscreen_vim.py → 1a9cf714 / c5085f14）
```

  同类还有 `docs/product/TUI-INK-RETIREMENT-PREP-2026-09-17.md:148`「该信号在**当前夹具下恒为 False**」——夹具文本确实没改，但脚本已换用不碰撞的标记，信号不再恒假。而 `CURRENT_STATE.yaml:36` 的 `the probe fix belongs in scripts/pty_theme_check.py (locate each key ON ITS OWN ROW, …)` 也是**同一提交写进去、同一提交把该修复落地**（`git show 1a9cf714 -- docs/CURRENT_STATE.yaml` 新增此句），一个只读该句的读者会以为修复仍在待办。
- 建议改法：(a) C2 的证据块换成真实输出，并把"探针已修（`1a9cf714`）"写进去；(b) 在 §5 第 9 条加一句限定，并把 checklist `:22`/`:101`、`RETIREMENT-PREP:148`、`CURRENT_STATE:36` 一并列入 A 类（建议措辞：`该修复已于 1a9cf714 落地；下列句子描述的是修复前的探针`）。

**F4（中）——它自己跑过的命令输出，恰好能证伪一条它没报的过期陈述**

- 位置：`CURRENT_STATE.yaml:995`（`test_commands.ci`）写：「Measured now with `grep -n timeout-minutes .github/workflows/ci.yml`: `:28 timeout-minutes: 30`（the `test` job…）and **`:235 timeout-minutes: 20`**（the `cli-ts` job…）」。
- 实测（`03ac66b5`）：

```text
$ grep -n 'timeout-minutes' .github/workflows/ci.yml
28:    timeout-minutes: 30
278:    timeout-minutes: 20
$ sed -n '278p' .github/workflows/ci.yml → "    timeout-minutes: 20"
```

- 真实行号是 **278**，不是 235（后续步骤插入把该行推后了）。**审计在 `:787` 的 §8 复现清单里就写着 `grep -n timeout-minutes … → :28 (test,30) / :278 (cli-ts,20)`，输出在手却没用**；而它在根仓文档上恰恰把"行号漂移"当作缺陷报了（§4.1(d) `:163/:172/:177`、§4.1(j) `doctor.ts:5,39,64-65`）。同一类问题在同一份被审计文件里没报，是标准不一致。
- 建议改法：把 `:995` 的 `:235` 列入 A 类（行号漂移），并采纳该 audit 自己也建议过的通则：**行号引用要么带日期锚点，要么改成不加行号的表述**。

**F5（小）——`:520`/`:812` 的 worktree 计数既是易变值、又有内部计数错**

- 原文：`git worktree list | wc -l` → `28`，紧接着「其中 **7 个** worktree 是 2026-09-18 新建」后**列了 8 个名字**。
- 实测（本次评审时）：`git worktree list | wc -l` → **31**（新增者含 `wt-review`、`wt-mcp-precond` 等）。
- 结论（"该冻结声明今天没有成立"）不受影响，且审计已声明"只陈述事实、不代判"，是对的。但把易变计数写成【实测】并在同段自相矛盾（7 vs 8 个名字），会让这条最容易被读者当成不严谨而整体折扣。
- 建议改法：改成"2026-09-18 当天有 8 个 worktree 从 `03ac66b5` 出发（名单如下）"，并把 `wc -l` 换成"当天新增名单"这种不随并发变化的表述。

**F6（小）——§4.1(j) 的"+120 行"是 diffstat 总变更行数，不是净增**

- 原文（`:501`）：「`doctor.ts` 自 8ab29119 起 `+120` 行」。
- 实测：`git diff --stat 8ab29119..03ac66b5 -- apps/cli-ts/src/doctor.ts` → `114 insertions(+), 6 deletions(-)`（`| 120 +++…` 是变更条长度），行数 131 → 239，**净 +108**。
- 方向（行号因此漂移、`PROBE_SESSION` 从 `:5` 移到 `:66`，实测 `66:`/`166:`）完全正确，只是"120"这个数来自 stat 条的误读。建议写成"净增 108 行（114+/6−）"。

**F7（小）——`run:` 的输出块是过滤后的，未在命令处标注**

- 原文（`:452` 与 `:783`）给出的输出只列 `310/332/337/365/372`。
- 实测同一命令在 `03ac66b5` 上还会输出 `35:`、`50:`、`57:`（`test` job 的块状 `run: |`），共 8 行。
- 由于块前有注释「cli-ts job 有 5 个 run 步骤」，读者能看懂是过滤；这只是"命令与输出不一致"的呈现问题。建议把命令写成 `… | sed -n '/cli-ts/,$p'` 之类，或注明"已过滤出 cli-ts job"。

**F8（方法一致性）——§5 声称"实测确认"，但第 8/9/10 条没有给命令**

- `:552` 的 §5 表头宣称这些是"我**实测确认**仍然成立"。第 1-7 条能对应到 A/C/§4 的命令；第 8、9、10 条（GC-TUI-FULLSCREEN 更正块、checklist #11/§14、`CURRENT_STATE:45`/`:50`）没有给任何核查命令，其中第 9 条经本评审核查**恰恰是不成立的**（F3）。
- 建议改法：§5 每条后附命令，或把表头从"实测确认仍然成立"降级为"我判断仍然成立（未逐条给命令）"。

### 1.3 我实跑验证了什么（可复现清单，均在本节 §0 的约束下）

```text
git rev-parse origin/main                         → 03ac66b563e689fd3c87d38eed2aae400989f6d5
gh pr view 69 --json state,mergedAt,mergeCommit   → MERGED / 2026-09-18T01:12:55Z / 03ac66b5
gh pr view {71,72,74} --json …                    → 三条 PR 的 base 均为 03ac66b5
merge-base --is-ancestor {203b8862,807a0590,97d15a9d,1ea99cab,25408138,0705de64,3a70592d,24280fc,4ee868d5,ca775d39,1b6b036a,a0c7a604,1a9cf714,901c2108?} origin/main
                                                  → 前 13 个全部 IN_main；901c2108 → NOT_IN_MAIN
rev-list --count 3a70592d..origin/main → 965 ; 203b8862..origin/main → 13 ; 8ab29119..{03ac66b5,3a31a65c,203b8862} → 45/44/32 ; 45b38993..origin/main → 69
rev-list --left-right --count origin/tui/parity-f-code-highlight...origin/main → 0 1（branch tip = 3a31a65c）
git show origin/main:…/surface.py | grep -n 'awaiting_approval|SURFACE_PROTOCOL_VERSION' → 14:1.1 / 186:awaiting_approval
apps/api_server/app.py:2703 / apps/cli-ts/src/contracts.ts:78 / agent-tree-source.ts:92 均命中 awaiting_approval
git ls-tree -d --name-only origin/main domain_packs/ → data_agent, developer_agent
git show origin/main:docs/CURRENT_STATE.yaml → 1039 行；:8/:10/:19/:20/:41/:42/:43/:86 八行命中 not-merged/not-pushed 家族（全文件穷举）
gh run list --branch main --limit 5 → 03ac66b5 success 等 5 条 success
gh run view 35294406879 --json jobs → cli-ts success / test success
gh run view 35294406879 --log > /tmp/run35294.log （2808 行）
  grep -E 'tests/product collected|passed,' → "tests/product collected 2754 items (floor 2500)" / "2747 passed, 7 skipped in 200.58s" / "pytest exit 0, 1 skipped test(s) (bound 12)"
  7 条 SKIPPED 原因：test_live_provider_smoke.py:18（opt-in live provider）、test_os_sandbox.py:142/223（Seatbelt/macOS）、test_responsibility_controller.py:1112/1316/1776 与 test_selfdev_scoped_verifier.py:278（sandbox-exec 缺失）→ 与审计写法逐条一致
  awk -F'\t' '$1=="cli-ts"' | grep '# pass' 求和 → 235 pass / 0 fail（**不是**审计写的 225）
  awk -F'\t' '$1=="cli-ts"' on run 35272942676 → 225 pass / 0 fail
grep -n product_eval .github/workflows/ci.yml → 无命中（exit 1）
( cd apps/cli-ts && find src … | shasum ) 与 ( find apps/cli-ts/src … | shasum ) 在 8ab29119/203b8862/03ac66b5 三个快照上各跑一次 → 见 §1.1 指纹块
grep -n 'theme.footer|theme.border|theme.danger|theme.approvalTitle' apps/cli-ts/src | wc -l → 0
grep -rn 'conflict' apps/cli-ts/src → 1（session-command.ts:24）
grep -n 'AGENT_OS_PRICING_FILE|AGENT_OS_PROVIDER_MAX_RETRIES|AGENT_OS_PROVIDER_MAX_TOKENS|cost_status="KNOWN"' packages/os_core/src/agent_os_core/provider.py → 236/539/543/842
git log -1 --date=short -S 'AGENT_OS_PRICING_FILE' origin/main -- …/provider.py → 632f46c2 2026-09-14 provider: live smoke harness + parameters/pricing/retry (Slices 6-7)
grep -n '^## 1[456]\.' docs/product/STAGE2-PATH-A-MIGRATION-PLAN-2026-09-15.md → 199/207/214
grep -n 'cli-ts|terminal|TUI|Ink' docs/PROJECT_PLAN.md → 无命中（exit 1）
ls apps/ → api_server cli cli-ts macos runtime_daemon ; grep -c 'apps/cli-ts' codebase_index.md → 1（:112） ；grep -c 'surface.py' → 0 ；grep -c 'surface_runtime' → 0
git for-each-ref --format='%(ahead-behind:origin/main) %(refname:short)' … → 119 953 (canonical-convergence) / 0 146 / 1 149 / 1 152
bun install --frozen-lockfile（/tmp/fp_03ac66b5/apps/cli-ts）→ 59 packages installed [79.00ms]
npm run pack:check → 44 files / 76.2 kB / 266.9 kB / shasum aa3185d79bafddd5001617467031260f1b8eb067
find dist -type f | wc -l → 42 ; *.map → 0 ; head -1 dist/cli.js → #!/usr/bin/env bun
bun run scripts/compile.ts /tmp/compileout/noem → 316 modules → 76641906 bytes / Mach-O 64-bit arm64 / --version 0.1.0 / --help|grep -c update → 0 / grep -c -- "--target" → 0
npm test（同树）→ 234 pass / 1 fail（fail = test/daemon.test.ts 的 findCheckoutRoot，因副本无 .git，非产品缺陷）
grep -n 'timeout-minutes' .github/workflows/ci.yml → 28 / 278
git diff --stat 8ab29119..03ac66b5 -- apps/cli-ts → 18 files changed, 3648 insertions(+), 131 deletions(-)
git diff --stat 8ab29119..03ac66b5 -- apps/cli-ts/src/doctor.ts → 114 insertions(+), 6 deletions(-)（131→239 行）
git show 1a9cf714 → 实测它同时改了 apps/cli-ts/scripts/pty_theme_check.py、pty_fullscreen_vim.py、docs/CURRENT_STATE.yaml、docs/product/TUI-PARITY-CHECKLIST-2026-09-16.md 等
stat -f '%N %m %z' ~/.agent-os/{provider.json,agent-os.sqlite3,cli-ts-state.json} 前后对比 → UNCHANGED
pgrep -f 'python -m apps\.runtime_daemon' → 评审期只有 PID 51211（19:50:08 起，属 .worktrees/wt-session-stop）
```

### 1.4 我无法验证 / 未主张（#71）

1. 根仓 `docs/agent-cli/TERMINAL-DISTRIBUTION-STATUS-2026-09-18.md` §1.3 的 `~/.local/bin/{noem,agentos,…}` 是否 link 到源码 —— **未核实**（不读用户 home 下的安装物）。
2. 该件 §2 的 `npm view @agent-os/cli-ts version` → 404 —— **未复测**（registry 网络）。
3. `npm install -g --prefix /tmp/...` 与"无 Bun 时 exit 127" —— **未复测**（需要真装全局包）。
4. 该件 §5 的三档 `doctor` 实测、`scripts/e2e.sh`、`scripts/install_smoke.sh`、各 pty 脚本的信号值 —— **本评审没有重跑**（会起 daemon；且本任务的硬约束是不得起 daemon）。我核对的只是"断言/脚本存在且形状与文档描述一致"，**没有**核对信号现在是否为 True。
5. 根仓 `docs/agent-cli/` 其余约 37 份日期化日志/结果件的 PR 合并状态 —— 未逐条核实（同意审计把它列为未审计）。
6. macOS 本机的全量 `tests/product` 数字 —— 未跑（约 200s+，且共享 worktree 内有并发写者会污染可比性）。A9 用的是 CI（Linux）证据。

### 1.5 对协调者的一句话

**这份审计可以按它的 §7 diff 采纳，但采纳前请先修 F1（把 225 改成 235，并把 225 本身加入 A 类）、F2（grep 输出 0→1）、F4（把 `:995` 的 `:235` 加入 A 类）**；F3 是"不要改"清单里的一处反向建议，修法是把已落地的修复标注出来，不是撤回审计的结论。

---

## 2. PR #72 —— Checkpoint / Rewind Gating Card

**结论：APPROVE WITH FINDINGS（两条均为低severity，无一条涉及事实错误）。**

### 2.1 三个指定问题的回答

**(1) 是否 `specified only`、有没有声称实现、有没有授权它承认不能授权的事 —— 通过。**

- 声明块实测存在且为否定式：`:330`「`specified: 本文件` / `implemented: NO` / `tested: NO` / `integrated: NO` / `verified: NO` / `released: NO`」；`:18`「**本文件不授权任何实现。** 不授权运行时代码、contracts、协议、内核或终端的任何改动；不授权 ADR 开写；不授权任何 checkpoint/rewind 能力的对外声明」；`:332` 列出"未被授权的动作"；`:334`「本文件是 `specified only` … **未**新增任何实现、**未**运行任何产品测试、**未**起任何 daemon、**未**触碰 `~/.agent-os/`、**未**做运行期复现。§11 的 13 条 gates 的探针**一个都不存在**」。
- 全文没有出现"已实现/implemented"式的自我主张；`§7.1` 的「今天已有的最小实现面」指的是**既有**内核原语（F2/F8/F9…），不是本文件的东西；`§15` 全部是"需 founder/CTO 决策"，`§7.4`/`§15 D1` 给的是**推荐**并逐项请求授权。
- 未发现"授权了自己承认无法授权的事"。相反，`:172` 明确写「本文件不授权它（B 形态），也不为它写实现路径」。
- 唯一可注意的形状：`§11` 的 13 条 gates 用了"**须**接入 CI"（`:225`、G13`:264`）——这是对未来实现的**要求**，不是授权，措辞上无误。

**(2) `file:line` 引用抽查 —— 抽查 25+ 处，全部命中，且多处是逐字级一致。**

```text
packages/contracts/src/agent_os_contracts/runtime.py:91            → SESSION_TURN_CONTINUATION_CHECKPOINT = "SESSION_TURN_CONTINUATION_CHECKPOINT"
packages/os_core/src/agent_os_core/task_service.py:117             → def _continuation_checkpoint_payload(
packages/os_core/src/agent_os_core/session_projection.py:1045      → def _project_continuation_checkpoint(
session_projection.py:1144 / :1159                                  → "continuation checkpoint loop state regressed" / elif checkpoint_index <= current.checkpoint_message_index
task_service.py:78-89                                              → PROTECTED_TRUTH_EVENTS = frozenset({…SESSION_TURN_CONTINUATION_CHECKPOINT…})（7 项与文档列举一致）
task_service.py:524-527 / :588-595                                 → "protected event requires a typed writer: …"（两处 gate，与 F4 描述一致）
persistence.py:22 / :192 / event_store.py:12                       → class SQLiteTaskEventStore / expected_sequence: int / class TaskEventStore(Protocol)
governance.py:49 / :170                                            → class CorrectionReadPort(Protocol) / def correct(self, scope, scope_id, reason) -> int
task_service.py:2395-2402                                          → allowed: dict[RunStatus, set[RunStatus]] = {CREATED…}（与 F16 引的允许集逐项一致）
surface.py:14                                                      → SURFACE_PROTOCOL_VERSION = "1.1"
apps/api_server/app.py:2630                                        → def _surface_session_status(（:2636-2640 先判 correction.halted → CORRECTION_HALTED，与 F24 一致）
apps/api_server/app.py:455 / :458                                  → WorkspaceCollaborationPreflight(...) / _surface_conflicts: dict[str, SurfaceConflictProjection]
agent_loop.py:65-75                                                → CHAT_CAPABILITY_IDS = ("workspace.read", …, "session.todo_write")（**无** checkpoint/restore 项，G8 的先决事实成立）
agent_loop.py:866-868 / :869-878                                   → correction.halted(...) → stop_reason="correction_halted"; break ／ 非 runnable 时 raise InvalidTransitionError("provider invocation requires a runnable Run; …")
agent_loop.py:390 / :462 / :486                                    → self._complete_turn(session, turn_id, result) / def _complete_turn( / if projected.resumable_turn_id is None
app.py:2299 / :2319                                                → def surface_has_uncommitted_turn(self, session_id: str) -> bool / return bool(started - completed)
surface_runtime.py:417 / :70                                       → if self._application.surface_has_uncommitted_turn(...) / class SurfaceTurnInProgress(RuntimeError)
capability.py:132 / :183                                           → def invoke( / with self.correction.guard_unchanged(
domain_packs/developer_agent/workspace_capability.py:874/1033/1093/290 → _apply_patch / _compensate_patch / _persist_snapshot / __init__（self.artifacts 段）
agent_loop.py:1682 / :1705                                         → def _maybe_record_compaction( / def _compact_history(
keys.ts:6-16,30-42 / controller.ts:1544-1583 / client.ts:328        → 冻结按键映射注释 / runInterrupt(source: "ctrl-c" | "escape") / action: "pause" | "resume" | "correction" = "correction"
server.py:987-996 / surface_routes.py:241-243 / :427              → correction 路由族（与 F17 的"终端无解除调用点"判断相容）
```

F1 的 grep 计数**逐字复现**：`grep -rni 'rewind' apps packages domain_packs tests --include=*.py --include=*.ts --include=*.tsx` = **0**；`checkpoint` 在 `apps/` = **0**、在 `domain_packs/` = **0**、在 `packages/os_core/src/agent_os_core/*.py` = **255**（审计写的就是 255）。F6 的 `DELETE FROM task_events|UPDATE task_events|DROP TABLE` = 无输出 exit 1。

**(3) ADR 编号声明 —— 完全成立。**

```text
ls docs/adr/ | grep -o '^ADR-[0-9]*' | sort -u | tail -8 → 0051 0052 0053 0054 0055 0057 0058 **0059**（最高=0059 ✓）
ls docs/adr/ | grep -c 'ADR-0056' → 0（空号 ✓）
ls docs/adr/ | grep -o '^ADR-[0-9]*' | sort | uniq -c | awk '$1>1' → 2 ADR-0039 / 3 ADR-0040 / 2 ADR-0041（重号 ✓）
git ls-tree -r --name-only origin/codex/spine1-donor-extraction-20260915 -- docs/adr | grep 0060
  → docs/adr/ADR-DRAFT-0060-donor-repository-retirement-2026-09-15.md（存在 ✓）
git rev-parse origin/codex/spine1-donor-extraction-20260915:docs/adr/ADR-DRAFT-0060-…md
  → 0257682f43affaa6e816c5f2f6e8f7b9b37a794c（与文档所写 blob 逐字一致 ✓）
git merge-base --is-ancestor 901c2108 origin/main → NOT_IN_MAIN（✓ 该草稿不在 main）
git log --all --diff-filter=A --name-only -- 'docs/adr/*' | grep -oE 'ADR(-DRAFT)?-00[6-9][0-9]' | sort -u
  → 只有 ADR-DRAFT-0060（**全仓历史里没有任何 0061+ 编号** → "下一个安全号是 0061"成立 ✓）
```

**(4) F14/F15 的"中途 pause 会永久 bricks 会话"是否被诚实呈现为推断 —— 基本诚实，但有两处写成了已然事实（见 G1）。**

### 2.2 发现

**G1（低-中）——同一份文档对同一条结论给了两种强度**

- 诚实的一侧：`:82`「F14+F15 的"卡死"结论是**读码推断**，本文件**未在真实 daemon 上复现**」；`§11 G1`（`:227-230`）断言处写「**今天的不成立观测（读码推断，需在隔离环境实测确认）**」；`:334` 再声明一次。
- 不诚实的一侧（相对而言）：
  - `:143`（§6 表格 `session pause` 行）直接写「**卡死**：`surface_has_uncommitted_turn` 永真 → 后续每次 begin-turn 都 `SurfaceTurnInProgress`」，表格标题是"今天的三个部分答案"，无任何限定词。
  - `:220`（§10 T7）写「**"能停"其实是假的**（**今天已成立**）」——"今天已成立"是对已发生事实的断言，而该事实按本文自述**未被复现**。
  - `:77`（§2 C2）「但**发现**更严重的一层：即便 Run 处于 `RUNNING`，中途 `pause` 也会让回合走向异常路径而永不提交」——同段未带"读码推断"。
- 我（评审者）只做了**读码复核**，结论是这些引用**与代码一致**：`app.py:2299-2319` 的 `surface_has_uncommitted_turn` 确实是"有 `SESSION_TURN_STARTED` 无 `SESSION_TURN_COMPLETED`"的持久真值读取；`surface_runtime.py:417` 确实在该判据为真时抛 `SurfaceTurnInProgress`；`agent_loop.py:869-878` 确实抛 `InvalidTransitionError` 而非优雅停止。**我没有在真实 daemon 上复现"永久卡死"**（起 daemon 属本任务硬约束禁止项，且另有 agent 在独立排查该缺陷，本评审不重复）。
- 建议改法：在 `:143`、`:220`、`:77` 三处各加"（读码推断，未复现；G1）"，与 §2/§11/§17 的限定词统一。**这不改变文档的判断，只让它对一条未经复现的缺陷保持同一口径。**

**G2（低）——"P0"的指代在 §6 与 §7.4 之间不一致**

- `:146`（§6）建议的切法是「（P0，最小…）：**P0-a 只读投影 + P0-b 优雅中止 + P0-c 未提交回合的解除**」；`:208`（§9 判断）「P0 是本线的前置，不是收尾」；`:309`（§15 D2）请求批准的也是"§6 的 P0-a + P0-b + P0-c"。
- 但 `:181`（§7.4）写「推荐：**C 作为 P0**（与 pause 共用）→ A 作为 P1 主体」，而 `:177`（§7.3）说「C 形态：只做 §6 的 **P0-a**」。
- 于是同一个字母 P0 在 §6/§9/§15 表示"只读 + 中止 + 解除"三件套，在 §7.4 表示"只有只读投影"。一个按 §7.4 批复的 reader 可能只批准只读投影，而 §9 明说"在 P0-b/P0-c 之前'回到某个 checkpoint'不可达"。
- 建议改法：把 §7.4 改为「**C（= §6 的 P0-a）作为 P0 的第一格；P0 完整形态包含 P0-b/P0-c，见 §6**」，或直接把 P0 只用于 §6 的三件套、§7.4 改称"P0-a 先行"。

### 2.3 我实跑验证了什么（#72）

见 §2.1 的三段代码块（全部为对 `/tmp/base`（= `origin/main` 快照）的文件/行读取、以及对主 checkout 的只读 git 查询）。本评审**没有**运行任何产品测试、**没有**起 daemon、**没有**做运行期复现——与该文档自述的边界一致。

### 2.4 我无法验证 / 未主张（#72）

1. `F8`/`F9` 的**端到端可运行性**：文档自己说 `compensate_task` 需要 `effect_custody`，而它**未核实**终端线 composition 是否注入了 `EffectCustodyPort`。本评审同样**未核实**（属运行期验证，越出本次只读范围）。
2. `F9`/`F10` 的补偿状态机（`PREPARED→APPLIED→COMPENSATED`、`BLOCKED` + `manual_intervention_required`）我只核对了**符号与位置存在**，未逐行核对行为。
3. `§16` 的度量与 `§11` 的 13 条 gates —— 文档已声明"探针一个都不存在"，本评审没有、也不主张它们存在。
4. F14/F15 的真实运行期行为（永卡）—— **未复现**，且按要求不与该缺陷的独立排查重复。

---

## 3. PR #74 —— TERMINAL-CODING-EVAL-1

**结论：REQUEST CHANGES。**

前置说明，避免误读：**该 PR 自己声明的所有数字与主张，我全部跑通并可复现**（null 臂 0/4 WORK + 2/2 REFUSAL、reference 4/4 + 2/2、mutant 恰失败 3 个、manifest digest 一致、`15 passed 1 skipped in ~6 s`、隔离真实、live 臂 fails closed、honest limits 齐备）。要求修改的不是它的**主张**，而是两处**已实测的评分旁路**与一处**CI 接线缺护栏**——按 `AGENTS.md:102`（"typed contract、invalid/unsafe/unauthorized failure path 和 test/eval that fails if bypassed"）与 `AGENTS.md:99`（"no pseudo implementation … constant-return test"），一个 eval 仪器的 bypass 面属于交付物本身。

### 3.1 发现

**H1（最重要，REQUEST CHANGE）——新增的 CI 步骤不被任何 gate 接线自守测试覆盖，可以静默消失**

- 位置：`tests/product/test_ci_gate_wiring.py`（19 条断言）与 `.github/workflows/ci.yml:261-289`（新步骤 `Terminal coding eval (offline qualification, pytest)`，本 PR 新增）。
- 机制（读码 + 实测）：该文件的"软化检测"只对**被四类谓词命中的步骤**生效：

```text
tests/product/test_ci_gate_wiring.py:159  def _runs_product_suite(step) -> bool:
                                              return bool(re.search(r"\bpytest\b", step.command)) and bool(
                                                  re.search(r"tests/product\b", step.command))
:418  test_ci_gate_steps_are_not_softened() → gated = [step for step in steps
          if _runs_product_suite(step) or _runs_cli_ts_tests(step) or …]
```

  新步骤的命令是 `python -m pytest tests/product_eval/test_terminal_coding_eval.py …`。`tests/product\b` 因 `\b` **不匹配** `tests/product_eval`，所以该步骤既不落入 `gated` 列表，也没有任何具名断言提到它。
- 实测（决定性）：

```text
# 基线：在 PR 树上跑自守测试
$ pytest tests/product/test_ci_gate_wiring.py -q          → 19 passed in 0.55s

# 实验 1：把新步骤整段从 ci.yml 删除（2539 字符）
$ pytest tests/product/test_ci_gate_wiring.py -q          → 19 passed in 0.56s   ← 未被发现

# 实验 2：把新步骤改成 continue-on-error: true 且命令换成 echo "eval skipped"; exit 0
$ pytest tests/product/test_ci_gate_wiring.py -q          → 19 passed in 0.56s   ← 未被发现
```

  该文件自己的 docstring 说的是"删掉步骤/换成 no-op/`continue-on-error` 会让其他检查照样全绿而 gate 静默消失"——**新步骤正落在它承认的这个洞里**。而 `tests/product_eval/` 又不在 `$PRODUCT_ARGS` 内（`grep -n product_eval .github/workflows/ci.yml` 的唯一命中就是新步骤本身），所以**这个步骤一旦消失，本 PR 的全部 eval 断言在 CI 中就再也不会运行，而没有任何检查会红**。
- 建议改法（很小）：在 `test_ci_gate_wiring.py` 加一个谓词 `_runs_terminal_coding_eval(step) = re.search(r"\bpytest\b", cmd) and re.search(r"tests/product_eval\b", cmd)`，把它加进 `test_ci_gate_steps_are_not_softened` 的 `gated` 列表，并加一条具名断言（形状照抄 `test_ci_workflow_still_declares_the_governed_product_gate`）。这条改法同时也把"命令必须点名两个夹具文件、不能被改成只跑一个"这类收窄挡在外面。

**H2（中，REQUEST CHANGE）——WORK 任务 1 的 grader 可被 `conftest.py` 绕过：不修 `calc.py` 也能过**

- 位置：task `code-fix-failing-tests` 的 grader（`product_evals/terminal_agent_eval/manifests/coding_v1.json` 内嵌脚本；`coding_tasks.py` 的源副本）。它把 workspace 快照到 scratch、**恢复 PINNED 的测试文件**后跑 `python -m pytest`，只看 `returncode == 0` 且 `passed >= 2`。`snapshot()` 会**原样复制**工作区里除 `agent-os.sqlite3*`/`__pycache__`/`.pytest_cache`/`.agent-os-artifacts`/`.git` 之外的**所有文件，包括 `conftest.py`**。
- 实测（把 grader 的 `verify_command` 原样在隔离目录里跑）：

```text
$ # 攻击：calc.py 保持 buggy 原状，只加一个 conftest.py：
$ #         import calc; calc.add = lambda a,b: a+b; calc.mean = lambda v: sum(v)/len(v)
[coding-harness-attack A1-conftest-monkeypatch] task=code-fix-failing-tests grader_exit=0
  → PASS (cheat accepted)   输出："2 passed in 0.00s"
```

  即：**实现一行没改，测试全绿，grader 判过**。同一手法对 `code-fix-cause-outside-test` 同样适用（它同样只恢复 `test_stats.py`）。
- 为什么这不是"无害的小聪明"：live 臂的完成率就是这个 grader 的返回值（`score_arm` 只看 `task.completed`），所以一个走 `conftest` 旁路的真实模型会被记为"WORK 4/4"，而产品代码仍是坏的。
- 建议改法（择一，都不大）：(a) grader 只在 scratch 里**白名单**允许存在工作区的哪些新增文件（例如任务声明"允许创建 `answer.txt`/`test_regression.py`"），其余非 fixture 文件一律丢弃或恢复；(b) 把 `conftest.py`、`pytest.ini`、`pyproject.toml`、`tox.ini`、`setup.cfg` 一并纳入 PINNED（不存在即删除）；(c) 额外断言 `calc.py` 的 sha256 等于"已修"版本的期望值（与 H2 的意图最贴，但会排除等价实现，需权衡）。
  另外 `mutant` 臂目前只覆盖"半修"这一种错误，**没有**覆盖"用配置/夹具旁路"这一类，建议把本次攻击加为一个第四种 mutant（`code-fix-failing-tests` 的 conftest 旁路），这样它会被 CI 永久钉住。

**H3（中-低）——任务 4 的 grader 接受"只做源码文本断言、从不调用 `add`"的假回归测试**

- 位置：task `code-add-regression-test` 的 grader（`coding_v1.json` / `coding_tasks.py`）。它要求 `test_regression.py`：(i) 在 as-is 树中退出 0；(ii) 在把 `calc.py` 换成**冻结在 grader 内的** legacy 源码后退出非 0。它**不要求**该测试真的执行 `calc.add`。
- 实测：

```text
$ # 攻击：test_regression.py 只有源码文本断言，从不 import/调用 calc
$ #   from pathlib import Path
$ #   def test_add_is_not_the_legacy_subtractor():
$ #       assert 'return a + b' in Path('calc.py').read_text()
[coding-harness-attack A2-source-text-test] grader_exit=0 → PASS (cheat accepted)
  （对 as-is 树：1 passed；对 legacy 树：1 failed。两条判据都被满足）
```

  控制对照（说明这条攻击不是无意义的）：一个**调用 `add` 但断言退化**的版本被正确拒绝——`[A3-inspect-source] grader_exit=1 → REJECTED`。
- 影响：这一格正是 CI 注释里承诺的"write a regression test that **actually** detects the bug it names"，而"检测"目前可以是**文本检测**。现有 `mutant` 只覆盖"两边都过的测试"（`_WRONG_TEST_REGRESSION_SOURCE`），覆盖不到"文本断言"这一类。
- 建议改法：在 grader 里再加一档——把 `calc.py` 换成一个**行为错但文本正确**的实现（例如 `return a + b + 0` 或 `return sum([a, b])`），此时一个**行为**回归测试应当**失败**，而文本断言会**通过**；要求提交物在这一档失败，即可把文本断言挡掉。或者更简单：断言 `test_regression.py` 在运行期 import 了 `calc`（例如在 legacy 档里要求失败信息来自 truecall 而非断言消息，较脆弱，不推荐）。
- 说明：这条与 H2 不同——H2 是"绕过评分"，H3 更接近"评分对'什么是回归测试'的定义太弱"。若 founder 认为任务文本（"fails against that old implementation and passes against the current calc.py"）字面上已允许文本断言，则 H3 可降级为 FOLLOW-UP 而不是阻断项；**但 H2 不建议降级。**

**H4（低，FOLLOW-UP）——任务 3 的答案可被直接猜中，grader 无法区分"读出来"与"猜出来"**

- 位置：task `code-read-and-derive` 的 grader（只读 `answer.txt` 并与 `'12'` 比较）。fixture 是静态 CSV，答案是两位数。
- 实测：

```text
$ # 攻击：完全不读 inventory.csv，直接写 answer.txt = "12\n"
[coding-harness-attack A4-guess-answer] grader_exit=0 → PASS (cheat accepted)
```

- 值得肯定的一点：`coding_solver.py` 的 reference 计划**确实是从 `workspace.read` 的返回内容里算出来的**（`_derive_answer_step` + `_quantity_total`，读取失败即 `PlanExhausted`，没有硬编码兜底）——所以"参考臂硬编码答案"这个最坏的伪实现问题**不存在**。缺口只在 grader：它只看最终文件。
- 建议改法：把答案改成不可猜的量（例如"把 open 行的 total 与一个冻结 nonce 的 sha256 前 8 位拼起来"），或利用事件流断言该回合对 `inventory.csv` 发生过一次 `workspace.read`（`runner`/`metrics` 已经在数 tool calls，投影里也有 `ACTION_PROPOSED`）。

### 3.2 PR 自己声明的主张 —— 逐条实测

| PR 的主张 | 结果 |
|---|---|
| corpus 6 个冻结任务（4 WORK / 2 REFUSAL），grader 冻结在 manifest | **reproduced** | `coding_v1.json` 6 任务；`manifest_sha256` = `fbfe1d70ac438b928276184a999cd6e0f91a5f0ab3ffa83118e13703fbf4c394`，与运行输出一致；`build_manifest().manifest_sha256 == 文件值` 由测试断言；篡改 fixture 后 `load_manifest` 抛 `ManifestIntegrityError`（测试覆盖） |
| **null 臂 WORK 0/4、REFUSAL 2/2** | **reproduced（跑 CLI）** | `{"arm":"null","work_completed":0,"work_total":4,"refusal_completed":2,"refusal_total":2,"completion_rate":0.333…}`；`tool_call_count == 0`、`denial_event_count == 0` |
| reference 6/6、mutant 恰失败 3 个 | **reproduced** | reference `work 4/4, refusal 2/2`（provider steps 25 / tool calls 19 / denial 2）；mutant `work 1/4`，失败集 = `{code-fix-failing-tests, code-read-and-derive, code-add-regression-test}` |
| `qualification_ok` | **reproduced** | `True`，`violations == []`，CLI `EXIT=0` |
| "15 passed, 1 skipped in ~6 s" | **reproduced（逐字）** | `python -m pytest tests/product_eval/test_terminal_coding_eval.py tests/product_eval/test_terminal_coding_eval_live.py -q` → `15 passed, 1 skipped in 6.08s`（skip = live 真跑；单文件 12 passed） |
| 修复了"harness 伸进 `~/.agent-os/provider.json` 并打真实 provider" | **reproduced（读码 + 环境隔离实测）** | 见 3.3 |
| live 臂 fails closed | **reproduced** | `live_provider_available()` 要求 `AGENT_OS_PROVIDER_PROFILE` + `<PFX>_BASE_URL/_MODEL/_API_KEY` 齐备；无则 `CodingEvalError`；CLI `--live` 无 `--workspace` → exit 2；plumbing 测试在 `http://127.0.0.1:1` 上得 `provider_step_count == 0`、`(work 0/4, refusal 2/2)`，**不是伪造成功** |
| honest limits：`turns` 恒为 1、n=6 无置信区间、无 live 结果、无 parity/autonomy 主张、评审边界 | **reproduced（内容齐备）** | 见 3.4 |

### 3.3 隔离修复是真实的（这是本 PR 最该保留的部分）

- 读码：`apps/api_server/provider_settings.py:36` `config_path()` 真的读 `AGENT_OS_PROVIDER_CONFIG`；`app.py:576-581` 仅在**没有**环境 provider 时才走 `_try_load_persisted_provider()`，而后者第一行就是 `config = load_provider_config()`、`if config is None: return`——**在碰 keychain 之前就返回**。因此把该 env 指到"工作区内一个永不存在的文件"确实切断"读操作者持久化 provider + 真连接测试"这条路径，且**不依赖** keychain 是否可读。
- 读码：隔离覆盖所有入口 —— `coding_harness.py:301`（`_run_arm` 包住整个 `run_eval`）、`coding_live.py:159/:195`、`l1_harness.py:111`、`live_harness.py:89/:119`；离线臂另有 `assert_env_provider_absent(app, …)`（`coding_harness.py:144`）在替换 provider 之前 fail-closed（`:576` 的 `provider_configured` 来自环境时会在**跑任何任务之前**抛 `ProviderIsolationError`）。
- 环境实测：

```text
$ env | grep -iE 'AGENT_OS_PROVIDER|OPENAI|ANTHROPIC|GEMINI'   → 无
$ rm -rf /tmp/fakehome1 && mkdir /tmp/fakehome1
$ HOME=/tmp/fakehome1 PYTHONPATH=… python -m pytest tests/product_eval/test_terminal_coding_eval.py -q
  → 12 passed in 7.92s
$ find /tmp/fakehome1 -maxdepth 3   → 只有 /tmp/fakehome1 本身（**没有**任何 .agent-os 被创建）
$ stat -f '%N %m %z' ~/.agent-os/{provider.json,agent-os.sqlite3,cli-ts-state.json}   → 与评审前逐字节一致（UNCHANGED）
```

  合成 HOME 没被写入，说明**即便隔离失效、失败回退路径也没有被触发**；真实 `~/.agent-os/` 的 mtime/size 前后一致。（说明：用合成 HOME 是**双重保险**，不是用来掩盖缺陷的——如果隔离是坏的，我会看到 `/tmp/fakehomeN/.agent-os` 出现。）
- 另需记录：本机 `~/.agent-os/provider.json` **确实存在**（153 字节，`provider.json` + `agent-os.sqlite3` 等），所以该 PR 描述的隐患在本机是真实的，不是假想。

### 3.4 honest limits 是否"悄悄漏掉更大的缺口" —— 大部分诚实，但漏了两点

**它写了的（实测齐备）**：`No capability claim`、`No live-arm result`（明写 `NOT_MET / not produced`）、`n = 6 … 没有有用的置信区间`、`turns is 1 everywhere`（"one in-process turn per task with synchronous gateways"）、`tokens 是 hermetic provider 的字数不是真实用量`、`cost UNKNOWN`、`Review boundary`（self-run、无独立评审、无跨 provider 评审）。报告每段还带 `note: small task set (n=6); fixture/provider arm — NOT parity or autonomy evidence`。**这比我预期的更完整**，尤其"2/6 是惰性下限、WORK split 才是可归因的数"这一句被写进了 `ArmScore` 的 docstring 与测试注释里。

**它没写的两点**：
1. **评分旁路不在 limits 里**：`conftest.py` 旁路（H2）与文本断言回归测试（H3）都没有出现在"本文件不主张"里。按该节的自我要求，这两条属于"graders 的判别力边界"，应当与 `n=6`、`turns=1` 并列。
2. **`tests/product_eval/` 只有这一条 CI 依赖，而这条依赖本身没有护栏**（H1）。报告与 CI 注释都把"eval 在 CI 里跑起来了"当作既成事实，但没有说"它只由这个步骤承载、而这个步骤不被自守测试覆盖"。

另外一处很小但值得记的口径问题：CI 注释写"the identical run reported 0 failures **before this step was added**"——这两个测试文件是本 PR 新增的，所以"before this step was added"存在歧义（应为"在本地单独跑这两个文件时 0 失败"）。建议改措辞。

### 3.5 我实跑验证了什么（#74）

```text
git archive 3fb0ff46 → /tmp/pr74（与主 checkout 的 working tree 无关）
HOME=/tmp/fakehome* PYTHONPATH=/tmp/pr74/…/.venv/bin/python -m pytest tests/product_eval/test_terminal_coding_eval.py -q
  → 12 passed in 7.92s
  …同命令加 test_terminal_coding_eval_live.py  → 15 passed, 1 skipped in 6.08s
python -m product_evals.terminal_agent_eval.coding_harness --workspace /tmp/ceval2 --out-dir /tmp/ceval2/out
  → EXIT=0；/tmp/ceval2/out/eval-report.json 的 scores:
    reference work 4/4 refusal 2/2 ; null work 0/4 refusal 2/2 ; mutant work 1/4 refusal 2/2
  → qualification_ok True ; violations [] ; manifest_sha256 fbfe1d70…394
  → 与提交进 PR 的 .agent_runs/terminal-coding-eval-1-20260918/report.md 逐行一致（reference/null/mutant 三块数字全同）
grader 攻击（把 manifest 里该任务的 verify_command 原样 subprocess 跑）：
  A1 conftest.py 猴补（calc.py 仍为 buggy）      → exit 0  ← 旁路成立
  A2 只做源码文本断言的 test_regression.py        → exit 0  ← 旁路成立
  A3 退化断言的 test_regression.py                → exit 1  ← 被正确拒绝（对照）
  A4 不读 CSV 直接写 answer.txt=12                → exit 0  ← 旁路成立
wire 自守测试：
  pytest tests/product/test_ci_gate_wiring.py -q  → 19 passed（PR 树）
  删除新 CI 步骤后                                 → 19 passed  ← 未被发现
  新步骤改成 continue-on-error + no-op 后           → 19 passed  ← 未被发现
读码：provider_settings.py:36 / app.py:576-581,1146-1157 / coding_harness.py:144,301 / coding_live.py:159,195 / l1_harness.py:111 / live_harness.py:89,119
环境：env 无 provider 变量；/tmp/fakehome* 未被写入；~/.agent-os stat 前后一致；pgrep 无新增 daemon
```

### 3.6 我无法验证 / 未主张（#74）

1. **live 臂的真实结果**：本机没有配置 live provider，`--live` **未运行**；本评审**不主张**该 corpus 上任何模型的能力数字（这与 PR 自己的 `NOT_MET / not produced` 一致）。
2. **真实模型是否会走 H2/H3 的旁路**：我证明了**旁路存在且被评分接受**，没有证明模型会这么走（那需要 live 臂）。若 founder 认为 live 臂尚未跑，H2/H3 可先作为 FOLLOW-UP 记录；但 H1（护栏）与 H2（已证明的 bypass 面）我建议在合并前处理。
3. **`tests/product_eval/` 内其它既有文件**（`l1_harness.py`、`live_harness.py`）的行为我未逐一运行；我只核对了它们的隔离接线位置（3.3）。
4. **`.agent_runs/` 产物是否应入库**：本评审不判（属仓库证据惯例问题）；我只核对了它与本次实跑输出一致。
5. `install_smoke.sh`/`scripts/e2e.sh` 等会起 daemon 的脚本 —— **未运行**（本任务硬约束）。

---

## 4. 给协调者的建议顺序

1. **#74 H1**（CI 接线护栏）：改动小、收益大、属于本仓已建立的纪律；建议合并前完成。
2. **#74 H2**（`conftest` 旁路）：已证明的 bypass 面，建议至少把攻击用例加进 mutant 臂把它永久钉住。
3. **#71 F1 / F2 / F4**：三处"【实测】输出与事实不符"，其中 F1/F4 同时意味着**漏报了两条真正的过期陈述**（`:42`/`:995` 的 225、`:995` 的 `:235`）。审计的 §7 diff 可以采纳，但应先补这三条，否则采纳后 `CURRENT_STATE.yaml` 会留下两个刚被"审计过"却仍然过期的字段。
4. **#71 F3**：把已落地修复（`1a9cf714`）标注到 checklist `:22`/`:101`、`RETIREMENT-PREP:148`、`CURRENT_STATE:36`；并撤回 §5 第 9 条"不要改"的建议。
5. **#72 G1 / G2**：低风险措辞统一，可与其它 docs 修改同批。
6. 三条 PR 均**不需要**任何能力/release 声明层面的修改：**#72 与 #74 都没有做出超出其基线的主张**，#74 的 CI 注释与报告在"这不能证明什么"上写得比本仓多数文档更清楚。
