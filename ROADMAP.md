# Roadmap

## Current Checkpoint - 2026-07-13

- Dashboard maps to the current backend surface: live decision requests, model health, model registry, adaptive healing, feedback, storage provisioning, operation ledger, audit integrity, and benchmarks.
- Backend exposes the matching utility APIs for database status/provisioning, decision events, operation events, and audit verification.
- Product direction is now Tenta Decision Runtime rather than a domain-specific fraud console.
- GitHub setup now includes README assets, runnable examples, CI, issue templates, PR template, security policy, changelog, and package metadata.

## Next Move - Core Utility

- Workload registry is started: each use case can declare request fields, feature aliases, policy thresholds, outcome labels, reason labels, and sample payloads without forking the runtime.
- Runtime endpoints and CLI commands now list, activate, sample, validate, import, and export workload specs.
- The default runtime now uses the generic `decision_risk` workload, while `payment_fraud` remains as a compatibility/reference pack.
- Active workload selection persists in runtime config; imported specs persist under `data/workloads`.
- Workload-aware replay fixtures now cover generic decision risk and payment fraud packs.
- Next: add workload version history, dashboard import/export controls, replay-backed drift/feedback/healing scenarios, and production model adapter scaffolding.

## Phase 0 - Foundation

- Create documentation structure.
- Define core architecture and module boundaries.
- Establish data safety rules and benchmark assumptions.
- Draft threat model and model risk controls.

## Phase 1 - Runtime Core

- Implement the decision scoring runtime.
- Define the model wrapper interface.
- Add structured decision events and audit logs.
- Expose initial scoring and health APIs.

## Phase 2 - Self-Healing Loop

- Add drift detection for features, labels, and model confidence.
- Build the memory system for decisions, feedback, and interventions.
- Implement policy-gated healing actions.
- Add fallback model and threshold adjustment support.

## Phase 3 - Learning and Evaluation

- Add online learning in shadow mode.
- Support delayed labels and analyst feedback.
- Build replay-based evaluation.
- Add regression tests for model behavior.

## Phase 4 - Operations

- Build the dashboard.
- Add Kubernetes deployment assets.
- Add plugin SDK and sample plugins.
- Add benchmark suites for latency and throughput.

## Phase 5 - Research Validation

- Compare drift detectors.
- Evaluate self-healing strategies under adversarial pressure.
- Publish reproducible experiments and design tradeoffs.
