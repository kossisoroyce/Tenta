# 12 - API Reference

This page defines the initial API surface. Endpoint names are provisional.

## Runtime API

### `POST /v1/score`

Scores a transaction and returns a decision.

Request fields:

- `transaction_id`
- `account_id`
- `amount`
- `currency`
- `merchant_id`
- `channel`
- `event_time`
- `features`

Response fields:

- `transaction_id`
- `score`
- `decision`
- `model_id`
- `model_version`
- `policy_version`
- `reason_codes`
- `latency_ms`

## Health API

### `GET /v1/health`

Returns runtime, model, policy, and dependency status.

## Healing API

### `GET /v1/healing/actions`

Lists proposed, approved, rejected, running, and rolled-back healing actions.

### `POST /v1/healing/actions/{action_id}/approve`

Approves a policy-gated action when the caller has permission.

