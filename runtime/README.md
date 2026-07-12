# Runtime

Low-latency decision runtime.

The runtime loads Timber-compiled classical ML models as native shared
libraries and invokes them through the model wrapper. Because inference is a
direct C function call into a signed, dependency-free artifact rather than a
Python service hop, the runtime can hold tight p99 budgets under high decision
volume.

Planned responsibilities:

- Receive decision requests.
- Fetch online features.
- Verify the signature of the loaded Timber artifact on load.
- Call model wrappers (which dispatch to Timber-compiled native inference).
- Apply policy decisions.
- Emit structured decision events.
- Maintain safe fallback behavior, including hot-swap to a previous signed artifact.

## Current Implementation

The first implementation slice is a dependency-free Python runtime package in
[`runtime/tenta_runtime`](tenta_runtime/). It provides:

- Decision request validation for the documented `POST /v1/decision-requests`
  contract, with `/v1/score` kept as a compatibility alias.
- A workload registry for request aliases, feature aliases, policy thresholds,
  reason labels, outcome labels, and sample payloads.
- A stable `ModelWrapper` interface with a deterministic rule-based baseline model.
- Threshold policy decisions for `allow`, `review`, and `block`.
- Structured decision events with in-memory and JSONL audit sinks.
- Pluggable runtime storage with in-memory, embedded SQLite, and optional
  Postgres backends.
- Persistent control-plane snapshots for model registry, active model, healing,
  drift, feedback, benchmarks, and policy history.
- App-facing serving endpoint discovery for the current champion model.
- Analyst feedback ingestion that updates feedback memory and records an
  operation event.
- Drift signal ingestion that updates monitors and proposes policy-gated healing
  actions.
- Healing execution for approved actions, including policy threshold changes,
  runtime controls, and rollback effect metadata.
- Role-gated governance for mutating operations, including denied-attempt audit
  events.
- Hash-chained operation events for provisioning, model, healing, and drift
  control-plane mutations.
- Audit integrity verification for decision and operation hash chains.
- A small stdlib HTTP API exposing `POST /v1/decision-requests`,
  `GET /v1/health`, `GET /v1/decisions`, and
  `GET /v1/decision-requests/{decision_request_id}`.
- A static dashboard served from [`dashboard`](../dashboard/) at `/`.

The rule-based model is a local development backend. Production integration should
replace it with a wrapper that verifies and dispatches to a signed Timber artifact.

## Run Tests

```bash
python3 -m unittest discover -s tests
```

## Run Locally

```bash
PYTHONPATH=runtime python3 -m tenta_runtime serve --host 127.0.0.1 --port 8080
```

By default, local runtime state is stored through the storage URL
`sqlite:data/tenta.sqlite3`. This keeps the core engine self-contained while
preserving decision audit events and idempotency records across restarts.

Storage options:

```bash
PYTHONPATH=runtime python3 -m tenta_runtime serve --memory-storage
PYTHONPATH=runtime python3 -m tenta_runtime serve --storage-url sqlite:data/custom.sqlite3
PYTHONPATH=runtime python3 -m tenta_runtime serve --storage-url postgresql://tenta:tenta@127.0.0.1:5432/tenta
```

The JSONL audit sink is still available as an additional append-only export:

```bash
PYTHONPATH=runtime python3 -m tenta_runtime serve --audit-path audit/decisions.jsonl
```

## CLI Utility

When installed, the package exposes `tenta`:

