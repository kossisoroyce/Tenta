# 17 - Deployment

Deployment should support repeatable promotion from development to staging to production.

## Environments

- Development: local services and synthetic data.
- Staging: production-like data contracts with anonymized or synthetic streams.
- Shadow production: real-time scoring without decision impact.
- Production: active scoring with policy-gated healing.

## Deployment Steps

1. Build runtime, controller, dashboard, and plugin artifacts.
2. Compile the fraud model with Timber into a signed C99 artifact and run the parity check against the source model.
3. Run unit and integration tests.
4. Run replay evaluation for model and policy changes against the Timber-compiled artifact.
5. Deploy to staging.
6. Enable shadow traffic (compare Timber-compiled artifact against the current production artifact live).
7. Review metrics, WCET report, and audit logs.
8. Promote through an approved release process. Promotion is a registry pointer change to the new signed artifact hash — the runtime picks it up via signature-verified hot-swap.

## Rollback

Every deployment must define rollback behavior for model artifacts, policy versions, runtime services, and healing actions. Because Timber artifacts are immutable and content-addressed by hash, rollback is a repoint to the previous known-good signed artifact — no rebuild required.

