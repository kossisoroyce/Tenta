# Changelog

All notable changes to Tenta will be documented in this file.

The project follows a pre-release cadence while the runtime, dashboard, and SDK
surfaces stabilize.

## 0.1.0 - Unreleased

### Added

- Python Decision Runtime package with `tenta` CLI.
- Stdlib HTTP API for decision requests, health, recent decisions, audit
  integrity, workloads, feedback, drift, model operations, healing actions, and
  database provisioning.
- Generic `decision_risk` workload and `payment_fraud` reference workload.
- Workload import/export, activation, validation, sample payloads, and packaged
  replay fixtures.
- Embedded SQLite persistence with optional Postgres backend and local
  provisioning flow.
- Hash-chained decision and operation audit trails.
- Persistent control-plane state for models, drift, healing, feedback,
  benchmarks, policy history, and runtime controls.
- React, TypeScript, Vite, and Kumo dashboard served by the runtime.
- GitHub CI, issue templates, PR template, README assets, and runnable examples.
- App-facing serving endpoint discovery through `GET /v1/serving-endpoint`,
  `tenta endpoint`, and model promotion responses.
- Timber artifact manifest registration with SHA-256 validation, signature
  metadata checks, workload compatibility checks, replay-gated promotion, and
  `tenta model ...` CLI commands.
- `TentaClient` Python helper for endpoint discovery, decisions, decision
  lookup, health, and feedback.
