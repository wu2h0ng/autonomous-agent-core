# GC + CP/AB — Provider 兼容扩展 + 终端内添加 Provider（rev 1）

- **日期**：2026-09-14
- **状态**：`SLICE_1_MERGED_PR22_FCBE6EF9 / SLICE_2_ANTHROPIC_IMPLEMENTED_LOCAL / AWAITING_INDEPENDENT_REVIEW / SLICE_2_GEMINI_DEFERRED`
- **Founder 决策（2026-09-14）**：批准 **Slice 1 先行**（终端加 provider）；凭证仅内存 env resolver（key 不落盘），已确认。Slice 1 已合并 PR #22（`fcbe6ef9`）。
- **Slice 2（Anthropic 原生）as-built**：新增 `AnthropicMessagesProvider`（`POST {base_url}/v1/messages`，头 `x-api-key` + `anthropic-version`，system/messages/tools/tool_use/tool_result 映射，usage 精确、cost UNKNOWN）；`OpenAICompatibleProvider` 抽出三个传输钩子（`_request_body`/`_transport_headers`/`_parse_completion`）+ `DEFAULT_ENDPOINT_PATH`/`EXPECTED_ENDPOINT_CLASS`/`ADAPTER_KIND` 作为 seam，invocation-binding/credential/failure 机制共用；选择面 `AGENT_OS_PROVIDER_ENDPOINT_CLASS` 或 profile `anthropic`；`configure_provider` 现支持 `endpoint_class ∈ {openai-compatible, anthropic-messages}`。**流式未实现**：Anthropic `complete_streaming` 回退为单次 complete（一条 delta），诚实标注。Gemini（`google-generative`）仍 fail-closed 未实现。
- **Track**：Product（高风险：provider/凭证路径 + 新增网络出口 + 终端交互面）
- **基座**：`main @ 404724b8`（OS-SANDBOX-0 与 CI 修复已并入）

## 1. 问题（recon 事实）

1. **仅支持 OpenAI 兼容协议**：产品运行时只有一个适配器 `OpenAICompatibleProvider`，固定 `POST {base_url}/chat/completions` + `Authorization: Bearer`（`packages/os_core/src/agent_os_core/provider.py:277,335,472`）。
2. `ProviderProfile.endpoint_class` 是无约束字符串（`packages/contracts/src/agent_os_contracts/provider.py:90`），但代码仅用 `"openai-compatible"`（`provider.py:320,328`）。
3. **原生非 OpenAI 协议未适配**：Anthropic Messages（`/v1/messages`, `x-api-key`, `anthropic-version`）与 Google Gemini（`generativelanguage`）无产品适配器（`grep` os_core/apps 为空）。命名的 `AGENT_OS_PROVIDER_PROFILE=anthropic` 只是把前缀映射到 `ANTHROPIC_*` 变量，底层仍发 `/chat/completions`（`app.py:835-851`）。
4. **终端不能加 provider**：`AgentOSApplication.configure_provider` 存在（`app.py:876-937`），但**未暴露**在 surface 协议上（`apps/api_server/surface_routes.py` 无 provider 路由）；surface 只经 `SurfaceApplicationPort` 委派。终端只能靠 daemon 启动时的 env。
5. 凭证：`EnvCredentialBroker` 在调用时读 env（`provider.py:121-131`）；`configure_provider` 把 key 写入进程 env `AGENT_OS_RUNTIME_PROVIDER_KEY`（**内存**，不落盘），并建 `CredentialRef(resolver_key=...)`（`app.py:902-916`）。

## 2. 目标（P/A）

- **P1（终端加 provider）**：surface 协议新增 `GET/PUT /v1/surface/provider`（status / configure），cli-ts 新增 `/provider` 命令与 `agent-os-ts provider` 子命令；复用 `configure_provider`。
- **P2（原生兼容）**：新增 `AnthropicMessagesProvider` 与 `GeminiGenerativeProvider`（原生协议），`endpoint_class ∈ {openai-compatible, anthropic-messages, google-generative}`；按 profile/endpoint 选择，OpenAI 兼容仍为默认。
- **硬不变量**：
  1. **key 永不持久化**（不写 DB/state/日志/trace/artifact）；仅经内存 env resolver；status 只暴露 `credential_ref_id`（脱敏）。
  2. endpoint 必须 HTTPS 或 loopback HTTP（沿用现有校验）。
  3. provider 配置是**操作员动作**（本地、bearer 鉴权）；**不**改变任何 capability 的 permit/approval；不改 C7。
  4. adapter 仅是传输层；模型输出仍须经 typed contract 与权限脊。
  5. configure 请求体**排除**日志/trace。

