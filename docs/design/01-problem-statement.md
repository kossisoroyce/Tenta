# 01 - Problem Statement

High-frequency financial transaction systems need fraud models that can react to changing behavior without sacrificing safety, latency, or auditability.

## Challenges

- Fraud patterns change quickly.
- Labels often arrive late through chargebacks, analyst review, or customer disputes.
- Attackers adapt to model behavior.
- Transaction volume makes manual review expensive.
- False positives create customer friction.
- False negatives create direct financial loss.
- Compliance teams need explainable decision trails.

## Platform Objective

Build a controlled self-healing layer around fraud detection models. The layer should observe production behavior, detect degradation, recommend or apply bounded interventions, and preserve enough history for debugging, audit, and model risk management.

## Success Criteria

- Low p95 and p99 scoring latency.
- Measurable fraud loss reduction.
- Controlled false positive rate.
- Drift alerts with useful segment-level context.
- Reversible automated actions.
- Full audit history for predictions and healing actions.

