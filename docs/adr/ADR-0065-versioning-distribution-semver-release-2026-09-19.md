# ADR-0065: Versioning and distribution channels — SemVer 2.0 + GitHub Releases, dry-run only

- Status: Accepted (founder ruling 2, 2026-09-19; engineering shape recorded,
  NOT executed — no tag/release/tap/publish happens on this branch).
- Date: 2026-09-19
- Deciders: founder.
- Preserves: the red line "do not tag / release / deploy / flip claim_ceiling";
  ADR-0064 signature model.
- Numbering check: max baseline ADR is 0062. This takes 0065.

## 1. Context

The tool ships to humans over three plausible paths (Python package, shell
install script, Homebrew). There was no chosen version scheme and no chosen
release shape, so self-update could not yet define "newer" or "expected sha256".

## 2. Options considered

- **A — Calendar versioning (CalVer).** Rejected. The surface is pre-1.0 and we
  need semantic "minimum required floor" comparisons for self-update; a date
  tells the operator nothing about compatibility.
- **B — Internal hash-only version.** Rejected for user-facing `--version`;
  operators need an orderable, comparable scheme.
- **C — SemVer 2.0 (chosen).** 1.0 is not promised; pre-1.0 uses `0.x.y`.
  First formal release is `0.1.0`; `--version` appends build metadata
  `0.1.0+<shortsha>`.

## 3. Decision (shape built, executed in dry-run/gated only)

- **Artifacts/channels (GitHub Releases):** single-file tarballs per platform
  (macOS arm64/x64, Linux x64) + sha256 manifest + minisign signature
  (ADR-0064). Three install channels:
  1. `uv tool`/`pipx` install of the Python package (fix stale wheel cache).
  2. `install.sh` evolved from the existing `install_local`/`install_smoke`;
     after install it boots the daemon and answers one deterministic stub turn.
  3. macOS Homebrew tap formula.
- **Release workflow:** tag-triggered build → manifest → (only when the signing
  secret is present) minisign sign → upload → update tap. **Default dry-run /
  gated.** When the secret is absent the workflow explicitly SKIPS signing and
  labels the artifact unsigned; it must NEVER upload an unsigned artifact while
  claiming it was verified.
- Self-update reads the latest release manifest and verifies per ADR-0064.

## 4. Consequences and reversibility

- No irreversible act is taken by this ADR. It records the intended pipeline;
  the first real tag remains a separate, explicit, gated founder action.
- The install-smoke CI step added on this branch already proves the Python
  channel end-to-end in CI (`uv tool install .` → boot → deterministic stub
  turn) against a temp dir and a stub provider.

## 5. Red lines (not crossed)

No real tag, no GitHub Release, no tap publish, no deploy, no `claim_ceiling`
change. The release workflow, Homebrew formula, and `install.sh` evolution are
scaffolding to be exercised in dry-run before any of that is allowed.
