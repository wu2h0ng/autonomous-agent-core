# SPINE-1 Data Agent donor — secret / PII / binary history scan

> Status: `EVIDENCE / PASS (secrets)`
> Date: 2026-09-15
> Donor pin: `aaea36c694adb04664ff30fddccb43c2eb6a6614` (`ai-native-business-data-agent-os`)
> Satisfies ADR-0054 §3 history-safety requirement (in part) and ADR-0060 precondition 5.

## 1. Secret scan — PASS

| Field | Value |
|---|---|
| Scanner | `gitleaks` 8.30.1 (Homebrew) |
| Invocation | `gitleaks git ai-native-business-data-agent-os --log-opts="--all" --report-format json --report-path <redacted> --redact` |
| Scope | all refs / full reachable history |
| Commits scanned | 507 |
| Bytes scanned | ~9.78 MB |
| Findings | **0** |
| Verdict | **PASS** (no secret/credential/high-entropy leaks) |
| Report digest (SHA-256, redacted) | `37517e5f3dc66819f61f5a7bb8ace1921282415f10551d2defa5c3eb0985b570` |

The report contains no secret values (scanned with `--redact`). Raw report:
`docs/architecture/provenance/secret-scan/donor-gitleaks-2026-09-15.json`.

## 2. Oversized / binary / LFS inventory — CLEAN

- Git LFS: **not used** (`.gitattributes` has no `filter=lfs`).
- Tracked files > 500 KB: **none**.
- Binary objects: **none** (all flagged "executable" matches are UTF-8 text scripts with shebangs).

## 3. PII / customer-data inventory — best effort, no real PII detected

| Pattern | Distinct matches | Note |
|---|---|---|
| email | 15 | all placeholder/example infrastructure domains (`@example.com`, `@company.com`, `@test.local`, `@agent-os.local`, `@db.example.com`, `@github.com`); remainder are image-name false positives |
| CN mobile phone | 0 | — |
| 18-digit ID card | 0 | — |

**Limitation:** this is best-effort pattern matching, **not** a PII classifier. The donor `docs/`
hold internal Chinese commercial/strategy material; it is retained in the donor archive as history
and is not migrated into the Product core.

## 4. Disposition

Secrets: PASS. Binary/LFS: clean. PII: no real customer PII detected; remaining material is internal
history. A full-history secret/PII scan of the pinned donor is now recorded, closing the secret-scan
portion of ADR-0060 precondition 5. This is a scan record, not a retirement authorization.
