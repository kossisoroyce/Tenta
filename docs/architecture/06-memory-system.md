# 06 - Memory System

The memory system stores the historical context needed for drift detection, evaluation, audits, and self-healing decisions.

## Memory Types

- Decision memory: transaction score, decision, model version, policy version, and latency.
- Feedback memory: chargebacks, analyst labels, disputes, and customer outcomes.
- Drift memory: detector outputs, windows, segments, and severity.
- Healing memory: proposed actions, approvals, executions, and rollback results.
- Feature memory: feature values, freshness, and source metadata where retention policy allows.

## Design Principles

- Store enough context to explain why a decision happened.
- Avoid storing raw sensitive data unless absolutely required.
- Apply retention and access controls per data class.
- Keep immutable audit events separate from mutable operational views.

## Open Decisions

- Event store implementation.
- Hot path cache strategy.
- Long-term retention policy.
- Feature snapshot granularity.

