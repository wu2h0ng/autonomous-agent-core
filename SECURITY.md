# Security Policy

## Supported Versions

This project is pre-MVP. Security fixes apply to the `main` branch until the first release line is created.

## Reporting a Vulnerability

Use GitHub private vulnerability reporting when available:

```text
https://github.com/wu2h0ng/data-agent-os/security/advisories/new
```

If private advisories are unavailable, contact the repository owner directly. Do not open a public issue for exploitable vulnerabilities, leaked secrets, credential exposure, customer data exposure, or bypasses of SQL Safety, permissions, EvidenceChain, or approval controls.

## Sensitive Data Rules

Do not commit:

- API keys, PATs, SSH private keys, cookies, sessions, or credentials.
- Raw customer data.
- Production database dumps.
- Private prompts containing customer secrets.
- Logs containing tokens, passwords, or sensitive business data.

## High-Risk Areas

Changes touching these areas require explicit review:

- `packages/os_core/sql_safety/`
- `packages/os_core/evidence_chain/`
- `packages/os_core/action_proposal/`
- `packages/os_core/agent_runtime/`
- `packages/contracts/`
- `providers/`
- `action_connectors/`
- GitHub Actions and automation scripts.

## MVP Action Policy

R4/R5 business actions are proposal-only. Automatic execution of high-risk actions requires a future ADR, tests, approval workflow, and CTO approval.