```bash
tenta serve
tenta health --url http://127.0.0.1:8080
tenta endpoint --url http://127.0.0.1:8080
tenta decide --url http://127.0.0.1:8080 --sample
tenta score --url http://127.0.0.1:8080 --sample
tenta decisions --url http://127.0.0.1:8080 --limit 10
tenta decision req-001 --url http://127.0.0.1:8080
tenta transaction txn-001 --url http://127.0.0.1:8080
tenta operations --url http://127.0.0.1:8080 --limit 10
tenta audit verify --url http://127.0.0.1:8080
tenta model list --url http://127.0.0.1:8080
tenta model register examples/decision-risk-v14.tenta.json --url http://127.0.0.1:8080
tenta model promote decision-risk-xgb-v14 --stage champion --url http://127.0.0.1:8080
tenta model endpoint decision-risk-xgb-v14 --url http://127.0.0.1:8080
tenta workload list --url http://127.0.0.1:8080
tenta workload active --url http://127.0.0.1:8080
tenta workload validate --url http://127.0.0.1:8080 --payload request.json --workload-id decision_risk
tenta workload export decision_risk --url http://127.0.0.1:8080 --output decision-risk.json
tenta workload import decision-risk.json --url http://127.0.0.1:8080 --activate
tenta workload activate payment_fraud --url http://127.0.0.1:8080
tenta replay list
tenta replay run --url http://127.0.0.1:8080
tenta feedback req-001 --label expected --url http://127.0.0.1:8080
tenta drift record --segment Mobile --feature velocity_10m --detector PSI --statistic 0.18 --threshold 0.1 --url http://127.0.0.1:8080
tenta db status --url http://127.0.0.1:8080
tenta db provision-sqlite --url http://127.0.0.1:8080 --path data/tenta.sqlite3
tenta db provision-postgres --url http://127.0.0.1:8080
tenta db connect postgresql://tenta:tenta@127.0.0.1:5432/tenta --url http://127.0.0.1:8080
tenta db migrate --storage-url sqlite:data/tenta.sqlite3
```

The same commands work through the module entry point during local development:

```bash
PYTHONPATH=runtime python3 -m tenta_runtime health --url http://127.0.0.1:8080
```

## Workloads

Workload specs are packaged in
[`runtime/tenta_runtime/workload_packs`](tenta_runtime/workload_packs/). The
default active workload is `decision_risk`, a generic domain-neutral risk
workload. `payment_fraud` remains as a compatibility/reference workload pack.

Specs define:

- request field aliases such as `amount` -> `value`
- feature aliases such as `entity_risk` -> the model's canonical risk signal
- review/block policy thresholds
- reason-code labels
- outcome labels
- sample payloads

The running runtime exposes them through `/v1/workloads`, validates payloads
with `/v1/workloads/validate`, and records workload activation/import as
`workload.activate` and `workload.import` operation events. The active workload
id is persisted in `data/tenta-runtime.json`; imported specs are persisted in
`data/workloads` when `persist` is true.

## Serving Endpoint Discovery

Timber produces the signed native model artifact, but applications should call
Tenta's governed decision endpoint:

```bash
tenta endpoint --url http://127.0.0.1:8080
```

The response includes the active champion model, workload id, method, contract,
and URL:

```json
{
  "status": "serving",
  "url": "http://127.0.0.1:8080/v1/decision-requests",
  "method": "POST",
  "contract": "decision_request.v1",
  "serving_mode": "governed_decision_runtime"
}
```

Model load, upload, promote, rollback, and registry responses include the same
`serving_endpoint` object. Only the champion model reports a live app endpoint;
candidate and shadow models remain registered but not app-facing.

## Timber Artifact Manifests

Tenta registers Timber outputs through a manifest file. The manifest binds the
model id/version, artifact path, SHA-256 digest, signature metadata, active
workload feature contract, offline metrics, and local replay predictor mode.

```bash
tenta model register examples/decision-risk-v14.tenta.json --url http://127.0.0.1:8080
tenta model promote decision-risk-xgb-v14 --stage champion --url http://127.0.0.1:8080
```

Promotion to `shadow` or `champion` requires:

- artifact file exists and matches the manifest SHA-256
- signature metadata is marked verified
- manifest workload id matches the active workload
- manifest feature contract covers every active workload feature
- active workload replay fixtures pass with the candidate wrapper

The first `TimberModelWrapper` supports a deterministic `rule_based` local
predictor so manifests can be exercised without a native library in tests and
examples. Native Timber ABI dispatch belongs behind the same wrapper contract.

