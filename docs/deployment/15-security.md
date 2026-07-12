# 15 - Security

Tenta sits in front of high-impact decision systems. Treat requests, model
outputs, feedback labels, control-plane operations, and audit trails as
sensitive, even when the first local examples use synthetic data.

## Security Controls

- Encrypt data in transit and at rest.
- Enforce least-privilege access to decision, feedback, feature, model, and
  storage systems.
- Enforce runtime governance roles for mutating operations and audit denied
  attempts as first-class operation events.
- Keep decision and operation logs immutable or export them to immutable
  storage in production.
- Protect model artifacts, registry credentials, database URLs, and signing keys.
- Redact credentials from API responses, logs, operation events, and dashboard
  state.
- Require signed model and policy artifacts before production use. The planned
  Timber integration should refuse to load artifacts whose signatures do not
  verify against trusted keys.
- Store production artifacts with authenticated encryption and versioned
  provenance metadata.
- Rate-limit sensitive APIs such as model promotion, database provisioning,
  workload activation, and healing approval.
- Monitor abnormal approval, rollback, workload-import, storage-switch, and
  threshold-change behavior.

## Privacy Controls

- Minimize stored raw request fields.
- Tokenize subject, account, customer, patient, device, merchant, policy,
  application, or identity identifiers when possible.
- Define retention by data class and workload domain.
- Restrict access to analyst labels, delayed outcomes, feedback notes, and
  operational metadata.
- Keep screenshots, examples, fixtures, and replay packs synthetic unless an
  explicit anonymization review has happened.

## Model Risk Controls

- Treat model promotion, threshold changes, workload activation, healing
  approval, and storage switching as governed operations.
- Require rollback metadata for production model changes.
- Run online-learning and adaptive-healing behavior in shadow mode before it can
  affect live decisions.
- Record the actor, role, source, request id, reason, target, result, and event
  hash for mutating operations.
- Keep decision idempotency records durable so retries cannot silently mutate
  audit history.

## Abuse Resistance

The runtime should reveal operational health to authorized operators while
avoiding public details that help attackers infer sensitive policies,
thresholds, model behavior, detector behavior, or customer-specific decision
patterns.
