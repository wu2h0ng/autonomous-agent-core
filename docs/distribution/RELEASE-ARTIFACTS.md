# 发布产物清单（RELEASE ARTIFACTS）— L4 ADR 输入素材（非正式 ADR）

> 状态：预备素材。本仓**不实际发布**；本清单只描述每个渠道将分发什么、如何命名、如何校验。

## 渠道与产物

| 渠道 | 产物格式 | 命名 | 校验方式 |
|---|---|---|---|
| pip / uv | Python wheel（`.whl`）+ sdist（`.tar.gz`） | `agent_os-<semver>-py3-none-any.whl` / `agent_os-<semver>.tar.gz` | sha256 + (L4 选定) ed25519 签名；`uv pip install --require-hashes` |
| npm | TS 包（`apps/cli-ts`）tgz | `agent-os-cli-<semver>.tgz` | sha256；包内 `package.json` version 与 Py side 一致 |
| Homebrew | Homebrew formula（独立 tap 仓） | `agent-os-cli.rb`（指向 bottle/tar） | bottle sha256 写入 formula |
| 直接下载 | 单文件二进制（TS 编译产物）+ 校验和文件 | `agent-os-cli-<os>-<arch>` / `agent-os-cli-<os>-<arch>.sha256` | sha256 旁置文件 + ed25519 签名（`.sig`） |

## 产物矩阵

- 单文件二进制按 `(macos/linux) × (arm64/x86_64)` 出 4 份（dry-run 只构建、不发）。
- wheel 纯 Python（`py3-none-any`），平台无关。

## 校验顺序（消费者侧）

1. 比对 `.sha256`；
2. 校验 ed25519 签名对 **trust anchor**（公钥指纹，L4 冻结）；
3. 通过后才安装/执行。

## 不产物

- 不发布 live provider key、不发布任何 `~/.agent-os/` 内容、不发布内部 fixture/quarantine 资产。
- 不自动升 tag；tag 仅由 gated 真实发布动作产生（见 `release-dry-run.yml`）。
