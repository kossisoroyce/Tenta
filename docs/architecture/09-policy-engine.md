# 09 - Policy Engine

The policy engine decides whether proposed healing actions can execute automatically, require approval, or must be rejected.

## Policy Inputs

- Action type.
- Model version and current health.
- Drift severity.
- Segment affected.
- Estimated business impact.
- Risk classification.
- Approval history.

## Example Policy

```yaml
actions:
  threshold_adjustment:
    max_delta: 0.03
    auto_approve_when:
      drift_severity: medium
      p99_latency_ms_below: 50
      false_positive_rate_delta_below: 0.01
  enable_online_learning:
    requires_human_approval: true
  fallback_model_switch:
    auto_approve_when:
      active_model_health: degraded
      fallback_model_health: healthy
```

## Audit Requirements

Every policy decision must record the proposed action, inputs, policy version, result, approver when applicable, and rollback criteria.

