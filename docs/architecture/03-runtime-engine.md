# 03 - Runtime Engine

The runtime engine receives transaction requests, prepares features, calls the wrapped model, applies decision policy, emits events, and returns a response.

## Responsibilities

- Validate transaction payloads.
- Fetch or compute online features.
- Call the active fraud model through the model wrapper.
- Apply threshold, block, allow, review, or step-up rules.
- Emit decision events for memory and monitoring.
- Enforce latency budgets and fallback behavior.

## Runtime Requirements

- Bounded p99 latency.
- Backpressure handling.
- Idempotency support for retried transaction requests.
- Graceful fallback when feature stores or models are degraded.
- Structured logs and metrics for every decision path.

## Failure Modes

- Feature lookup timeout.
- Model service timeout.
- Missing or malformed transaction fields.
- Policy engine unavailable.
- Memory write failure.
- Drift detector lag.

The runtime should continue making safe decisions during partial outages, but it must mark degraded decisions in the audit trail.

