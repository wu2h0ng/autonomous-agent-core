# Agent OS Dual Workbench Slice 1 — Round 3 Independent Review

| Field | Value |
|---|---|
| reviewer | kimi-reviewer-round3 |
| builder | kimi-builder(未采信其记录,全部结论基于亲读代码与亲跑测试) |
| reviewed range | `e4461dbe..c4d8023f`(8 commits,重点 `d3158313`、`c4d8023f`) |
| review time | 2026-09-10T22:40:00+08:00 |
| verdict | **APPROVE_SLICE_1** |

## 亲跑验证结果

| 验证项 | 结果 |
|---|---|
| `node scripts/verify.mjs`(apps/code-oss) | **PASS,45/45**,duration 7.2s |
| `node tests/dual-workbench-slice-1.test.mjs`(e2e) | **PASS,1/1**,duration 11.8s,双窗口 CDP 连接 + 只读投影断言通过 |

与前两轮沙箱环境不同,本轮 loopback 可用,运行时绑定、HTTP 探活、e2e 全部真实执行,非"沙箱受限推断通过"。

## Round 2 P1-1 复审:三层身份证据(c4d8023f)

逐行亲读 `overlay-src/src/vs/agentos/electron-main/interactiveRuntimeLifecycle.ts` 全文(155 行)。

**逻辑结构**:SIGKILL 前依次通过三道独立证据,任一不满足即 fail-closed 不发信号——

1. **启动时间指纹**(L134-137):`ps -o lstart=` 秒级指纹,轮询期早退用;
2. **descriptor 重读**(L138-145):重读文件比对 pid+boot_id,捕获 descriptor 易主;
3. **bearer 认证 HTTP 探活**(L146-148):`probeRuntimeIdentity` 向 descriptor 的 host:port 发 `GET /v1/tasks`,1s `AbortSignal.timeout`。

**fail-closed 完备性核查**(逐项对照代码,非推断):

- 连接拒绝:`fetch` 抛错 → catch → `false` → 不发 SIGKILL ✓
- 探活超时:`AbortSignal.timeout(1000)` 抛 TimeoutError → catch → `false` ✓
- 401 / 任意非 2xx:`response.ok === false` → `false` ✓
- descriptor 重读抛错(文件消失/损坏):→ `'descriptor-unavailable'`,不发信号 ✓
- 指纹为 null(进程已死/不可察)或不匹配:→ `'terminated'`,不发信号 ✓

**绕过路径核查**:

- 唯一 SIGKILL 语句在 L150,位于三道证据之后,无可跳过路径(无早退 return 穿过 probe 到达 kill);
- 生产调用点(patch 010 L39,`app.ts` will-quit 钩子)`beginInteractiveRuntimeTermination(runtimeDescriptorPath)` 不传 deps,使用真实 `processStartFingerprint` + 真实 `probeRuntimeIdentity`;deps 注入仅是模块级测试接缝,不经 IPC 暴露;
- probe 探测的是 SIGTERM 时刻已验证的原始 descriptor 的 socket(而非重读后可能被改写的字段),方向安全:外来进程即使复用 pid,也无法在未持有 bearer 的情况下在原 socket 上答出 2xx。

**结论:Round 2 P1-1 已关闭。** 秒级指纹的同秒穿透窗口由 bearer 探活兜底,三层证据互补无单点。

## 测试有效性:变异测试实证(fail-first)

不止静态推断,本轮在 `/tmp` 隔离副本(不触碰被评审代码)上做了两轮变异实验,复现测试场景的精简版:

| 实验 | 变异 | 结果 |
|---|---|---|
| 基线(未变异) | probe 注入为 false | 进程存活,`wasKilled=false` —— 实现行为正确 |
| 变异体 1 | 删除 SIGKILL 前的 probe 调用 | 外来进程被误杀,`wasKilled=true` —— `skips SIGKILL when the runtime identity probe fails` 测试**会失败** |
| 变异体 2 | 删除指纹比对(只查 null) | 复用 pid 被误杀,`wasKilled=true` —— `never SIGKILLs a reused pid identity` 测试**会失败** |

两个关键回归测试均为真·失败先行。另注意 `escalates to SIGKILL past the deadline` 测试使用真实 HTTP server + 真实 bearer 校验走完整探活路径,并断言 `signalCode === 'SIGKILL'`——若探活链路断裂导致永不升级,该测试也会失败。双向覆盖成立。

## 红线复核(grep + 亲读)

- **bearer 不出主进程**:`bearer`/`token`/`Authorization` 在 overlay `src/vs/agentos/` 中仅出现于 `electron-main/`(mainService、channel 注释、lifecycle probe)与 `common/runtimeTaskCatalog.test.ts`(decoder 拒绝 bearer 形 key 的反向断言);browser/electron-browser 侧零命中。✓
- **无残留 fetchFrom**:`fetchFrom` 在 overlay-src 中零命中;测试显式断言 `typeof bridge.fetchFrom === 'undefined'`。✓
- **IPC 面**:`runtimeTaskCatalogChannel.ts` 仅放行 `listTasks`,其余命令与全部事件 typed throw;channel 只返回解码投影,descriptor 字节与 bearer 不过 IPC。✓
- **只读边界**:16 个写入口 typed reject 与 decoder 防注入测试在 verify 45/45 内通过。✓

## 问题列表

**P0:0。P1:0。**

### P2 / 非阻塞观察项(不阻塞裁决,记入后续切片候选)

1. **probe 失败时返回值语义**:`probeIdentity` 失败返回 `'terminated'`,但此时进程实际仍存活。fail-closed 方向正确(绝不误杀),但结果标签可能误导调用方认为 runtime 已退出,掩盖"wedged runtime 泄漏"事件。建议后续切片增加独立结果值(如 `'identity-unproven'`)或日志记录,便于可观测性。
2. **probe→SIGKILL 残余竞态**:probe 成功到 `process.kill` 之间存在毫秒级窗口,pid 理论上可在此间死亡并被复用。无 pidfd/进程句柄原语则无法彻底消除;当前三层证据已把窗口压到极小,macOS 同用户威胁模型下可接受。
3. **遗留已知项**(前两轮已记录,未变):descriptor `lstat`+`readFile` 的 TOCTOU 间隙,builder 已记入后续切片候选(no-follow open + fstat)。

## 逐项结论汇总

| 审查项 | 结论 |
|---|---|
| 三层证据逻辑严密性 | PASS |
| fail-closed 完备性(超时/401/拒连/非2xx) | PASS |
| 绕过路径(probe 跳过/生产 deps 注入/竞态) | PASS,仅余毫秒级固有窗口(P2-2) |
| 4 个生命周期测试 fail-first 有效性 | PASS(变异测试实证) |
| verify.mjs | PASS 45/45 |
| e2e dual-workbench-slice-1 | PASS 1/1 |
| bearer 红线 / fetchFrom 残留 / IPC 面 | PASS |

## 裁决

**APPROVE_SLICE_1**

理由:P0=0 且 P1=0。Round 2 唯一 P1(pid 复用穿透)已由 `c4d8023f` 的 bearer 认证探活彻底关闭,fail-closed 语义经代码逐行核查与变异测试双重验证;两项要求的测试在本机环境亲跑全绿。三条 P2 观察项为非阻塞改进建议,不影响本切片裁决。
