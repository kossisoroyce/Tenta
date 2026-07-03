# Security Policy

## Supported Versions

The project is pre-release. Security fixes apply to the active main branch until release channels are defined.

## Reporting Security Issues

Do not open public issues for vulnerabilities, secrets, fraud bypasses, or data exposure concerns. Use the private reporting channel defined by the maintainers. If no channel exists yet, mark the issue as blocked until one is created.

## Data Handling Rules

- Never commit production financial data.
- Never commit secrets, API keys, model registry credentials, or database URLs.
- Use synthetic or anonymized datasets in examples.
- Treat model outputs, analyst labels, and transaction metadata as sensitive.

## Model Risk Rules

- Any automated healing action must be logged.
- Any production model update must be reversible.
- High-impact policy changes require human approval.
- Shadow evaluation is required before online learning affects live decisions.

