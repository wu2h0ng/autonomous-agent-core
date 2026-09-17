# Ink 退役记录（2026-09-17）

- **状态**：`DONE` —— 运行时决策已定（§1.2 默认 Bun），切片 J 完成入口切换，**Ink 本体已删除、`dist` 已重建**
  （§7）。本文件保留为**退役的完整记录**：前提、清单、执行与覆盖代价。
- **前置事实**：19 项 TUI parity 清单**全部 DONE**（见 `TUI-PARITY-CHECKLIST-2026-09-16.md` §14），#5/#6 为全屏领先 Ink。
- **判定口径**：每一项都要有"在哪、为什么能删、删了会不会带走别的东西"的实测依据；不确定的写成待定，不写成结论。

## 1. 运行时事实（**已更正**）与 founder 决策

### 1.1 更正：不是"只能在 bun 下运行"，而是"Node 22 不行"

本文件初版写的是「全屏客户端目前只能在 bun 下运行」。**该结论只对 Node 22 成立，已在同日实测推翻。**

- `@opentui/core` **自带两套 FFI 后端与两个入口**：`index.bun.js` → `createBunBackend(bun:ffi)`，
  `index.node.js` → `createNodeBackend(node:ffi)`；`package.json` 的 `exports` 里有显式的 `"node"` 条件。
  它是**为两边设计的**。
- node chunk 的 `loadBackend()` 在非 bun 运行时 `require("node:ffi")`，失败就静默降级成
  `createUnsupportedBackend`，直到第一次 `dlopen` 才抛 `OpenTUI native FFI is not available`。
  所以那句报错的含义是**"你这个 Node 不会 FFI"**，不是"不支持 Node"。
- `node:ffi` 是 **Node 26.1.0（2026-05-07）**才加的实验模块，`--experimental-ffi` 开启
  （开权限模型时还要 `--allow-ffi`）。Node 22 报 `ERR_UNKNOWN_BUILTIN_MODULE`。
- **实测**（Node 26.9.0，只换运行时、脚本逻辑不动）：`ffi.dlopen` 返回 `{lib, functions}`，
  `lib` 上有 `registerCallback / unregisterCallback / close`，与 `createNodeBackend` 期望**完全吻合**；
  四个 pty 脚本（home / theme / highlight / parity_a）**全部通过，信号与 bun 一致**；
  不加 `--no-warnings` 也通过。详见 §4.1。

**这条错误结论的源头也已定位并更正**：`GC-TUI-FULLSCREEN-MIGRATION-2026-09-15.md` §2 的渲染器对照表
把 OpenTUI 记为"Node 可用 ❌ → **仅 Bun**"，而那次测量是在 **Node 22** 上做的。结论被从"这个 Node 不行"
过度推广成"Node 不行"，随后被本文件与切片 G/J 的记载继承。该表已就地更正并保留原测量。

### 1.2 founder 决策：**默认 Bun**
理由（实测支撑）：Node 这条路要 Node ≥26（当前是 Current、**非 LTS**）+ `--experimental-ffi`
实验开关，且 Node 官方写明该 API"随时可能变"；Bun 不需要任何开关，并且能 `bun build --compile`
出**单文件**（**已实测**：编译产物在 `/tmp` 下完整渲染全屏界面，用户两个运行时都不用装）。
Node 26 那条记为**已验证的备用路径**，待 `node:ffi` 转正后可再切。

> 残余风险已记录：`node:ffi` 仍是实验 API，其形状变化会直接打断 node 路径；
> 这不影响默认的 Bun 路径。

## 2. 删除清单（按依赖实测，非猜测）

### 2.1 Ink 专属 —— 可随 Ink 一起删除

| 文件 | 谁在引用它 | 备注 |
|---|---|---|
| `src/App.tsx` | 仅 `src/cli.tsx` | Ink TUI 主体 |
| `src/cli.tsx` | 仅打包/测试入口 | `import { render } from "ink"` |
| `src/HomeView.tsx` | 仅 `src/App.tsx`（+ 两个测试） | 见 §3 |
| `src/ComposerView.tsx` | 仅 `src/App.tsx` | |
| `src/markdown.ts` | 仅 `src/App.tsx`（+ `test/render.test.ts`） | `marked-terminal` |
| `test/app.test.tsx` | — | 渲染 Ink `<App>` |
| `test/homeview.test.tsx` | — | 渲染 Ink `HomeView`/`StatusBar` |
| `test/render.test.ts` | — | `src/markdown.ts` |
| `test/ink-home-baseline.test.tsx` | — | **本轮新增**，见 §3 |

依赖：`ink`、`marked-terminal`、`ink-testing-library`、`@types/marked-terminal`。

