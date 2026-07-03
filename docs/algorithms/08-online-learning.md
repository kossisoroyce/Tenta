# 08 - Online Learning

Online learning allows the platform to adapt from new feedback, but it must be constrained carefully in financial systems.

## Operating Modes

- Off: no online updates.
- Shadow: learner updates internally but does not affect live decisions.
- Assisted: learner recommendations require approval.
- Bounded live: approved model parameters update within strict limits.

## Safeguards

- Use delayed labels carefully.
- Track label provenance and confidence.
- Prevent feedback loops from analyst decisions alone.
- Require rollback support.
- Compare against a frozen baseline.
- Monitor segment-level harm and false positive rate.

## Recommended Default

Start with shadow mode. Promote online updates only after replay tests, canary evaluation, and policy approval.

