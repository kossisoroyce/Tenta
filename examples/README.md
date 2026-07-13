# Examples

Runnable examples for the Tenta Decision Runtime.

## Decision Request

Start the runtime, then send a sample decision request:

```bash
tenta serve --host 127.0.0.1 --port 8080
```

Open the dashboard and create the first local admin. For CLI commands that
change control-plane state, create an API key under Governance and export it:

```bash
export TENTA_API_KEY='tenta_key_...'
```

```bash
curl -s http://127.0.0.1:8080/v1/decision-requests \
  -H 'Content-Type: application/json' \
  -d @examples/decision_request.json
```

The same payload can be sent through the CLI:

```bash
tenta decide --payload examples/decision_request.json --url http://127.0.0.1:8080
```

## Timber Model Registration

`decision-risk-v14.tenta.json` is a local Timber manifest fixture. The runtime
verifies the referenced artifact hash, signature metadata, active workload
feature contract, and replay pack before promotion.

```bash
tenta model register examples/decision-risk-v14.tenta.json --url http://127.0.0.1:8080
tenta model promote decision-risk-xgb-v14 --stage champion \
  --reason "Validated replay and rollback plan" \
  --url http://127.0.0.1:8080
tenta endpoint --url http://127.0.0.1:8080
```

After promotion, applications keep calling the governed decision endpoint:

```text
POST http://127.0.0.1:8080/v1/decision-requests
```

## Workload Import

`claims_triage_workload.json` shows how a domain pack can remap request fields,
features, thresholds, reason labels, and sample payloads without changing the
runtime engine.

```bash
tenta workload import examples/claims_triage_workload.json \
  --activate \
  --url http://127.0.0.1:8080
```

Then validate and score the workload sample:

```bash
tenta workload sample claims_triage --url http://127.0.0.1:8080
tenta replay run --workload-id decision_risk --url http://127.0.0.1:8080
```

## Storage Provisioning

SQLite is embedded and works without external services:

```bash
tenta db provision-sqlite --path data/tenta.sqlite3 --url http://127.0.0.1:8080
```

For local Postgres, install the optional dependency and use the provisioning
payload or CLI command:

```bash
pip install -e '.[postgres]'
tenta db provision-postgres --url http://127.0.0.1:8080
```

```bash
curl -s http://127.0.0.1:8080/v1/database/provision \
  -H 'Content-Type: application/json' \
  -d @examples/postgres_provision.json
```

All examples use synthetic data. Do not commit real customer, patient,
financial, security, or operational records.