### 2.2 **必须保留**（新路径在用，删了会把全屏视图一起弄坏）

| 模块 | 谁在用 | 为什么容易误删 |
|---|---|---|
| `src/highlight.ts` | `src/opentui/code-highlight.ts`（`EXTENSION_LANGUAGE`） | 文件名像 Ink 专属，其实 #16 的修复依赖它 |
| `src/home.ts` | `src/opentui/home-panel.tsx`、`src/opentui/app.tsx` | 当初特意做成 renderer-neutral 就是为了不被 Ink 带走（切片 G） |
| `src/controller.ts` / `src/client.ts` / `src/theme.ts` / `src/layout.ts` / `src/composer.ts` / `src/keys.ts` … | 两侧共用 | 与视图无关 |

### 2.3 入口切换（**切片 J 已完成**）

`package.json` 的 `engines` 已改为 `{ "bun": ">=1.4.0" }`，`bin` 仍指向 `./dist/cli.js`，但
`src/cli.tsx` 的 shebang 已改为 `#!/usr/bin/env bun`（`tsc` 会把它带进产物），且 `src/cli.tsx`
**不再静态依赖 Ink**：交互式路径改为**动态 import** `src/opentui/mount.tsx`。

`dist/` 里仍是旧 Ink 的编译产物（`dist/App.js`、`dist/HomeView.js`、`dist/ComposerView.js`、
`dist/markdown.js`），**需要在下一次 `npm run build` 时重建**；本切片未重建 `dist`（属发布动作，未做）。

## 3. 本轮已完成的准备工作：把 parity 基线冻结成数据

**问题**：`test/opentui-home.test.tsx`（#18 的漂移守卫）原本在测试时**实时渲染 Ink 的 `HomeView`**
作为对照——也就是让**存活的一侧**依赖**被删除的一侧**。删 Ink 会连 parity 基线一起带走。

**做法**：
- 新增 `test/fixtures/ink-home-baseline.ts`：把实测到的 Ink `HomeView` 输出冻结为数据
  （两套变体：有 model / 无 model 无分支），**不 import ink**，并**把采集输入一起写进 fixture**
  ——没有输入的快照不可复现。同时冻结 `INK_MODE_TIP`（那条实测到的 `shift+tab` 提示）。
- 新增 `test/ink-home-baseline.test.tsx`：**实时重测** Ink 输出与冻结快照是否逐行一致。
  在 Ink 还在的日子里，一旦 Ink 措辞/版式漂移就会失败，迫使**有意识地**更新快照；
  **删 Ink 时把本文件一起删即可**，快照继续独立工作——这个可分离性正是设计目的。
- 改造 `test/opentui-home.test.tsx`：对照改为读冻结快照，**移除 `ink-testing-library` 与 `HomeView` 依赖**。
  现在这个文件在 Ink 删除后仍可运行。
- 另加一条**防空转**断言：漂移守卫是"我方每一行都在基线里"的方向，若基线被清空会**空过**，
  所以显式断言快照不少于 9 行且五个字段行都在。

**证据**：改造后 `test/opentui-home.test.tsx`(9) + `test/ink-home-baseline.test.tsx`(2) = 11 pass；
冻结快照与实时 Ink 渲染**逐行完全一致**（若我手写错，录制测试会立即失败）。

## 4. 切片 J：运行时切到 Bun（**已完成的部分**）

### 4.1 已实现

- **统一入口**：`src/cli.tsx` 现在同时是子命令入口与交互入口。`--version` / `--help` / `doctor` /
  `daemon` / `provider` / `session` / 无头 `-p` **保持不加载** `@opentui/core`（视图是动态 import），
  所以这些路径在**没有原生 FFI 的运行时上仍然可用**——这正是 node-only 单测还能驱动真实入口的前提。
- **视图挂载抽成模块**：新增 `src/opentui/mount.tsx`（`mountFullscreen`）。开发/取证入口
  `src/opentui/main.tsx` 改为薄封装，**行为保持不变**（12 个 pty 脚本仍驱动它）。
- **补齐四项回退**（全屏视图相对 Ink 的真实缺口，实测得出）：
  1. `provider` —— 入口现在会查 `providerStatus()` 并把真实 `provider_id` 传进视图；
     `FullscreenAppProps` 增加了 `provider`。（**这条同时更正了切片 G 的错误结论**，见 §6。）
  2. `initialHistory` / `onHistoryChange` —— 从 `loadState` 载入历史、提交时回调落盘，
     Ctrl-R 搜索因此能跨重启；此前全屏视图每次都从空历史开始且从不持久化。
  3. `controller.themeName` / `.goal` / `.vimMode` —— 此前入口从未从 state 设置，`/theme`、`/goal`、
     vim 偏好在全屏视图里是**被忽略**的。
  4. `--resume <id>` —— 此前全屏入口不处理。
