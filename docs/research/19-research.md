# 19 - Research

This page tracks open research questions, experiments, and evaluation ideas.

## Open Questions

- Which drift detectors produce the best signal-to-noise ratio for high-volume
  decision streams?
- How should the system distinguish legitimate seasonal behavior from
  adversarial or harmful drift?
- Which healing actions reduce loss, risk, or harm without increasing user
  friction or operator burden?
- How should delayed labels be weighted in online learning?
- What is the safest default when detectors disagree?

## Experiment Backlog

- Simulate sudden segment-level outcome spikes.
- Simulate gradual behavior drift across a workload population.
- Compare threshold adjustment against fallback model routing.
- Measure analyst or reviewer workload impact from segment-level review
  escalation.
- Evaluate online learner behavior with noisy labels.

## Evaluation Metrics

- Adverse outcomes prevented.
- False positive and false negative rates.
- Precision and recall by segment.
- Review queue volume.
- Detection delay.
- Rollback frequency.
- Latency overhead from monitoring and policy checks.
