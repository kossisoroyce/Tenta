# 17 - Deployment

Deployment should support repeatable promotion from development to staging to production.

## Environments

- Development: local services and synthetic data.
- Staging: production-like data contracts with anonymized or synthetic streams.
- Shadow production: real-time scoring without decision impact.
- Production: active scoring with policy-gated healing.

## Deployment Steps

1. Build runtime, controller, dashboard, and plugin artifacts.
2. Run unit and integration tests.
3. Run replay evaluation for model and policy changes.
4. Deploy to staging.
5. Enable shadow traffic.
6. Review metrics and audit logs.
7. Promote through an approved release process.

## Rollback

Every deployment must define rollback behavior for model artifacts, policy versions, runtime services, and healing actions.

