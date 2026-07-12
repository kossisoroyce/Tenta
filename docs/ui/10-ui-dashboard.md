# 10 - UI Dashboard

The dashboard gives operators, analysts, and model-risk reviewers visibility into
the live decision runtime.

## Views

- Live scoring health.
- Score and decision distribution.
- Drift alerts by segment.
- Model version comparison.
- Healing action queue.
- Policy approval history.
- Analyst feedback and label delay.
- Benchmark and latency panels.

## Operator Actions

- Approve or reject high-risk healing actions.
- Roll back an automated action.
- Promote a candidate model to shadow mode.
- Inspect a decision request trail.
- Acknowledge or escalate drift alerts.

## Design Constraint

The dashboard should make automated adaptation understandable. Operators should see what changed, why it changed, who or what approved it, and how the system is measuring the outcome.
