# 04 - Model Wrapper

The model wrapper provides a stable interface between the runtime and any
production model implementation. In production, the wrapper's `predict` path
dispatches to a Timber-compiled native C99 artifact loaded as a shared library;
the wrapper's contract is deliberately identical whether the underlying model is
Timber-compiled, a Python fallback, or a future backend.

## Interface Goals

- Hide framework-specific model details.
- Return consistent prediction metadata.
- Expose model version and feature contract.
- Support fallback behavior.
- Attach explainability and confidence signals when available.

## Prediction Contract

```json
{
  "model_id": "risk-xgb-v12",
  "model_version": "12.3.0",
  "score": 0.91,
  "decision": "review",
  "confidence": 0.84,
  "features_used": ["amount", "entity_risk", "velocity_10m"],
  "explanations": [
    {"feature": "velocity_10m", "impact": 0.22},
    {"feature": "entity_risk", "impact": 0.18}
  ]
}
```

## Wrapper Hooks

- `load`: initialize model and metadata; for Timber-backed models, verify the artifact's Ed25519 signature and record its hash.
- `predict`: score one transaction or a microbatch.
- `health`: report readiness and runtime diagnostics, including active artifact hash and compile-time backend.
- `explain`: produce local explanations when supported.
- `shadow_predict`: score without affecting live decisions.
- `swap`: atomically replace the active Timber artifact with a new signed artifact (used by policy-approved healing actions).
