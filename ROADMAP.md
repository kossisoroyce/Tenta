# Roadmap

## Phase 0 - Foundation

- Create documentation structure.
- Define core architecture and module boundaries.
- Establish data safety rules and benchmark assumptions.
- Draft threat model and model risk controls.

## Phase 1 - Runtime Core

- Implement the transaction scoring runtime.
- Define the model wrapper interface.
- Add structured decision events and audit logs.
- Expose initial scoring and health APIs.

## Phase 2 - Self-Healing Loop

- Add drift detection for features, labels, and model confidence.
- Build the memory system for decisions, feedback, and interventions.
- Implement policy-gated healing actions.
- Add fallback model and threshold adjustment support.

## Phase 3 - Learning and Evaluation

- Add online learning in shadow mode.
- Support delayed labels and analyst feedback.
- Build replay-based evaluation.
- Add regression tests for model behavior.

## Phase 4 - Operations

- Build the dashboard.
- Add Kubernetes deployment assets.
- Add plugin SDK and sample plugins.
- Add benchmark suites for latency and throughput.

## Phase 5 - Research Validation

- Compare drift detectors.
- Evaluate self-healing strategies under adversarial pressure.
- Publish reproducible experiments and design tradeoffs.