## 3. 非目标

无模型注册表/定价（cost 继续 `UNKNOWN`）；无 OAuth；无 keychain/keyring 持久化；不改 E1/E2/E3 冻结语义；不做 release。

## 4. 设计（切片）

### Slice 1 — 终端加 provider（P1）
- Contracts：`SurfaceProviderStatus`（provider_id/model_id/endpoint_class/credential_ref_id/configured，**无 key**）、`SurfaceProviderConfigureCommand`（base_url/model/endpoint_class/api_key/temperature）。
- `SurfaceApplicationPort` + `AgentOSApplication.surface_configure_provider/surface_provider_status`；`SurfaceRuntime` 委派（沿用 idempotency/lock 模式）。
- 路由：`GET /v1/surface/provider`（status）、`POST /v1/surface/provider`（configure；bearer 鉴权，错误映射沿用 `_surface_error_status`）。
- cli-ts：zod 契约镜像 + `client.ts` 两个方法 + `/provider`（无参→状态；带参→引导式输入 base_url/model/endpoint_class/key，key 输入不回显、不进 state 文件）+ `agent-os-ts provider status|set`（headless）。
- 失败路径：缺 key/坏 URL/不支持 endpoint_class → 结构化错误；daemon 未配置 → status `configured=false`。

**as-built 差异（2026-09-14）**：HTTP 处理器仅支持 GET/POST（`server.py` 无 `do_PUT`），故 configure 用 **`POST /v1/surface/provider`**；`/provider set <base-url> <model> [endpoint-class]` 的 **key 取自 CLI 环境变量 `AGENT_OS_PROVIDER_KEY`**（不由 composer 输入 → 不进入 history/state/transcript，比掩码输入更不易泄漏）；不支持 `endpoint_class != openai-compatible` 一律 fail-closed。headless 子命令留待后续。

### Slice 2 — 原生适配器（P2）
- `AnthropicMessagesProvider`：`POST {base_url}/v1/messages`，头 `x-api-key` + `anthropic-version: 2023-06-01`，请求/响应映射到既有 `ProviderMessageRole`/`ProviderToolProposal`（`tool_use`→proposal，`tool_result`→tool message）。
- `GeminiGenerativeProvider`：`POST {base_url}/v1beta/models/{model}:generateContent`，头 `x-goog-api-key`，`functionCall`↔tool proposal 映射。
- 选择：`AGENT_OS_PROVIDER_ENDPOINT_CLASS` 或 `AGENT_OS_PROVIDER_PROFILE ∈ {anthropic,gemini}`；默认 `openai-compatible`。
- 错误/超时/usage 映射（token 精确或 `UNKNOWN`，沿用 E3 诚实）。

## 5. 测试计划（test-first）

1. 路由鉴权（无/坏 token → 401）；configure 成功后 status `configured=true` 且**无 key 字段**。
2. **key 不落盘**：configure 后断言 key 不出现在 sqlite、`~/.agent-os` 各 state 文件、artifacts、日志缓冲（字符串扫描）。
3. Anthropic/Gemini 请求形状（路径/头/auth/body）对**本地 stub** 正确；响应→proposal/message 映射正确；缺 key fail-closed。
4. 不支持 `endpoint_class` → 拒绝（fail-closed），无静默回退。
5. 非回归：openai-compatible 路径不变；C7/permit/approval 不变；E1/E2/E3 专项绿。
6. 绕过检测：若 status 泄露 key、若 configure 绕过鉴权、若 adapter 直发未映射输出 → 测试必红。

## 6. Gate 路径

```text
GC/CP/AB(本文) -> CTO 安全 gate(独立) -> test-first Slice 1
-> 独立 exact-diff + key-不落盘复核 -> Slice 2 -> 独立 exact-diff
-> founder merge 授权
```

## 7. 需 founder 决策

1. **是否批准该 GC**（高风险：凭证 + 新网络出口）；
2. **Slice 范围**：仅 Slice 1；或 Slice 1 + Anthropic；或 Slice 1 + Anthropic + Gemini；
3. **凭证确认**：仅内存 env resolver、不引入 keychain 持久化（建议，符合"key 不落盘"）。
