# Ink 退役准备工作（2026-09-17）

- **状态**：`PREP_ONLY` —— 本文件记录**已实测的退役前提与删除清单**，尚未删除任何东西。
- **前置事实**：19 项 TUI parity 清单**全部 DONE**（见 `TUI-PARITY-CHECKLIST-2026-09-16.md` §14），#5/#6 为全屏领先 Ink。
- **判定口径**：每一项都要有"在哪、为什么能删、删了会不会带走别的东西"的实测依据；不确定的写成待定，不写成结论。

## 1. 硬约束（**实测**，决定退役顺序）

**全屏客户端目前只能在 bun 下运行，node 下起不来。** 实测（`node --import tsx src/opentui/main.tsx`，22.22.2）：

```
Error: Failed to initialize OpenTUI render library:
OpenTUI native FFI is not available for this runtime yet
    at resolveRenderLib2 (…/@opentui/core/chunk-node-70eg2nhg.js:17805)
    at new CliRenderer2 (…/@opentui/src/renderer.ts:1070)
```

而 `bun 1.4.2` 下 12 个 pty 脚本全部正常运行。当前 `package.json` 是 `"engines": { "node": ">=20" }`、
`bin` 指向 `tsc` 产物 `dist/cli.js`，而 `dist/cli.js` 是 **Ink** 入口。

**推论（重要）**：退役 Ink 不是"删几个文件"，而是**把 CLI 的运行时依赖从 node 换成 bun**。
所以它和 `bun build --compile`、Linux 沙箱属于同一条改动链，**必须先做运行时/打包决策**，
再动入口与删除。本文件只做与该决策无关的准备工作。

> 备注：`@opentui/core/platform/ffi.ts` 里有 "Node FFI backend" 相关文案，且
> `@opentui/core-darwin-arm64` 已安装，所以 node 支持**可能**在后续版本到来；若要在 node 上继续，
> 应先确认这一点，而不是先删 Ink。

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

### 2.3 入口切换（**留到最后**，且依赖 §1 的决策）

`package.json` 的 `bin`（`noem`/`agentos`/`agent-os`/`agent-os-ts` → `./dist/cli.js`）、
`scripts.build`（`tsc -p tsconfig.build.json`）、`engines` 都得跟着改；`dist/` 里还有 Ink 的编译产物
（`dist/App.js`、`dist/cli.js`、`dist/HomeView.js`、`dist/ComposerView.js`、`dist/markdown.js`）需要重建。
**在运行时决策确定前不动这些。**

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

## 4. 退役顺序（建议，待运行时决策后执行）

1. **决策运行时**（bun-only / 等 node FFI / `bun build --compile` 产物）—— §1 的闸门。
2. 入口切到 `src/opentui/main.tsx`，打包产物改为 bun 目标；确认 `bin` 四个别名都能跑。
3. 删 §2.1 的全部文件与依赖；删 `test/ink-home-baseline.test.tsx`。
4. 全量单测 + 12 个 pty 脚本 + 冒烟（`bun run src/opentui/main.tsx`）。
5. 更新 `docs/product/TUI-PARITY-CHECKLIST-2026-09-16.md` §2 的结论段与 `docs/CURRENT_STATE.yaml`。

## 5. 与本文件无关但仍未做的（避免混在一起）

- **独立复审** F/G/H 三个切片（改动含共享证据工具与两条被推翻的旧结论）。
- **`VIM_NORMAL_EDIT_SUBMITTED` 复核**：实测 `False`，但 slice-D pin 记录曾两次 `True`，
  #11 的 DONE 证据本身存疑；且该脚本**不设闸门**（恒 exit 0），属打印型信号。
- **可选加固**：palette/selector 条目现在能按内容断言（此前只能断言标题，见 §14.3）；
  cell-diff 残留（帧变矮时留旧字形）。
- 路线图尾部：provider live smoke（需 key）、`bun build --compile`、Linux 沙箱、P3a-2。
