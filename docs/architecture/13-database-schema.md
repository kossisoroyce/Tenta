# 13 - Database Schema

The schema should separate immutable audit events from query-optimized operational views.

## Core Tables

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

