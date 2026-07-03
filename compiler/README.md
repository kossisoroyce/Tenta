# Compiler

Model, policy, and artifact compilation layer.

This module wraps the [Timber Compiler](https://github.com/kossisoroyce/timber) with fraud-detection-specific build, validation, and signing steps. It takes a trained fraud model (XGBoost, LightGBM, scikit-learn, CatBoost, or ONNX) plus its policy, feature contract, and metadata, and produces a signed, deployable inference artifact for the runtime.

## Responsibilities

- Invoke Timber to compile the trained model into native C99 (optionally with SIMD / GPU / embedded backends).
- Validate that the compiled artifact preserves the model's predictions within tolerance against a reference test set.
- Attach the model's feature contract, calibration, and policy bindings to the artifact bundle.
- Sign artifacts with Ed25519 and register them in the model registry.
- Validate policy manifests, plugin manifests, and deployment configuration.
- Verify runtime artifacts are complete, signed, compatible, and safe to deploy.

## Build Pipeline

1. Load trained model + training-time metadata.
2. Run parity harness (Python model vs. Timber-compiled model) on a golden dataset.
3. Compile with Timber to C99 (targets: x86-64 AVX2/AVX-512, ARM NEON/SVE, or embedded).
4. Package: compiled shared library + feature contract + calibration + policy manifest + WCET report.
5. Sign the bundle with Ed25519 and push to the model registry.

See [docs/architecture/03a-timber-compiler.md](../docs/architecture/03a-timber-compiler.md) for the full integration design.
