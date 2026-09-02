# Security Policy

## Supported Version

Only the latest release on the `main` branch is supported. The `develop`
branch and feature branches are pre-release software.

## Reporting a Vulnerability

Do not publish credentials, customer records, payment data or exploitable
details in a public issue.

Report a vulnerability privately to the repository owner through GitHub's
private vulnerability reporting feature when enabled. Include:

- The affected commit or release
- Reproduction steps
- Expected impact
- A suggested mitigation, if available

Never include production API keys, database backups or unredacted logs.

## High-Risk Areas

Changes affecting authentication, cashier permissions, M-Pesa callbacks,
offline invoice replay, payment reconciliation, raw printing or document
submission require focused security review and integration tests.
