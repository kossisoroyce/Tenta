import unittest
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))

from tenta_runtime import (  # noqa: E402
    DecisionPolicy,
    IdempotencyConflictError,
    InMemoryAuditSink,
    PayloadValidationError,
    run_replay,
    RuleBasedModelWrapper,
    RuntimeEngine,
)


def base_payload(**overrides):
    payload = {
        "transaction_id": "txn-001",
        "account_id": "acct-001",
        "amount": 120.0,
        "currency": "usd",
        "merchant_id": "merchant-001",
        "channel": "card_present",
        "event_time": "2026-07-11T12:00:00Z",
        "features": {
            "merchant_risk": 0.1,
            "velocity_10m": 1,
            "account_age_days": 400,
            "chargeback_count": 0,
        },
    }
    payload.update(overrides)
    return payload


class RuntimeEngineTests(unittest.TestCase):
    def setUp(self):
        self.audit = InMemoryAuditSink()
        self.engine = RuntimeEngine(
            model=RuleBasedModelWrapper(),
            policy=DecisionPolicy(),
            audit_sink=self.audit,
        )

    def test_scores_low_risk_transaction_as_allow(self):
        response = self.engine.score(base_payload())

        self.assertEqual(response["transaction_id"], "txn-001")
        self.assertEqual(response["decision"], "allow")
        self.assertEqual(response["model_id"], "fraud-rule-baseline")
        self.assertEqual(response["policy_version"], "policy-baseline-0.1.0")
        self.assertIn("score_below_review_threshold", response["reason_codes"])

        events = self.audit.list_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].transaction_id, "txn-001")
        self.assertEqual(events[0].decision, "allow")

    def test_accepts_decision_runtime_payload_aliases(self):
        response = self.engine.score(
            {
                "decision_request_id": "req-runtime-001",
                "subject_id": "subject-001",
                "context_id": "reference-workload",
                "value": 120.0,
                "currency": "usd",
                "channel": "api",
                "requested_at": "2026-07-11T12:00:00Z",
                "features": {
                    "entity_risk": 0.1,
                    "velocity_10m": 1,
                    "subject_age_days": 400,
                    "prior_adverse_events": 0,
                    "high_risk_segment": False,
                },
            }
        )

        self.assertEqual(response["transaction_id"], "req-runtime-001")
        self.assertEqual(response["decision_request_id"], "req-runtime-001")
        self.assertEqual(response["decision"], "allow")

    def test_scores_high_risk_transaction_as_block(self):
        response = self.engine.score(
            base_payload(
                amount=9000,
                features={
                    "merchant_risk": 0.98,
                    "velocity_10m": 30,
                    "account_age_days": 2,
                    "chargeback_count": 5,
                    "is_high_risk_country": True,
                },
            )
        )

        self.assertEqual(response["decision"], "block")
        self.assertIn("score_above_block_threshold", response["reason_codes"])
        self.assertIn("merchant_risk_high", response["reason_codes"])
        self.assertIn("velocity_high", response["reason_codes"])

    def test_idempotent_retry_returns_cached_response_without_new_event(self):
        payload = base_payload()
        first = self.engine.score(payload)
        second = self.engine.score(dict(payload))

        self.assertEqual(first, second)
        self.assertEqual(len(self.audit.list_events()), 1)

    def test_reused_transaction_id_with_different_payload_conflicts(self):
        self.engine.score(base_payload())

        with self.assertRaises(IdempotencyConflictError):
            self.engine.score(base_payload(amount=250.0))

    def test_validation_rejects_missing_required_fields(self):
        payload = base_payload()
        del payload["account_id"]

        with self.assertRaises(PayloadValidationError):
            self.engine.score(payload)

    def test_health_reports_components(self):
        health = self.engine.health()

        self.assertEqual(health["status"], "healthy")
        self.assertEqual(health["model"]["status"], "healthy")
        self.assertEqual(health["policy"]["status"], "healthy")
        self.assertEqual(health["audit"]["status"], "healthy")
        self.assertEqual(health["workload"]["workload_id"], "decision_risk")

    def test_workload_registry_lists_and_validates_payloads(self):
        registry = self.engine.workload_registry()
        ids = {item["workload_id"] for item in registry["workloads"]}

        self.assertEqual(registry["active_workload_id"], "decision_risk")
        self.assertIn("payment_fraud", ids)

        validation = self.engine.validate_workload_payload(
            {
                "decision_request_id": "req-validate",
                "workload_id": "decision_risk",
                "subject_id": "subject-001",
                "context_id": "reference-workload",
                "value": 100,
                "currency": "USD",
                "channel": "api",
                "requested_at": "2026-07-11T12:00:00Z",
                "features": {
                    "entity_risk": 0.1,
                    "velocity_10m": 1,
                    "subject_age_days": 120,
                    "prior_adverse_events": 0,
                    "high_risk_segment": False,
                },
            }
        )

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["normalized"]["workload_id"], "decision_risk")
        self.assertIn("merchant_risk", validation["normalized"]["features"])

    def test_workload_activation_changes_policy_context(self):
        active = self.engine.activate_workload("payment_fraud")

        self.assertEqual(active["workload_id"], "payment_fraud")
        self.assertEqual(self.engine.policy.version, "fraud-policy-0.1.0")

        response = self.engine.score(
            base_payload(
                transaction_id="txn-payment-workload",
                workload_id="payment_fraud",
                merchant_id="merchant-001",
            )
        )

        self.assertEqual(response["workload_id"], "payment_fraud")
        self.assertEqual(response["policy_version"], "fraud-policy-0.1.0")

    def test_explicit_workload_uses_that_workload_policy_without_activation(self):
        response = self.engine.score(
            base_payload(
                transaction_id="txn-explicit-payment-workload",
                workload_id="payment_fraud",
                merchant_id="merchant-001",
            )
        )

        self.assertEqual(self.engine.workloads.active_id, "decision_risk")
        self.assertEqual(response["workload_id"], "payment_fraud")
        self.assertEqual(response["policy_version"], "fraud-policy-0.1.0")

    def test_import_export_workload_spec(self):
        spec = self.engine.export_workload("decision_risk")
        spec["workload_id"] = "decision_risk_variant"
        spec["name"] = "Decision Risk Variant"
        spec["policy"] = {**spec["policy"], "version": "variant-policy-0.1.0", "review_threshold": 0.5}

        imported = self.engine.import_workload(spec)
        activated = self.engine.activate_workload("decision_risk_variant")

        self.assertEqual(imported["workload_id"], "decision_risk_variant")
        self.assertEqual(activated["policy"]["version"], "variant-policy-0.1.0")
        self.assertEqual(self.engine.policy.review_threshold, 0.5)

    def test_replay_fixtures_pass_across_workloads(self):
        replay = run_replay(self.engine)

        self.assertEqual(replay["status"], "passed")
        self.assertEqual(replay["failed"], 0)
        self.assertGreaterEqual(replay["count"], 4)

    def test_recent_decisions_are_returned_newest_first(self):
        first = base_payload(transaction_id="txn-first", amount=100)
        second = base_payload(transaction_id="txn-second", amount=9000)

        self.engine.score(first)
        self.engine.score(second)

        payload = self.engine.decisions(limit=10)
        self.assertEqual([item["transaction_id"] for item in payload["decisions"]], ["txn-second", "txn-first"])

    def test_transaction_lookup_returns_decision_event(self):
        self.engine.score(base_payload(transaction_id="txn-lookup"))

        decision = self.engine.transaction("txn-lookup")

        self.assertIsNotNone(decision)
        self.assertEqual(decision["transaction_id"], "txn-lookup")
        self.assertEqual(decision["decision"], "allow")


if __name__ == "__main__":
    unittest.main()
