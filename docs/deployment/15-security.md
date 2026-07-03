# 15 - Security

Fraud detection platforms handle sensitive signals, high-impact decisions, and adversarial pressure.

## Security Controls

- Encrypt data in transit and at rest.
- Enforce least-privilege access to decision, feedback, and feature stores.
- Keep audit logs immutable.
- Protect model artifacts and registry credentials.
- Require signed model and policy artifacts before production use.
- Rate-limit sensitive APIs.
- Monitor for abnormal approval, rollback, and threshold-change behavior.

## Privacy Controls

- Minimize stored raw transaction fields.
- Tokenize account, card, device, and merchant identifiers when possible.
- Define retention by data class.
- Restrict access to analyst labels and customer dispute data.

## Abuse Resistance

The platform should reveal operational health to authorized users while avoiding public details that help attackers infer fraud rules, thresholds, or detector behavior.

