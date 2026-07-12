# 13 - Database Schema

The schema should separate immutable audit events from query-optimized operational views.

## Core Tables

### `schema_migrations`

- `component`
- `version`
- `applied_at`

Every storage backend records applied schema versions. Runtime decision storage
and control-plane storage use separate migration components.

### `decision_events`

- `id`
- `transaction_id`
- `event_time`
- `model_id`
- `model_version`
- `policy_version`
- `score`
- `decision`
- `reason_codes`
- `latency_ms`
- `degraded_mode`
- `previous_hash`
- `event_hash`
- `created_at`

`previous_hash` and `event_hash` form a tamper-evident event chain. New events
hash their canonical payload plus the previous event hash.

### `idempotency_keys`

- `transaction_id`
- `fingerprint`
- `response_json`
- `created_at`

### `control_plane_snapshots`

- `namespace`
- `payload_json`
- `updated_at`

The first persistence pass stores the operational control plane as a versioned
snapshot. This keeps model registry state, active model, healing actions, drift
monitors, feedback, benchmarks, and policy history durable while the individual
relational tables mature.

### `operation_events`

- `id`
- `operation_type`
- `actor`
- `target`
- `status`
- `request_json`
- `result_json`
- `message`
- `previous_hash`
- `event_hash`
- `created_at`

Control-plane mutations write append-only operation events. The embedded
runtime records database provisioning, model load/upload/promotion/rollback,
healing proposal/approval/execution/rejection/rollback, drift signal ingestion,
drift acknowledgement/escalation, and feedback ingestion here. `previous_hash`
and `event_hash` provide the same local tamper-evident chain as decision events.
The canonical `event_json` also includes governance metadata: `role`, `source`,
`request_id`, and `reason`.

### `feedback_events`

- `id`
- `transaction_id`
- `feedback_type`
- `label`
- `source`
- `event_time`
- `confidence`

### `drift_events`

- `id`
- `detector`
- `segment`
- `baseline_window`
- `current_window`
- `metric`
- `severity`
- `created_at`

### `healing_actions`

- `id`
- `action_type`
- `status`
- `proposed_by`
- `policy_version`
- `risk_level`
- `payload`
- `created_at`
- `executed_at`
- `rollback_at`

## Storage Notes

High-volume decision events may require partitioning by time and tenant. Sensitive feature payloads should be tokenized, minimized, or stored behind stricter access controls.

The embedded runtime uses SQLite for self-contained local operation and tests.
Production and multi-process deployments should use the same `RuntimeStore`
contract with the Postgres adapter so audit, memory, idempotency, and healing
workflows share transactional guarantees.

Runtime storage URLs:

- `memory`
- `sqlite:data/tenta.sqlite3`
- `postgresql://tenta:tenta@127.0.0.1:5432/tenta`

Run migrations explicitly with:

```bash
tenta db migrate --storage-url sqlite:data/tenta.sqlite3
```
