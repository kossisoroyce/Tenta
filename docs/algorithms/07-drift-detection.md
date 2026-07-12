# 07 - Drift Detection

Drift detection identifies when production data or model behavior diverges from expected behavior.

## Drift Types

- Feature drift: input feature distributions change.
- Label drift: outcome distributions change.
- Concept drift: the relationship between features and outcomes changes.
- Confidence drift: model confidence distribution changes.
- Segment drift: drift appears in a subject, context, geography, age, channel, device, or workload-specific segment.

## Candidate Detectors

- Population Stability Index for simple feature monitoring.
- Kolmogorov-Smirnov tests for numerical distribution shift.
- Chi-square tests for categorical feature drift.
- Jensen-Shannon divergence for probability distributions.
- ADWIN or similar windowed detectors for streaming change.
- Model performance monitoring for delayed labels.

## Alert Requirements

Alerts should include affected segment, detector name, baseline window, current window, severity, confidence, and recommended next action.