- **可操作的失败提示**：在没有原生 FFI 的运行时上启动交互模式，现在打印
  「需要自带原生 FFI 的运行时 / 请用 Bun 或 Node ≥26 + `--experimental-ffi` / 其余命令仍可用」，
  而不是抛裸栈（实测 node 22 下如此）。
- **打包**：新增 `scripts/compile.ts` + `npm run compile`（`bun build --compile`）。

### 4.2 单文件编译（**已实测**）

`bun build --compile src/cli.tsx` 产出 ~76 MB 单文件，**在 `/tmp` 下（非仓库目录）完整渲染全屏界面**，
无任何原生库报错——说明 `.dylib` 被打进去了，用户**既不需要 bun 也不需要 node**。

**顺带修掉一个真缺陷**：编译产物的 `--version` 原本打出 `0.0.0`（`agentVersion()` 是相对模块读
`package.json`，单文件旁边没有它，静默落到兜底值）。现在由 `--define __NOEM_VERSION__` 在编译期注入，
源码模式与编译产物都返回正确版本（实测两者均为 `0.1.0`）。

### 4.3 证据

- **新增** `scripts/pty_entry_check.py`（`npm run check:entry`）：驱动**真实入口**，断言
  `--version`/`--help` 在 node 下可用、交互模式在 node 下给提示而非裸栈、在 bun 下渲染首页面板与
  provider 行。**PASS**。
- **重写** `scripts/pty_smoke.py`：它原本用 `tsx`(node) 驱动 `src/cli.tsx` 并断言 **Ink** 的字符串，
  切换后必然失败。现在改为在 **Bun** 下驱动真实入口，断言改用 `frame_reader` 重建的**屏幕内容**
  （全屏视图是增量重绘，ANSI 剥离流里 "hello pty" 是碎的，子串断言不可靠），并重新实测了全部字符串。
  新增 Ctrl-C **退出码必须为 0** 的断言。**PASS**。
- 全量单测 **177 + 32 = 209 pass**；**13 个 pty 脚本全绿**（12 个原有 + 新增 entry check）。
- 中文断言需要一条 `cjk_join` 归一化：宽字符占两个单元格，`frame_reader` 会多存一个占位空格，
  屏幕上显示为 `终 端 流 式`。**未改共享的 `frame_reader`**（会牵动其余 12 个脚本的基线），
  在本脚本内显式处理并注明。

### 4.4 后续（**已在 §7 执行**）

切片 J 当时只切了入口与运行时。删除 Ink 与重建 `dist` 随后执行，见 §7；本文件其余部分保留当时
的判断依据，不改写。

## 5. 与本文件无关但仍未做的（避免混在一起）

- **独立复审** F/G/H 三个切片（改动含共享证据工具与两条被推翻的旧结论）。
- **~~`VIM_NORMAL_EDIT_SUBMITTED` 复核~~ 已完成（2026-09-17）**：该信号在**当前夹具下恒为 False**，
  与行为无关——夹具含 `return "hello " + name`，而断言是 `"ello" in submitted and "hello" not in submitted`，
  后半句永假。该夹具文本由 `e44ef044`（切片 E，06:51）加入，晚于切片 D 的 `c5085f14`（05:54），
  所以切片 D 当时记录的 `True` 不据此判为造假，但**已不能再作为 #11 的证据**。
  **行为经独立复测通过**：用不与夹具文本碰撞的标记 `qqwwzz`，以 `frame_reader` 行级重建屏幕断言
  （normal 态未映射键 `q` 不插入；`0`+`x` 后提交 `qwwzz`；`0xizz` 后提交 `zzqwwzz`）。
  脚本信号的修复归属 `apps/cli-ts/scripts/pty_fullscreen_vim.py`：两处都要改——把标记换成不与夹具
  碰撞的串（如 `qqwwzz`），并让信号**可失败**（原先无论行为如何都恒 exit 0，False 也能被当证据引用）。
- **可选加固**：palette/selector 条目现在能按内容断言（此前只能断言标题，见 §14.3）；
  cell-diff 残留（帧变矮时留旧字形）。
- Linux 沙箱、provider live smoke（需 key）、**P3a-2**（更正 2026-09-17：`awaiting_approval` 字段已在分支上
  实现——`21d842c5` 引入、`9dabc0e2` 改名；未推，且缺 GC/CTO gate 与契约 minor 版本决定，
  `SURFACE_PROTOCOL_VERSION` 仍为 `1.1`）。