## Replay Fixtures

Packaged replay fixtures live in
[`runtime/tenta_runtime/replay_fixtures`](tenta_runtime/replay_fixtures/).
They provide small regression packs per workload so the same runtime can be
checked across generic and domain-specific decision contexts.

```bash
tenta replay list
tenta replay run --url http://127.0.0.1:8080
tenta replay run --workload-id payment_fraud --url http://127.0.0.1:8080
```

## Database Provisioning

The runtime supports one-click-style database setup through the same core used
by the CLI.

SQLite can be provisioned and connected immediately:

```bash
tenta db provision-sqlite --url http://127.0.0.1:8080 --path data/tenta.sqlite3
```

To initialize storage without a running server:

```bash
tenta db init --storage-url sqlite:data/tenta.sqlite3
```

For Postgres, the runtime can start the local Compose service and connect in
one command:

```bash
pip install -e '.[postgres]'
tenta db provision-postgres --url http://127.0.0.1:8080
```

Use `--no-start` when an existing Postgres server is already running and you
only want the runtime/control-plane hot swap.

These commands persist the selected storage URL in `data/tenta-runtime.json`
unless `--no-persist` is passed. The HTTP equivalent is
`POST /v1/database/provision`.

Database provisioning now moves both runtime audit/memory and control-plane
state. If an operator promotes a model, approves a healing action, acknowledges
drift, or uploads a candidate model, that state is saved and restored on the
next `tenta serve`. Provisioning and other control-plane mutations are also
written to the operations ledger exposed by `GET /v1/operations`.

## Governance

Mutating HTTP requests can include `actor`, `role`, `source`, `request_id`, and
`reason`. Roles are `analyst`, `detector`, `operator`, `model-risk`, and
`admin`. The runtime currently infers a compatible role for local dashboard and
CLI actors when `role` is omitted, but explicit roles are enforced. Denied
attempts return `403` and are written as `governance.denied` operation events.

## Healing Execution

Approved healing actions are executed immediately after approval. Supported
effects include bounded policy threshold changes, manual-review overlays,
fallback traffic controls, shadow-scoring toggles, and online-learning toggles.
Execution writes `healing.execute` to the operations ledger and stores rollback
criteria on the action. Rolling back an action restores the previous effect
where the executor has enough state to do so.

## Migrations And Audit Integrity

Runtime and control-plane stores record schema versions in `schema_migrations`.
The current embedded SQLite backend migrates legacy decision tables in place.

```bash
tenta db migrate --storage-url sqlite:data/tenta.sqlite3
```

Decision audit events include:

- `previous_hash`
- `event_hash`

These fields form a hash chain over canonical decision payloads. This is not a
replacement for signed immutable storage, but it gives the local and Postgres
backends a tamper-evident audit trail. Operation events use the same hash-chain
shape, so administrative actions can be inspected beside runtime decisions.

To verify both chains from a running runtime:

```bash
tenta audit verify --url http://127.0.0.1:8080
```

## Local Postgres

SQLite is the embedded default. For the serious local backend path, start
Postgres with:

```bash
docker compose up -d postgres
```

Then run:

```bash
pip install -e '.[postgres]'
PYTHONPATH=runtime python3 -m tenta_runtime serve \
  --storage-url postgresql://tenta:tenta@127.0.0.1:5432/tenta
```

Example decision request:

```bash
curl -s http://127.0.0.1:8080/v1/decision-requests \
  -H 'Content-Type: application/json' \
  -d '{
    "decision_request_id": "req-001",
    "subject_id": "subject-001",
    "context_id": "reference-workload",
    "value": 120,
    "currency": "USD",
    "channel": "web",
    "requested_at": "2026-07-11T12:00:00Z",
    "features": {
      "entity_risk": 0.2,
      "velocity_10m": 2,
      "subject_age_days": 180
    }
  }'
```
