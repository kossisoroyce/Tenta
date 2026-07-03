# Contributing

Thanks for helping build the Self-Healing ML Platform.

## Contribution Principles

- Keep fraud detection safety, auditability, and operational reliability ahead of novelty.
- Do not commit real customer data, card data, account data, personally identifiable information, secrets, or production model artifacts.
- Prefer synthetic, anonymized, or tokenized datasets for examples and tests.
- Document every behavior that changes model decisions, thresholds, healing actions, or policy enforcement.

## Workflow

1. Open an issue or design note for significant changes.
2. Keep pull requests focused on one capability or document area.
3. Add or update tests for runtime, model wrapper, drift detection, policy, and API behavior.
4. Update documentation when changing public APIs, deployment configuration, or safety controls.
5. Include benchmark notes for changes that affect latency, throughput, or memory use.

## Code Quality

- Favor explicit contracts over implicit model behavior.
- Keep model adaptation paths observable and reversible.
- Make failure modes visible through logs, metrics, and audit events.
- Use deterministic tests where possible and bounded stochastic tests where needed.