## 6. 更正：切片 G 写下的 provider 结论是**错的**

切片 G（commit `3d4ad932`）在 `CURRENT_STATE.yaml` 的 pin 与提交信息里写了：

> 「app.tsx … passes provider: null to match Ink exactly (Ink App never receives provider either,
> so both views fall back to openai-compatible - a pre-existing gap in BOTH views, not a regression)」

**两条都不成立**：

- `src/cli.tsx`（Ink 入口）**会**查 `client.providerStatus()` 得到 `providerLabel`（还带 1.5s 超时兜底），
  并把它作为 `provider` 传给 Ink `App`；
- Ink `App.tsx:616` **会**把它继续传给 `HomeView`。

所以 Ink 一直显示**真实** provider id。全屏视图硬编码 `null` 时，`providerValue()`
（`src/home.ts`）会回退成字面量 `openai-compatible`——**这是真回退**，不是"两边同源的缺口"。

**为什么当时的守卫没抓到**：`test/opentui-home.test.tsx` 的防漂移守卫只比对了 `provider = null`
这一档，而那个回退字面量**恰好等于**本机夹具守护进程报告的 `provider_id`，两个方向都无法区分
"转发了真实值"与"丢掉了真实值"。**这个盲区就是错误结论能通过的原因。**

**已做的更正**（记录而非删除旧说法）：
- 冻结基线新增第三档 `INK_HOME_BASELINE_PROVIDER_SET`（`provider: "anthropic"`，实测 Ink 显示
  `provider anthropic · claude-sonnet`），`test/ink-home-baseline.test.tsx` 增加对应录制用例；
- `test/opentui-home.test.tsx` 增加「真实 provider id 必须到达行上、且不得出现回退字面量」的用例，
  同时保留 null 档断言，使两者**可区分**；
- 切片 J 的入口改为传真实 provider（§4.1 第 1 项），回退已修。

**诚实边界**：本机夹具守护进程报告的 `provider_id` 恰好是 `openai-compatible`（等于回退字面量），
所以**端到端 PTY 检查在夹具上区分不出修复前后**；该修复的证明来自内容模型断言 + Ink 基线录制 +
入口代码路径，不是来自 PTY 证据。要端到端区分需要把夹具配成另一个 provider id。

## 7. 执行记录：删除 Ink + 重建 dist（2026-09-17）

### 7.1 与旧清单的两处不一致（按依赖实测更正）

1. **`src/cli.tsx` 不在删除清单里。** 旧清单把它列为 Ink 专属，理由是它 `import { render } from "ink"`；
   切片 J 之后它已不再引用 Ink，并且现在**就是统一入口**。照旧清单删它会删掉整个 CLI。
2. **`test/render.test.ts` 不整文件删。** 旧清单把它记成"`src/markdown.ts` 的测试"，但它实际只
   `import` `src/controller.js`；文件里 7 条用例中**只有 1 条**碰 Ink 的 `renderMarkdown`
   （而且是动态 import）。整文件删会白丢 6 条 controller 断言。做法：只删那 1 条，其余保留。

### 7.2 实际删除内容

`git rm`：`src/App.tsx`、`src/HomeView.tsx`、`src/ComposerView.tsx`、`src/markdown.ts`、
`test/app.test.tsx`、`test/homeview.test.tsx`、`test/ink-home-baseline.test.tsx`。

依赖移除：`ink`、`marked`、`marked-terminal`、`@types/marked-terminal`、`ink-testing-library`。

**保留（易误删）**：`src/highlight.ts`（`src/opentui/code-highlight.ts` 依赖它的 `EXTENSION_LANGUAGE`，
已在文件头加注"文件名像 Ink 专属但全屏视图在用"）、`src/home.ts`、
`test/fixtures/ink-home-baseline.ts`（冻结快照，§3 的设计目的就是让它活过删除）。

### 7.3 先搬走断言再删（不连带丢覆盖）

- `test/homeview.test.tsx` 的 3 条用例里，`shortenPath` 那条**可移植**（该函数现在 `src/home.ts`），
  已**逐字迁移**到 `test/opentui-home.test.tsx`（含 home 相对化、兄弟目录边界、宽度上限、非 home 直通）。
  另两条渲染 Ink 组件，不可移植，由首页面板与漂移守卫用例覆盖。
- `test/render.test.ts` 那条 markdown 断言的**意图**由上线路径的既有检查承担：
  `test/opentui-code-highlight.test.ts`（区间 + 围栏解析）与 `scripts/highlight_render_check.ts`
  （无头渲染 + 反向对照）。已在文件头注明，避免以后被误认为漏测。

