# PRD: Audit Export Tooling


## Summary


Tenta already records hash-chained decision events and operation events, and it
can verify those chains through the runtime API. The next audit milestone is to
turn that internal integrity data into portable, regulator-friendly audit
packages: signed exports, deeper chain inspection, and operational reports that
can be shared outside the running runtime without losing provenance.


This feature adds an audit/export surface for model-risk, compliance, and
operations teams. It should let an authorized user select an audit window,
export decision and operation evidence, verify the export offline, inspect chain
continuity, and generate human-readable reports for review.


## Problem


The current audit surface answers one narrow question: whether the decision and
operation hash chains are valid inside the active store. That is useful during
runtime operation, but it is not enough for audits, incident reviews, compliance
requests, or model-risk committees.


Users need to answer broader questions:


- What decisions happened during a specific window?
- Which model, workload, and policy version produced those decisions?
- Were any decisions made in degraded mode?
- Which model promotions, healing approvals, database changes, or workload
  changes happened near the same time?
- Can the exported evidence be verified after it leaves the runtime?
- Is the exported chain complete, partial, or broken?


## Goals


- Export signed audit bundles for decision and operation evidence.
- Support offline verification of exported bundles.
- Provide chain inspection beyond the current summary status.
- Generate operational reports for audit windows.
- Expose the feature through API and CLI first, with dashboard support after the
  backend contract stabilizes.
- Preserve Tenta's current no-required-dependencies runtime posture.


## Non-Goals


- This feature does not implement long-term archival storage.
- This feature does not implement a full SIEM integration.
- This feature does not export raw sensitive feature payloads by default.
- This feature does not replace the existing runtime integrity endpoint.
- This feature does not introduce external key management in the first version.


## Users


- Model-risk reviewer: needs evidence for model promotion, rollback, and policy
  changes.
- Compliance reviewer: needs a portable package showing what happened during a
  regulated review window.
- Runtime operator: needs to inspect chain gaps, degraded events, and suspicious
  operational changes.
- Incident responder: needs a compact report around an incident window.


## Current State


Implemented today:


- Decision events include `previous_hash` and `event_hash`.
- Operation events include `previous_hash` and `event_hash`.
- `GET /v1/audit/integrity` verifies decision and operation chains.
- CLI command `tenta audit verify` calls the integrity endpoint.
- Decision and operation stores can list recent events.


Gaps:


- No export bundle format.
- No export signing.
- No offline verifier.
- No chain segment inspection by event id, hash, or time window.
- No operational report generation.
- No dashboard export workflow.


## Requirements


### Audit Bundle Export


The runtime must support exporting an audit bundle for a caller-selected window.


Minimum bundle contents:


- `manifest.json`
- `decisions.jsonl`
- `operations.jsonl`
- `integrity.json`
- `report.json`
- `signature.json`


The manifest must include:


- export id
- export format version
- runtime version
- generated timestamp
- requested time window
- included chains
- event counts
- first and last event hashes per chain
- storage backend metadata with sensitive values redacted
- active workload id
- active model id and version when available
- report hash
- file hashes for every bundle file except `signature.json`


The export must support these modes:


- decisions only
- operations only
- decisions and operations
- report only
- full bundle


Default behavior should export decisions and operations for the requested
window, plus integrity and report metadata.


### Signing


The first version should use a local signing key managed by Tenta.


Requirements:


- Generate a local audit signing key if none exists.
- Store the signing key in the runtime storage or config path with restrictive
  local file permissions when file-backed.
- Include the public verification key or key fingerprint in the export.
- Sign the canonical manifest hash.
- Fail closed if signing is requested but no signing key can be loaded or
  generated.


The signing implementation may use stdlib cryptographic primitives for the
first version if Ed25519 is not available without adding dependencies. The
format should leave room for Ed25519 or external KMS support later.


### Offline Verification


A user must be able to verify an exported bundle without a running Tenta server.


The verifier must check:


- all files listed in `manifest.json` exist
- file hashes match the manifest
- manifest canonical hash matches `signature.json`
- signature is valid
- decision chain continuity within the exported segment
- operation chain continuity within the exported segment
- whether the segment is complete or partial relative to the manifest metadata


The verifier should produce machine-readable JSON and a concise human-readable
summary.


### Chain Inspection


The backend must provide better chain inspection for the active store.


Users should be able to inspect:


- chain head and tail
- event count and verified count
- first broken link, if any
- event before and after a selected event hash
- events around a selected transaction id or operation id
- partial-window continuity, including boundary hashes


The API should not require loading unbounded history into memory. Limit and
window parameters must be bounded.


### Operational Reports


The report should summarize audit-relevant activity during the selected window.


Minimum report sections:


- Runtime summary
- Decision volume and decision mix
- Model versions observed
- Policy versions observed
- Workloads observed
- Degraded-mode decisions
- Top reason codes
- Operation activity by type
- Model promotions and rollbacks
- Healing approvals, executions, rejections, and rollbacks
- Drift acknowledgements and escalations
- Database provisioning or connection changes
- Audit chain status


Reports should be emitted as JSON in version one. Markdown output is desirable
for CLI and dashboard download, but JSON is the canonical report format.


### API


Add authenticated control-plane endpoints:


- `POST /v1/audit/exports`
- `GET /v1/audit/exports/{export_id}`
- `GET /v1/audit/exports/{export_id}/download`
- `POST /v1/audit/exports/verify`
- `GET /v1/audit/chains/{chain}`
- `GET /v1/audit/chains/{chain}/events`


