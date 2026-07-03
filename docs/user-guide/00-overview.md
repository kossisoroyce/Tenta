# 00 - Overview

The Self-Healing ML Platform is designed for real-time fraud detection systems where model quality, latency, and governance all matter at once.

## What Self-Healing Means

Self-healing does not mean a model can change itself without controls. In this platform, self-healing means the system can detect degradation, select a bounded response, apply it through policy gates, and record the full decision trail.

Example healing actions:

- Raise or lower fraud score thresholds within approved limits.
- Route traffic to a fallback model.
- Trigger retraining or batch evaluation.
- Enable a shadow online learner.
- Request human review for high-risk segments.

## Core Loop

1. Score a transaction.
2. Record model inputs, outputs, context, and decision metadata.
3. Monitor performance, drift, latency, errors, and feedback.
4. Detect degradation or distribution shift.
5. Propose a healing action.
6. Apply policy gates.
7. Execute the approved action.
8. Audit and evaluate the result.

## Non-Goals

- Replacing fraud analysts.
- Allowing unbounded online learning in production.
- Optimizing only for model accuracy while ignoring compliance, safety, and latency.
- Providing instructions for fraud evasion.

