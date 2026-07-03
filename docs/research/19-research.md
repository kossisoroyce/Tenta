# 19 - Research

This page tracks open research questions, experiments, and evaluation ideas.

## Open Questions

- Which drift detectors produce the best signal-to-noise ratio for transaction streams?
- How should the system distinguish legitimate seasonal behavior from adversarial drift?
- What healing actions reduce loss without increasing customer friction?
- How should delayed labels be weighted in online learning?
- What is the safest default when detectors disagree?

## Experiment Backlog

- Simulate sudden merchant-category fraud bursts.
- Simulate gradual account-takeover drift.
- Compare threshold adjustment against fallback model routing.
- Measure analyst workload impact from segment-level review escalation.
- Evaluate online learner behavior with noisy labels.

## Evaluation Metrics

- Fraud loss prevented.
- False positive rate.
- Precision and recall by segment.
- Review queue volume.
- Detection delay.
- Rollback frequency.
- Latency overhead from monitoring and policy checks.

