# Self-Healing ML Platform

Self-Healing ML Platform is a reference architecture for fraud detection in high-frequency financial transaction systems. The platform wraps fraud models with runtime monitoring, drift detection, memory, policy controls, online learning, and human review workflows so production models can adapt safely without becoming ungoverned.

## Goals

- Detect fraud with low latency under high transaction volume.
- Monitor data drift, concept drift, model confidence, and operational health.
- Trigger controlled healing actions such as threshold adjustment, model fallback, retraining, or online updates.
- Preserve auditability for every model decision and every automated intervention.
- Provide a dashboard, SDK, plugin system, and deployment path for production use.

## Repository Layout

```text
ship/
├── docs/
│   ├── architecture/
│   ├── design/
│   ├── algorithms/
│   ├── api/
│   ├── deployment/
│   ├── ui/
│   ├── sdk/
│   ├── research/
│   └── user-guide/
├── runtime/
├── dashboard/
├── sdk/
├── compiler/
├── controller/
├── plugins/
├── examples/
└── benchmarks/
```

## Documentation

Start with [docs/README.md](docs/README.md), then read:

- [Overview](docs/user-guide/00-overview.md)
- [Problem Statement](docs/design/01-problem-statement.md)
- [System Architecture](docs/architecture/02-system-architecture.md)
- [Self-Healing Engine](docs/algorithms/05-self-healing-engine.md)
- [API Reference](docs/api/12-api-reference.md)
- [Security](docs/deployment/15-security.md)

## Status

This repository is in the planning and design phase. The current content defines the platform boundaries, documentation map, module responsibilities, and early architecture assumptions.

## License

Apache License 2.0. See [LICENSE](LICENSE).
