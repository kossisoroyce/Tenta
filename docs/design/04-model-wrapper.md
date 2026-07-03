# 04 - Model Wrapper

The model wrapper provides a stable interface between the runtime and any fraud model implementation.

## Interface Goals

- Hide framework-specific model details.
- Return consistent prediction metadata.
- Expose model version and feature contract.
- Support fallback behavior.
- Attach explainability and confidence signals when available.

## Prediction Contract

```json
{
  "model_id": "fraud-xgb-v12",
  "model_version": "12.3.0",
  "score": 0.91,
  "decision": "review",
  "confidence": 0.84,
  "features_used": ["amount", "merchant_risk", "velocity_10m"],
  "explanations": [
    {"feature": "velocity_10m", "impact": 0.22},
    {"feature": "merchant_risk", "impact": 0.18}
  ]
}
```

## Wrapper Hooks

- `load`: initialize model and metadata.
- `predict`: score one transaction or a microbatch.
- `health`: report readiness and runtime diagnostics.
- `explain`: produce local explanations when supported.
- `shadow_predict`: score without affecting live decisions.