### 7.4 覆盖代价（诚实记账）

被删的 `test/app.test.tsx` 有 **16 条集成测试**：palette / @mention / 多行粘贴 / Ctrl-R / selector /
vim×4 / ctrl-p 历史 / 审批 y / 首页首帧 / backspace / ctrl-d。逐项核对新视图：

- **仍有覆盖**：Ctrl-R（`pty_search_check` + viewkeys 单测）、vim（`pty_fullscreen_vim` + `opentui-vim`）、
  palette/selector（`pty_fullscreen_parity_a` + `opentui-overlays`）、审批 y（`pty_smoke` phase3）、
  首页首帧（`pty_home_frame_check`）、ctrl-p 历史（viewkeys 单测；注意 agents 面板激活时被面板占用，
  该情形也有单测）。
- ~~**无等价断言**~~ **已补齐（2026-09-17，commit `c745212a`）**：`backspace`（macOS 发 `0x7f` 删除前一字符）、
  `ctrl-d` 前向删除与多行粘贴（CR/CRLF 归一）三者现由
  `apps/cli-ts/scripts/pty_fullscreen_editor_keys.py` 在**全屏视图**上断言，本次复跑输出：
  `BACKSPACE_DELETES_PREVIOUS: True`（`qwe` → `qw` → `qwr`）、`CTRL_D_DELETES_FORWARD: True`
  （`jkl` + Left + ctrl-d → `jk`）、`PASTE_CRLF_IS_ONE_BREAK: True`（bracketed paste `p` CRLF `q`
  → 两行 `p`/`q`）、`EDITOR_KEYS_OK: True`（exit 0）。断言在 composer 内部行上做行级重建
  （`frame_reader.Screen`），不是对原始字节流做子串匹配。
- **原 verdict 撤回并保留（记录而非删除）**：`c15fdd24` 曾把三者判为 `NOT_MET`，那是**原 harness 的缺陷，
  不是产品缺陷**：①按键后强制重绘读取返回空/部分帧；②`ctrl-d` 的期望本身写错
  （`asd` + Left + ctrl-d 得到 `as` 而不是 `ad`，该断言不可能通过）。`c745212a` **只改脚本**
  （`scripts/pty_fullscreen_editor_keys.py`，73 insertions / 83 deletions），**产品代码未变**——所以
  Ink 退役时"textarea 原生处理这三件事"的假设成立，缺的只是断言。

**结论**：这不是"覆盖率不变"，而是"从 Ink 的集成测试换成了 opentui 单测 + pty 集成"；三条曾经缺失的
断言已于 `c745212a` 在**全屏视图**上补齐（未恢复 Ink 测试）。

### 7.5 顺带发现：`npm install` 本来就装不上（既有冲突，非本次引入）

删依赖时 `npm install` 报 `ERESOLVE`：根项目声明 `react-devtools-core@^8.0.0`，而
`@opentui/react@0.5.11` 的 peer 要求 `^7.0.1`。**与本次删除无关**，是既有不一致（此前 lockfile
大概由 bun 生成，所以没暴露）。已把声明对齐到 peer 要求的 `^7.0.1`，`npm install` 现可正常完成；
随后**整网重跑**确认无回归。

同一过程得到一条**独立佐证**：`@opentui/core@0.5.11` 自己声明
`engines: { bun: ">=1.3.0", node: ">=26.4.0" }` —— 与 §1.1 实测的"Node 26 起可用"完全一致，
也说明 Bun 是官方一等公民。

### 7.6 证据

- **`dist` 重建**：无 Ink 产物（`App/HomeView/ComposerView/markdown.js` 均不在）；`dist/cli.js`
  shebang 为 `#!/usr/bin/env bun` 且可执行；`./dist/cli.js --version` → `0.1.0`；
  **node 下跑子命令仍可用**（视图未加载）。
- **发布产物本身渲染验证**：在 pty 里直接跑 `bun dist/cli.js`，首帧首页面板完整、header 与 provider 行
  都在、无原生库报错。
- 单文件编译复核：`--compile` 后 `--version` → `0.1.0`。
- 单测 **187 pass / 0 fail**（合并为单一分组；此前 209 分两组）。
- **13 个 pty 脚本全绿**（依赖变更后重跑）。
- `package-lock.json` 与 `bun.lock` 均已更新，不再含 `ink` / `marked-terminal`。

### 7.7 注意：`dist` 未被 git 跟踪

`apps/cli-ts/dist` 是构建产物、未纳入版本控制，因此"重建 dist"**不产生提交内容**；它是发布前
必须执行的步骤，本轮已执行并验证。
