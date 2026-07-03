# 16 - Testing

Testing must cover software correctness, model behavior, safety controls, and production resilience.

## Test Types

- Unit tests for runtime contracts and policy rules.
- Integration tests for scoring, memory writes, and drift events.
- Replay tests using historical or synthetic transaction streams.
- Shadow model comparisons.
- Load tests for throughput and p99 latency.
- Chaos tests for model, feature store, and database failures.
- Security tests for authorization and secret handling.

## Model Tests

- Baseline metric comparison.
- Segment-level false positive and false negative checks.
- Drift detector calibration.
- Online learner rollback simulation.
- Reason code stability checks.

## Release Gates

A release should not promote a model or healing policy unless it passes latency, safety, evaluation, and auditability checks.

