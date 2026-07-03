# 05 - Self-Healing Engine

The self-healing engine converts drift signals, performance signals, and operational signals into proposed actions.

## Inputs

- Feature drift events.
- Label drift and delayed performance metrics.
- Confidence distribution changes.
- Segment-level false positive and false negative trends.
- Runtime errors, latency spikes, and fallback rates.
- Analyst feedback and confirmed fraud labels.

## Healing Actions

- Adjust thresholds within policy-defined bounds.
- Shift traffic to a fallback model.
- Trigger retraining or evaluation.
- Enable shadow scoring for candidate models.
- Increase manual review for risky segments.
- Disable online learning when instability is detected.

## Safety Model

Every healing action is a proposal until the policy engine approves it. Some actions can be auto-approved under strict bounds. High-risk actions require human approval.

## Control Loop

1. Aggregate signals.
2. Diagnose likely degradation mode.
3. Generate candidate actions.
4. Estimate impact and risk.
5. Submit action to the policy engine.
6. Execute approved action.
7. Monitor outcome and rollback criteria.

