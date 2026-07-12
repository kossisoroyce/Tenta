# 12 - API Reference

This page defines the initial API surface. Endpoint names are provisional.

## Decision Runtime API

### `POST /v1/decision-requests`

Runs a decision request through the live runtime and returns the policy decision.
This is the preferred platform endpoint.

Request fields:

- `decision_request_id`
- `workload_id` (optional; defaults to the active workload)
- `subject_id`
- `context_id`
- `value`
- `currency`
- `channel`
- `event_time` or `requested_at`
- `features`

Feature aliases supported by the reference workload:

- `entity_risk`
- `velocity_10m`
- `subject_age_days`
- `prior_adverse_events`
- `high_risk_segment`

Response fields:

- `decision_request_id`
- `transaction_id`
- `score`
- `decision`
- `model_id`
- `model_version`
- `policy_version`
- `reason_codes`
- `latency_ms`
- `workload_id`

### `POST /v1/score`

Legacy compatibility alias for `POST /v1/decision-requests`. Existing clients
may continue sending `transaction_id`, `account_id`, `merchant_id`, `amount`,
and workload-specific feature names. The runtime normalizes equivalent payloads
to the same idempotency fingerprint.

## Health API

### `GET /v1/health`

Returns runtime, model, policy, storage, audit, and dependency status. Storage
health includes `schema_version` when the backend supports migrations.
The response also includes the active workload summary under `workload`.

### `GET /v1/serving-endpoint`

Returns the current application-facing endpoint for the live champion model.
Timber artifacts run behind this governed Tenta endpoint rather than being
exposed as raw model microservices. Applications should send decision requests
to the returned `url`.

```json
{
  "model_id": "fraud-xgb-v12",
  "model_version": "12.3.0",
  "stage": "champion",
  "status": "serving",
  "url": "http://127.0.0.1:8080/v1/decision-requests",
  "endpoint_url": "http://127.0.0.1:8080/v1/decision-requests",
  "method": "POST",
  "content_type": "application/json",
  "contract": "decision_request.v1",
  "serving_mode": "governed_decision_runtime",
  "workload_id": "decision_risk"
}
```

The endpoint is stable across model promotions. Promoting a new Timber artifact
to champion changes the model behind the endpoint while preserving policy,
audit, idempotency, workload validation, and rollback controls.

## Workload Registry API

Workloads let Tenta describe decision domains without forking the runtime. A
workload declares request aliases, feature aliases, policy thresholds, reason
labels, outcome labels, and a sample payload.

### `GET /v1/workloads`

Returns the active workload plus summaries of all packaged workload specs.

### `GET /v1/workloads/active`

Returns the full active workload spec.

### `GET /v1/workloads/{workload_id}`

Returns a full workload spec, including features, aliases, reason labels,
outcome labels, and sample payload.

### `GET /v1/workloads/{workload_id}/export`

Returns the full workload spec wrapped as `{ "workload_id": "...", "spec": { ... } }`
for portability across machines.

### `GET /v1/workloads/{workload_id}/sample`

Returns a sample request payload for the workload.

### `POST /v1/workloads/validate`

Validates a payload against the selected workload without scoring it.

```json
{
  "workload_id": "decision_risk",
  "payload": {
    "decision_request_id": "req-001",
    "workload_id": "decision_risk",
    "subject_id": "subject-001",
    "context_id": "reference-workload",
    "value": 120,
    "currency": "USD",
    "channel": "api",
    "requested_at": "2026-07-11T12:00:00Z",
    "features": {
      "entity_risk": 0.2,
      "velocity_10m": 2,
      "subject_age_days": 180,
      "prior_adverse_events": 0,
      "high_risk_segment": false
    }
  }
}
```

### `POST /v1/workloads/activate`

Activates a workload on the running runtime and replaces the threshold policy
with the workload policy. Requires `model-risk` or `admin`; successful
activation writes `workload.activate` to the operation ledger.
The active workload id is persisted in `data/tenta-runtime.json`.

```json
{
  "workload_id": "payment_fraud",
  "actor": "operator@example.com",
  "role": "model-risk",
  "reason": "Switch local runtime to payment fraud pack"
}
```

### `POST /v1/workloads/import`

Imports a workload spec into the running registry. Requires `model-risk` or
`admin`; successful imports write `workload.import` to the operation ledger.
When `persist` is true, the spec is written under `data/workloads`. When
`activate` is true, the imported workload becomes active and the active workload
id is persisted in runtime config.

```json
{
  "spec": {
    "workload_id": "claims_triage",
    "name": "Claims Triage",
    "version": "0.1.0",
    "domain": "insurance",
    "features": [
      {
        "name": "entity_risk",
        "label": "Entity risk",
        "type": "number",
        "default": 0.25
      }
    ]
  },
  "persist": true,
  "activate": false,
  "actor": "operator@example.com",
  "role": "model-risk"
}
```

## Audit API

### `GET /v1/decisions`

Returns recent decision audit events. Supports a `limit` query parameter from 1
to 100. Decision events include `event_hash` and `previous_hash` for audit
integrity.

### `GET /v1/decision-events`

Alias for listing recent decision audit events with `decision_request_id`
included on each row.

### `GET /v1/decision-requests/{decision_request_id}`

Returns the latest decision audit event for a decision request, or `404` when
the request is unknown to the runtime store.

### `GET /v1/transactions/{transaction_id}`

Legacy compatibility alias for `GET /v1/decision-requests/{decision_request_id}`.

### `GET /v1/operations`

Returns recent control-plane operation events. Supports a `limit` query
parameter from 1 to 100. Operation events include `event_hash` and
`previous_hash`, so database provisioning, model promotion, healing approvals,
and drift decisions can be shown as a tamper-evident activity feed.

