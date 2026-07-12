# Security Policy

Tenta is pre-release software for governing high-stakes ML decisions. Security
work currently applies to the active `main` branch until release channels are
defined.

## Reporting Security Issues

Do not open public issues for vulnerabilities, secrets, bypasses, data exposure,
model-governance failures, or unsafe automation paths.

Use GitHub private vulnerability reporting when available. If the repository has
not enabled a private reporting channel yet, contact the maintainers directly
and keep the issue out of public issue threads until a safe channel exists.

## Sensitive Data Rules

- Never commit production customer, patient, account, card, claim, identity,
  security, or transaction data.
- Never commit secrets, API keys, signing keys, model registry credentials,
  database URLs with real credentials, or cloud credentials.
- Use synthetic or anonymized datasets in examples, fixtures, tests, and
  screenshots.
- Treat model outputs, analyst labels, feedback records, audit logs, and
  operational metadata as sensitive.

## Runtime Safety Rules

- Mutating operations should be role-gated and written to the operations ledger.
- Automated healing actions must be auditable and reversible where possible.
- Production model updates must preserve rollback metadata.
- Storage provisioning must not leak credentials in API responses or logs.
- Shadow evaluation should precede online-learning or self-healing behavior that
  can affect live decisions.

## Supported Versions

| Version | Supported |
| --- | --- |
| `main` | Yes |
| Published releases | Not yet |
