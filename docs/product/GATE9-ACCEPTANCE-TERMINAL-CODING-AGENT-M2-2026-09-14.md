# Gate 9 Acceptance Record — Terminal Coding Agent M2（补记 / retrospective closure）

- **日期**：2026-09-14
- **类型**：**补记式闭合记录**（retrospective closure record），**非**新的独立评审
- **验收权威**：CTO/founder gate 9
- **状态**：`ACCEPTED_GATE_9 / STANDALONE_ARTIFACT_DEBT_CLOSED_2026_09_14`
- **Track**：Product（治理/记录）

## 1. 本文件为何存在

Gate 8 裁决（`GATE8-VERDICT-TERMINAL-CODING-AGENT-M2-2026-09-11.md`）仅有一处 P2（G8-1：8 处 rev-8/gate-7 旧标签残留），并明确：rev 10 仅做标签修正；**gate 9 为核对性验证（rubber-stamp）**，预期一轮闭合。

Rev 10 已落盘并被接受，但**验收只记录在 commit message + PR #13 合并授权 + CURRENT_STATE** 中，**没有独立落盘的 gate-9 裁决文件**。`CURRENT_STATE.m2_gate9_record_2026_09_13` 已如实记为"acknowledged debt"。本文件**闭合该债务**。

## 2. 精确输入

| 输入 | 位置 / 标识 |
|---|---|
| GC rev 10 | `docs/product/GC-TERMINAL-CODING-AGENT-M2-2026-09-11.md` |
| CP rev 10 | `docs/product/CP-TERMINAL-CODING-AGENT-M2-2026-09-11.md` |
| AB §13 rev 10 | `docs/architecture/T-P-CORE-TERMINAL-CODING-AGENT-ARCHITECTURE.md` |
| rev-10 落盘提交 | `df4f6ef1`（docs(product)，3 文件 +1044；commit msg "CTO gate 9 ACCEPT"；`git merge-base --is-ancestor df4f6ef1 origin/main` = 真） |
| 终端线合并 | PR #13 → `ecc82b13` |
| 支持路径决策 | cli-ts（TS/Ink）= 唯一受支持交互 TUI；Path A=headless；Path B(textual)=frozen（founder 2026-09-11 D1 + 2026-09-13） |
| CURRENT_STATE | `terminal_supported_path_2026_09_13`、`m2_gate9_record_2026_09_13` |

## 3. 本次核对（2026-09-14）

1. **Rev 10 已落盘**：`df4f6ef1` 新增 GC/CP/AB rev 10（+1044 行），为 main 祖先。
2. **G8-1（8 处标签）已闭合**：前向排序引用现指 gate 9（`GC:236`、`CP:29`、`CP:238`）；后向状态头现为 "after gate 8"（`CP:225`）；合同溯源自述改为 "frozen at rev 8; unchanged through rev 10"（`GC:481`、`CP:49`）。剩余 "rev 8"/"gate 7" 字符串均为**历史冻结/门史引用**，非旧前向排序标签。
3. **E1/E2/E3 冻结合同经 rev 10 未变**：GC 自述 rev 10 为 label-only，不改合同/矩阵/阈值/排序（`GC:479-483`）；抽查 GC:71/111/150、CP:49/82/101、AB:298/332/344 一致。
4. **E1/E2/E3 + textual TUI 经独立 exact-diff 评审**（三轮，终审 ACCEPT，2026-09-11），见 `M2-REVIEW-PACKET-2026-09-11.md`。
5. **基板已并入 main**（PR #13）；支持路径已收敛为 cli-ts，textual 冻结为参考。

## 4. 权威与诚实边界

- 本文件为**补记式闭合**，**不含**新的独立评审结论；gate-9 验收权威为 CTO/founder 决策（`df4f6ef1` + PR #13 合并授权），并已在 `CURRENT_STATE.m2_gate9_record_2026_09_13` 记录。
- **不**新增或隐含任何机制、合同、矩阵、阈值、排序变更。
- 原始裁决（gate 8 `REVISE_TO_SPEC`；独立 exact-diff `ACCEPT`）**保留且不被覆盖**。
- 无 parity / autonomy / release 主张。

## 5. 结论

- **Gate 9：ACCEPTED（已在 commit/PR 捕获，本文件补记）。**
- **standalone gate-9 artifact 债务：CLOSED（2026-09-14）。**
- 后续沿已定的支持路径（cli-ts）与 OS-SANDBOX-0 等独立门推进；本记录不再重开 M2 合同。
