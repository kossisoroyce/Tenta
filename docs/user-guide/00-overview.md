# 00 - Overview

Tenta is a Decision Runtime for high-stakes machine learning systems where
model quality, latency, governance, and auditability all matter at once. It
wraps production models with workload-specific validation, policy decisions,
storage-backed memory, human feedback, drift monitoring, adaptive healing, and
tamper-evident audit trails.

Fraud detection is the first reference workload, not the limit of the platform.
The same runtime shape can support credit, insurance, healthcare, identity,
AML, cybersecurity, quality inspection, and other automated decision systems.

Production model serving is designed to pair with
[Timber](https://github.com/kossisoroyce/timber)-compiled native artifacts so
the scoring path can stay fast, deterministic, and auditable by artifact hash.
The current local runtime uses a deterministic rule-based model wrapper so the
engine, dashboard, storage, and governance paths can be developed without
external model infrastructure.

## What Self-Healing Means

Self-healing does not mean a model can change itself without controls. In
Tenta, self-healing means the system can detect degradation, select a bounded
response, apply it through policy gates, and record the full operation trail.

Example healing actions:

- Raise or lower decision thresholds within approved limits.
- Route traffic to a fallback model.
- Trigger retraining or batch evaluation.
- Enable a shadow online learner.
- Request human review for high-risk segments.
- Pause or constrain automation when dependencies become unhealthy.

## Core Loop

1. Receive a decision request for the active workload.
2. Normalize aliases and validate required fields/features.
3. Score the request through the live model wrapper.
4. Apply workload-specific policy thresholds and reason rules.
5. Persist the decision, idempotency record, and audit hash.
6. Monitor performance, drift, latency, errors, and feedback.
7. Propose bounded healing or governance actions when conditions degrade.
8. Apply role gates, execute approved actions, and write operation events.

## Non-Goals

- Replacing human operators, analysts, clinicians, reviewers, or auditors.
- Allowing unbounded online learning in production.
- Optimizing only for model accuracy while ignoring compliance, safety, latency,
  reversibility, and auditability.
- Providing instructions for evasion or misuse of decision systems.
