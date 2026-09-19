# 版本策略（VERSIONING STRATEGY）— L4 ADR 输入素材（非正式 ADR）

> 状态：预备素材，供 L4 分片的签名/版本/分发正式 ADR 采用。本仓**不实际 tag/publish/deploy**。
> 基线：`origin/main = 04377dc3`。

## 1. 语义化版本（SemVer）

`<MAJOR>.<MINOR>.<PATCH>`，严格 SemVer：

- **MAJOR**：不向后兼容的接口/协议/契约破坏（`SURFACE_PROTOCOL_VERSION` 跳档、grant/permit 语义破坏、配置/CLI 不兼容变更）。
- **MINOR**：向后兼容的新能力（新 capability、新面板、新 surface 字段，均为 additive）。
- **PATCH**：向后兼容的修复（bugfix、文档、不改变行为契约的重构）。

## 2. 预发布标签（pre-release）

- `aN`：alpha（内部 dogfood，可能 break，不声明可升级路径）。
- `bN`：beta（契约冻结，收反馈，声明升级路径）。
- `rc.N`：release candidate（待 founder 批准即转正；仅差 gated 发布动作）。
- 示例：`1.0.0-rc.1`。转正即 `1.0.0`。

## 3. 版本号与 git tag 的对应

- 正式发布：git tag `v<semver>`（如 `v1.0.0`），annotated tag，message 指向 release notes 草稿。
- 预发布：tag `v<semver>-aN` / `v<semver>-bN` / `v<semver>-rc.N`。
- **tag 只由 gated 真实发布动作产生**；dry-run workflow 不 tag、不 push。
- 一个版本号 = 一个 commit = 一个 tag；不复用、不 force-tag。

## 4. 版本号在代码中的位置

- Python：`pyproject.toml` 的 `[project] version`（单一来源；wheel 从此读）。
- TS：`apps/cli-ts/package.json` 的 `version`，与 Python 侧同值（发布前校验两侧一致）。
- 构建产物元数据（wheel `METADATA`、单文件二进制 embed 的 version）在构建时从上述来源读，**不**手写第二处。

## 5. 升级兼容性承诺

- MINOR/PATCH：可原地升级，不做 destructive migration；append-only durable 历史不删不改（沿 ADR-0061 §8.2）。
- MAJOR：声明升级路径与回滚；回滚 = 关断 + 发上一注册版本（沿既有 canary/rollback 纪律）。
- 不声明跨主版本的自动迁移。

## 6. claim_ceiling（no release）解除条件

当前 `claim_ceiling = no release`：本仓不发布。解除须 founder 批准，且满足：(a) 签名方案 ADR（L4）落地；(b) gated dry-run workflow 跑绿；(c) 产物清单与校验方式冻结；(d) 升级/回滚路径有证据。