`chain` must be one of:


- `decisions`
- `operations`


Export creation request:


```json
{
  "start_time": "2026-07-18T00:00:00Z",
  "end_time": "2026-07-18T23:59:59Z",
  "chains": ["decisions", "operations"],
  "format": "bundle",
  "include_report": true,
  "sign": true,
  "reason": "Quarterly model-risk audit"
}
```


Export creation response:


```json
{
  "export_id": "audit_exp_20260718_001",
  "status": "ready",
  "format_version": "tenta.audit-export.v1",
  "created_at": "2026-07-18T18:00:00Z",
  "download_url": "/v1/audit/exports/audit_exp_20260718_001/download",
  "signature": {
    "algorithm": "hmac-sha256",
    "key_fingerprint": "sha256:..."
  },
  "counts": {
    "decisions": 1204,
    "operations": 31
  },
  "integrity": {
    "status": "valid"
  }
}
```


### CLI


Add CLI commands:


```bash
tenta audit export --from 2026-07-18T00:00:00Z --to 2026-07-18T23:59:59Z --output audit-bundle.tgz
tenta audit inspect --chain decisions --limit 50
tenta audit inspect --chain operations --around-hash sha256:...
tenta audit verify-export audit-bundle.tgz
tenta audit report --from 2026-07-18T00:00:00Z --to 2026-07-18T23:59:59Z --output report.json
```


The CLI should support `--json` for machine-readable output where the default is
human-readable.


### Dashboard


Add an Audit Exports workflow under Governance or a dedicated Audit view.


The dashboard should allow authorized users to:


- choose a time window
- choose decisions, operations, or both
- create a signed export
- download the bundle
- see recent exports
- view chain status and first broken link
- view report summaries


The dashboard should not expose raw signing keys.


## Authorization


Export creation and download are sensitive. Initial permissions:


- `audit.export`: admin, model-risk
- `audit.verify`: admin, model-risk, operator
- `audit.inspect`: admin, model-risk, operator
- `audit.report`: admin, model-risk, operator


Every export creation must record an operation event with:


- actor
- role
- source
- request id
- reason
- requested window
- chains included
- output format
- export id
- signing key fingerprint


## Data Safety


Default exports must avoid raw sensitive payloads. Decision exports should use
the existing decision event shape unless a future explicit option includes
feature snapshots.


Rules:


- Redact storage URLs and credentials.
- Do not include session tokens or API key tokens.
- Include API key ids only when they already appear in operation context.
- Prefer ids, versions, hashes, timestamps, decisions, reason codes, and
  policy metadata over raw user data.


## Acceptance Criteria


- A model-risk user can create a signed audit bundle through the API.
- The CLI can download or create an export bundle from a running runtime.
- The CLI can verify the bundle offline and report valid, partial, or invalid.
- Chain inspection can identify the first broken link in a tampered test store.
- Operational reports summarize decisions, operations, model changes, healing
  actions, drift actions, degraded decisions, and chain status.
- Export creation records a hash-chained operation event.
- Tests cover successful export, invalid signature, tampered file, broken chain,
  partial chain window, authorization failure, and redaction.


## Implementation Plan


1. Add audit export domain models and bundle serialization.
2. Add local signing-key management and canonical manifest hashing.
3. Add store query methods for bounded time-window event retrieval.
4. Add export generation service.
5. Add offline bundle verifier.
6. Add operational report builder.
7. Add API routes and governance permissions.
8. Add CLI commands.
9. Add dashboard workflow.
10. Add tests and example export fixtures.


## Suggested Files


Likely new runtime modules:


- `runtime/tenta_runtime/audit_exports.py`
- `runtime/tenta_runtime/audit_reports.py`
- `runtime/tenta_runtime/audit_signing.py`


Likely changed files:


- `runtime/tenta_runtime/storage.py`
- `runtime/tenta_runtime/storage_postgres.py`
- `runtime/tenta_runtime/control_plane_store.py`
- `runtime/tenta_runtime/console_api.py`
- `runtime/tenta_runtime/governance.py`
- `runtime/tenta_runtime/cli.py`
- `dashboard/src/api.ts`
- `dashboard/src/views/Governance.tsx`
- `tests/test_audit_integrity.py`


Likely new tests:


- `tests/test_audit_exports.py`
- `tests/test_audit_reports.py`


## Open Decisions


- Should v1 use HMAC-SHA256 with a local secret or require an asymmetric signing
  format from the start?
- Should exports be stored in the runtime database, on disk under `data/audit`,
  or generated on demand?
- How long should generated exports be retained?
- Should dashboard downloads stream from the runtime or return a prebuilt
  archive path?
- Should Markdown/PDF reports be in scope for v1 or deferred until JSON reports
  are stable?


## Milestones


### Milestone 1: Backend Export Core


- Bundle format
- Signing
- Offline verification
- Unit tests


### Milestone 2: API and CLI


- Authenticated export endpoints
- Chain inspection endpoints
- CLI export, inspect, verify, and report commands
- Integration tests


### Milestone 3: Dashboard Workflow


- Export creation UI
- Recent exports
- Chain inspection view
- Report summary panels


### Milestone 4: Hardening


- Postgres parity
- Tamper fixtures
- Redaction tests
- Documentation and examples