### `GET /v1/audit/integrity`

Verifies the hash chains for runtime decision events and control-plane operation
events. The response reports `valid` when every event hash matches its payload
and every `previous_hash` points to the prior event in the chain.
It reports `partial` when legacy rows predate hash-chain enforcement or match an
older hash payload format, and `invalid` when the verifier finds a true mismatch.

## Database Provisioning API

### `GET /v1/database/status`

Returns the currently connected storage backend, configured storage URL, and
available backend options for the UI provisioning flow. The response also
includes control-plane persistence health so the UI can show whether operational
state is durable.

### `POST /v1/database/provision`

Provisions or connects runtime storage and hot-swaps the running engine to the
new store. Requires `model-risk` or `admin`.

SQLite request:

```json
{
  "backend": "sqlite",
  "path": "data/tenta.sqlite3",
  "persist": true
}
```

Postgres request:

```json
{
  "backend": "postgres",
  "storage_url": "postgresql://tenta:tenta@127.0.0.1:5432/tenta",
  "compose_file": "compose.yaml",
  "service": "postgres",
  "start": true,
  "wait": true,
  "persist": true
}
```

When `storage_url`, `compose_file`, or `service` are omitted, the runtime uses
the local development defaults above. Postgres provisioning runs Docker Compose,
waits for the configured service healthcheck, then connects the runtime and
control plane to the database. It requires Docker and the optional
`tenta[postgres]` package extra. Failures are written to the operations ledger.

When `persist` is true, the runtime writes the selected storage URL to
`data/tenta-runtime.json` so future `tenta serve` runs can use the same backend.

## Operations Console API

These endpoints are backed by the runtime control plane and are used by the
dashboard/console. State is persisted through the configured runtime storage
backend.

Mutating requests accept governance metadata:

- `actor`
- `role`
- `source`
- `request_id`
- `reason`

Supported roles are `analyst`, `detector`, `operator`, `model-risk`, and
`admin`. Dangerous operations are role-gated. Denied attempts return `403` and
write a `governance.denied` operation event with the allowed roles.

- `GET /v1/overview`
- `GET /v1/workloads`
- `GET /v1/workloads/active`
- `GET /v1/workloads/{workload_id}`
- `GET /v1/workloads/{workload_id}/export`
- `GET /v1/workloads/{workload_id}/sample`
- `POST /v1/workloads/validate`
- `POST /v1/workloads/activate`
- `POST /v1/workloads/import`
- `GET /v1/models`
- `GET /v1/models/{model_id}/endpoint`
- `POST /v1/models/load`
- `POST /v1/models/{model_id}/promote`
- `POST /v1/models/rollback`
- `GET /v1/drift`
- `POST /v1/drift/events`
- `POST /v1/drift/{monitor_id}/acknowledge`
- `POST /v1/drift/{monitor_id}/escalate`
- `GET /v1/policy/history`
- `GET /v1/operations`
- `GET /v1/audit/integrity`
- `GET /v1/feedback`
- `POST /v1/feedback`
- `GET /v1/benchmarks`

### Model Registry And Serving Endpoints

`GET /v1/models` returns registered models, available signed artifacts, and the
current `serving_endpoint`. Each model row is also decorated with its own
`serving_endpoint` object. Only the champion returns a live `url`; candidates,
shadow models, fallbacks, and archived models return `status:
registered_not_serving`.

`GET /v1/models/{model_id}/endpoint` returns the serving status for one model.
This is useful after a Timber artifact is uploaded, loaded, or promoted.

`POST /v1/models/load`, `POST /v1/models/upload`,
`POST /v1/models/{model_id}/promote`, and `POST /v1/models/rollback` return the
model record plus `serving_endpoint`. When a model is promoted to `champion`,
the response contains the app-facing URL to use:

```json
{
  "model_id": "fraud-xgb-v13-rc2",
  "version": "13.0.0-rc2",
  "stage": "champion",
  "serving_endpoint": {
    "status": "serving",
    "url": "http://127.0.0.1:8080/v1/decision-requests",
    "method": "POST",
    "contract": "decision_request.v1",
    "serving_mode": "governed_decision_runtime"
  }
}
```

### `POST /v1/feedback`

Records analyst or outcome feedback for a decision request and updates the
feedback summary. When the request already exists in decision memory, the
runtime can fill in `model_decision` from the stored decision.

```json
{
  "decision_request_id": "req-001",
  "outcome_label": "expected",
  "delay_hours": 1.5,
  "segment": "Mobile",
  "actor": "analyst@example.com"
}
```

`outcome_label` accepts `adverse` or `expected`; legacy clients may continue
sending `analyst_label` as `fraud` or `legit`.

### `POST /v1/drift/events`

Records a detector signal, updates or creates the matching drift monitor, and
proposes a policy-gated healing action when severity is `warn` or `critical`.

```json
{
  "segment": "Channel · Mobile",
  "feature": "velocity_10m",
  "detector": "Population Stability Index",
  "statistic": 0.18,
  "threshold": 0.1,
  "confidence": 0.91,
  "population": 24000,
  "actor": "detector@runtime"
}
```

## Healing API

### `GET /v1/healing/actions`

Lists proposed, approved, rejected, running, and rolled-back healing actions.

### `POST /v1/healing/actions/{action_id}/approve`

Approves a policy-gated action when the caller has permission, then executes
the bounded effect. The response includes `execution`, `outcome`, and
`rollback_criteria` details when execution succeeds.

### `POST /v1/healing/actions/{action_id}/rollback`

Rolls back an executed or running healing action and records the reverted effect
in the operation ledger.
