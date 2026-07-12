# 03 - Runtime Engine

The runtime engine receives decision requests, normalizes workload aliases,
prepares features, calls the wrapped model, applies decision policy, emits
events, and returns a response.

## Responsibilities

- Validate decision request payloads.
- Fetch or compute online features.
- Verify the Ed25519 signature of the loaded Timber-compiled model artifact on load.
- Call the active model through the model wrapper (a native call into the Timber-compiled C99 artifact in production).
- Apply threshold, block, allow, review, or step-up rules.
- Emit decision events for memory and monitoring.
- Enforce latency budgets and fallback behavior, including hot-swap to a previous signed Timber artifact.

## Runtime Requirements

- Bounded p99 latency. Native inference through Timber-compiled artifacts keeps the model call itself sub-millisecond for typical tree ensembles, leaving the budget for feature IO and policy evaluation.
- Backpressure handling.
- Idempotency support for retried transaction requests.
- Graceful fallback when feature stores or models are degraded.
- Structured logs and metrics for every decision path, including the active Timber artifact hash for full traceability.

## Failure Modes

- Feature lookup timeout.
- Model service timeout.
- Missing or malformed request fields.
- Policy engine unavailable.
- Memory write failure.
- Drift detector lag.

The runtime should continue making safe decisions during partial outages, but it must mark degraded decisions in the audit trail.
