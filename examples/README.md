# Examples

Runnable examples for the Tenta Decision Runtime.

## Decision Request

Start the runtime, then send a sample decision request:

```bash
tenta serve --host 127.0.0.1 --port 8080
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
