import json
from http.server import HTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))

from tenta_runtime import (  # noqa: E402
    ControlPlane,
    DecisionPolicy,
    InMemoryAuditSink,
    InMemoryControlPlaneStore,
    RuleBasedModelWrapper,
    RuntimeEngine,
)
from tenta_runtime.api import make_handler  # noqa: E402
from tenta_runtime.console_api import ConsoleRoutes  # noqa: E402
from tenta_runtime.database import DatabaseProvisioner, load_runtime_config  # noqa: E402


class RuntimeApiTests(unittest.TestCase):
    def setUp(self):
        self.static_dir = tempfile.TemporaryDirectory()
        static_path = Path(self.static_dir.name)
        (static_path / "index.html").write_text(
            '<!doctype html><title>Tenta Runtime Dashboard</title><script src="/dashboard/app.js"></script>',
            encoding="utf-8",
        )
        self.audit = InMemoryAuditSink()
        self.engine = RuntimeEngine(
            model=RuleBasedModelWrapper(),
            policy=DecisionPolicy(),
            audit_sink=self.audit,
        )
        self.config_path = str(static_path / "runtime-config.json")
        self.workload_dir = static_path / "workloads"
        self.control_plane = ControlPlane(store=InMemoryControlPlaneStore())
        self.console = ConsoleRoutes(
            self.engine,
            self.control_plane,
            config_path=self.config_path,
            workload_dir=self.workload_dir,
        )
        self.database = DatabaseProvisioner(
            self.engine,
            config_path=self.config_path,
            control_plane=self.control_plane,
        )
        self.server = HTTPServer(
            ("127.0.0.1", 0),
            make_handler(self.engine, static_dir=static_path, console=self.console, database=self.database),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        self.static_dir.cleanup()

    def test_health_endpoint(self):
        body = self._get_json("/v1/health")

        self.assertEqual(body["status"], "healthy")
        self.assertEqual(body["model"]["model_id"], "fraud-rule-baseline")

    def test_score_endpoint(self):
        body = self._post_json(
            "/v1/score",
            {
                "transaction_id": "txn-api-001",
                "account_id": "acct-api-001",
                "amount": 500,
                "currency": "USD",
                "merchant_id": "merchant-api-001",
                "channel": "web",
                "event_time": "2026-07-11T12:00:00Z",
                "features": {"merchant_risk": 0.2, "velocity_10m": 2},
            },
        )

        self.assertEqual(body["transaction_id"], "txn-api-001")
        self.assertEqual(body["decision_request_id"], "txn-api-001")
        self.assertIn(body["decision"], {"allow", "review", "block"})
        self.assertEqual(len(self.audit.list_events()), 1)

    def test_decision_requests_endpoint_accepts_runtime_contract(self):
        body = self._post_json(
            "/v1/decision-requests",
            {
                "decision_request_id": "req-api-001",
                "subject_id": "subject-api-001",
                "context_id": "reference-workload",
                "value": 500,
                "currency": "USD",
                "channel": "web",
                "requested_at": "2026-07-11T12:00:00Z",
                "features": {
                    "entity_risk": 0.2,
                    "velocity_10m": 2,
                    "subject_age_days": 120,
                    "prior_adverse_events": 0,
                    "high_risk_segment": False,
                },
            },
        )

        self.assertEqual(body["decision_request_id"], "req-api-001")
        self.assertEqual(body["transaction_id"], "req-api-001")
        lookup = self._get_json("/v1/decision-requests/req-api-001")
        self.assertEqual(lookup["decision_request_id"], "req-api-001")
        events = self._get_json("/v1/decision-events?limit=1")
        self.assertEqual(events["decisions"][0]["decision_request_id"], "req-api-001")

    def test_score_endpoint_validation_error(self):
        with self.assertRaises(HTTPError) as error:
            self._post_json("/v1/score", {"transaction_id": "txn-invalid"})

        self.assertEqual(error.exception.code, 422)
        payload = json.loads(error.exception.read().decode("utf-8"))
        self.assertEqual(payload["error"], "validation_error")

    def test_decisions_endpoint(self):
        self._post_json(
            "/v1/score",
            {
                "transaction_id": "txn-api-feed",
                "account_id": "acct-api-001",
                "amount": 500,
                "currency": "USD",
                "merchant_id": "merchant-api-001",
                "channel": "web",
                "event_time": "2026-07-11T12:00:00Z",
                "features": {"merchant_risk": 0.2, "velocity_10m": 2},
            },
        )

        body = self._get_json("/v1/decisions?limit=5")

        self.assertEqual(body["limit"], 5)
        self.assertEqual(body["decisions"][0]["transaction_id"], "txn-api-feed")

    def test_transaction_lookup_endpoint(self):
        self._post_json(
            "/v1/score",
            {
                "transaction_id": "txn-api-lookup",
                "account_id": "acct-api-001",
                "amount": 500,
                "currency": "USD",
                "merchant_id": "merchant-api-001",
                "channel": "web",
                "event_time": "2026-07-11T12:00:00Z",
                "features": {"merchant_risk": 0.2, "velocity_10m": 2},
            },
        )

        body = self._get_json("/v1/transactions/txn-api-lookup")

        self.assertEqual(body["transaction_id"], "txn-api-lookup")
        self.assertIn(body["decision"], {"allow", "review", "block"})

    def test_transaction_lookup_endpoint_not_found(self):
        with self.assertRaises(HTTPError) as error:
            self._get_json("/v1/transactions/missing")

        self.assertEqual(error.exception.code, 404)

    def test_database_status_endpoint(self):
        body = self._get_json("/v1/database/status")

        self.assertEqual(body["connected"]["backend"], "memory")
        self.assertEqual(body["available_backends"][0]["backend"], "sqlite")
        self.assertEqual(body["available_backends"][1]["backend"], "postgres")
        self.assertTrue(body["available_backends"][1]["provisionable"])

    def test_database_provision_sqlite_endpoint_connects_runtime(self):
        db_path = str(Path(self.static_dir.name) / "runtime.sqlite3")

        body = self._post_json(
            "/v1/database/provision",
            {
                "backend": "sqlite",
                "path": db_path,
                "request_id": "req-db-provision-test",
                "reason": "unit test provision",
            },
        )

        self.assertEqual(body["status"], "connected")
        self.assertEqual(body["storage"]["backend"], "sqlite")
        self.assertEqual(body["operation"]["operation_type"], "database.provision")
        self.assertEqual(body["operation"]["role"], "admin")
        self.assertEqual(body["operation"]["request_id"], "req-db-provision-test")
        self.assertEqual(body["operation"]["reason"], "unit test provision")
        self.assertEqual(body["control_plane"]["operation_events"], 1)
        self.assertEqual(self.engine.health()["storage"]["path"], db_path)

    def test_database_provision_denies_unprivileged_role_and_records_operation(self):
        db_path = str(Path(self.static_dir.name) / "denied.sqlite3")

        with self.assertRaises(HTTPError) as error:
            self._post_json(
                "/v1/database/provision",
                {
                    "backend": "sqlite",
                    "path": db_path,
                    "actor": "analyst@test",
                    "role": "analyst",
                    "request_id": "req-denied-db",
                },
            )

        self.assertEqual(error.exception.code, 403)
        payload = json.loads(error.exception.read().decode("utf-8"))
        self.assertEqual(payload["operation"], "database.provision")
        operations = self._get_json("/v1/operations?limit=1")
        self.assertEqual(operations["operations"][0]["operation_type"], "governance.denied")
        self.assertEqual(operations["operations"][0]["status"], "denied")
        self.assertEqual(operations["operations"][0]["role"], "analyst")
        self.assertEqual(operations["operations"][0]["request_id"], "req-denied-db")

    def test_operations_endpoint_reports_provisioning_events(self):
        db_path = str(Path(self.static_dir.name) / "runtime-ops.sqlite3")
        self._post_json(
            "/v1/database/provision",
            {"backend": "sqlite", "path": db_path},
        )

        body = self._get_json("/v1/operations?limit=1")

        self.assertEqual(body["limit"], 1)
        self.assertEqual(body["operations"][0]["operation_type"], "database.provision")
        self.assertEqual(body["operations"][0]["status"], "succeeded")
        self.assertIsNotNone(body["operations"][0]["event_hash"])

    def test_workload_endpoints_validate_activate_and_audit(self):
        registry = self._get_json("/v1/workloads")

        self.assertEqual(registry["active_workload_id"], "decision_risk")
        self.assertTrue(any(w["workload_id"] == "payment_fraud" for w in registry["workloads"]))

        sample = self._get_json("/v1/workloads/decision_risk/sample")["sample_payload"]
        validation = self._post_json("/v1/workloads/validate", {"workload_id": "decision_risk", "payload": sample})

        self.assertTrue(validation["valid"])
        self.assertEqual(validation["normalized"]["workload_id"], "decision_risk")

        activated = self._post_json(
            "/v1/workloads/activate",
            {
                "workload_id": "payment_fraud",
                "actor": "casey@example.com",
                "role": "model-risk",
                "request_id": "req-workload-activate",
                "reason": "switch workload pack",
            },
        )

        self.assertEqual(activated["active"]["workload_id"], "payment_fraud")
        self.assertEqual(self.engine.policy.version, "fraud-policy-0.1.0")
        operations = self._get_json("/v1/operations?limit=1")
        self.assertEqual(operations["operations"][0]["operation_type"], "workload.activate")
        self.assertEqual(operations["operations"][0]["request_id"], "req-workload-activate")
        health = self._get_json("/v1/health")
        self.assertEqual(health["workload"]["workload_id"], "payment_fraud")
        self.assertEqual(load_runtime_config(self.config_path).active_workload_id, "payment_fraud")

    def test_workload_import_export_persists_spec(self):
        export = self._get_json("/v1/workloads/decision_risk/export")
        spec = export["spec"]
        spec["workload_id"] = "decision_risk_api_variant"
        spec["name"] = "Decision Risk API Variant"
        spec["policy"] = {**spec["policy"], "version": "api-variant-policy-0.1.0"}

        imported = self._post_json(
            "/v1/workloads/import",
            {
                "spec": spec,
                "activate": True,
                "persist": True,
                "actor": "casey@example.com",
                "role": "model-risk",
                "request_id": "req-workload-import",
            },
        )

        self.assertEqual(imported["workload"]["workload_id"], "decision_risk_api_variant")
        self.assertEqual(imported["active"]["workload_id"], "decision_risk_api_variant")
        self.assertTrue((self.workload_dir / "decision_risk_api_variant.json").exists())
        self.assertEqual(load_runtime_config(self.config_path).active_workload_id, "decision_risk_api_variant")
        operations = self._get_json("/v1/operations?limit=1")
        self.assertEqual(operations["operations"][0]["operation_type"], "workload.import")
        self.assertEqual(operations["operations"][0]["request_id"], "req-workload-import")

    def test_audit_integrity_endpoint_verifies_decisions_and_operations(self):
        self._post_json(
            "/v1/score",
            {
                "transaction_id": "txn-api-integrity",
                "account_id": "acct-api-001",
                "amount": 120,
                "currency": "USD",
                "merchant_id": "merchant-api-001",
                "channel": "web",
                "event_time": "2026-07-11T12:00:00Z",
                "features": {"merchant_risk": 0.2, "velocity_10m": 2},
            },
        )
        self._post_json(
            "/v1/feedback",
            {
                "transaction_id": "txn-api-integrity",
                "analyst_label": "legit",
                "actor": "analyst@test",
            },
        )

        body = self._get_json("/v1/audit/integrity")

        self.assertEqual(body["status"], "valid")
        self.assertEqual(body["decisions"]["status"], "valid")
        self.assertEqual(body["decisions"]["events_checked"], 1)
        self.assertEqual(body["operations"]["status"], "valid")
        self.assertEqual(body["operations"]["events_checked"], 1)

    def test_feedback_endpoint_records_label_and_uses_transaction_decision(self):
        score = self._post_json(
            "/v1/score",
            {
                "transaction_id": "txn-api-feedback",
                "account_id": "acct-api-001",
                "amount": 120,
                "currency": "USD",
                "merchant_id": "merchant-api-001",
                "channel": "web",
                "event_time": "2026-07-11T12:00:00Z",
                "features": {"merchant_risk": 0.2, "velocity_10m": 2},
            },
        )

        body = self._post_json(
            "/v1/feedback",
            {
                "decision_request_id": "txn-api-feedback",
                "outcome_label": "expected",
                "actor": "analyst@test",
                "delay_hours": 1.5,
            },
        )

        self.assertEqual(body["transaction_id"], "txn-api-feedback")
        self.assertEqual(body["decision_request_id"], "txn-api-feedback")
        self.assertEqual(body["model_decision"], score["decision"])
        self.assertEqual(body["analyst_label"], "legit")
        self.assertEqual(body["outcome_label"], "expected")
        operations = self._get_json("/v1/operations?limit=1")
        self.assertEqual(operations["operations"][0]["operation_type"], "feedback.record")

    def test_drift_events_endpoint_creates_monitor_and_healing_proposal(self):
        body = self._post_json(
            "/v1/drift/events",
            {
                "segment": "Issuer · API Bank",
                "feature": "velocity_10m",
                "detector": "Population Stability Index",
                "statistic": 0.18,
                "threshold": 0.1,
                "confidence": 0.91,
                "population": 24000,
                "actor": "detector@test",
            },
        )

        self.assertEqual(body["monitor"]["severity"], "critical")
        self.assertEqual(body["action"]["status"], "proposed")
        self.assertEqual(body["action"]["linked_drift"], body["monitor"]["id"])
        drift = self._get_json("/v1/drift")
        self.assertTrue(any(m["id"] == body["monitor"]["id"] for m in drift["monitors"]))
        operations = self._get_json("/v1/operations?limit=1")
        self.assertEqual(operations["operations"][0]["operation_type"], "healing.propose")

    def test_healing_approval_denies_unprivileged_role_and_records_operation(self):
        with self.assertRaises(HTTPError) as error:
            self._post_json(
                "/v1/healing/actions/heal_eu_review/approve",
                {
                    "actor": "analyst@test",
                    "role": "analyst",
                    "request_id": "req-denied-healing",
                },
            )

        self.assertEqual(error.exception.code, 403)
        payload = json.loads(error.exception.read().decode("utf-8"))
        self.assertEqual(payload["operation"], "healing.approve")
        operations = self._get_json("/v1/operations?limit=1")
        self.assertEqual(operations["operations"][0]["operation_type"], "governance.denied")
        self.assertEqual(operations["operations"][0]["target"], "heal_eu_review")
        self.assertEqual(operations["operations"][0]["role"], "analyst")
        self.assertEqual(operations["operations"][0]["request_id"], "req-denied-healing")
        action = next(a for a in self._get_json("/v1/healing/actions")["actions"] if a["id"] == "heal_eu_review")
        self.assertEqual(action["status"], "proposed")

    def test_healing_approval_records_explicit_actor_context(self):
        body = self._post_json(
            "/v1/healing/actions/heal_eu_review/approve",
            {
                "actor": "casey@example.com",
                "role": "model-risk",
                "source": "approval-console",
                "request_id": "req-approve-context",
                "reason": "validated replay",
            },
        )

        self.assertEqual(body["status"], "running")
        self.assertEqual(body["outcome"]["status"], "applied")
        self.assertEqual(body["execution"]["kind"], "manual_review_override")
        overview = self._get_json("/v1/overview")
        self.assertIn("heal_eu_review", overview["runtime_controls"]["manual_review_overrides"])
        operations = self._get_json("/v1/operations?limit=1")
        self.assertEqual(operations["operations"][0]["operation_type"], "healing.execute")
        self.assertEqual(operations["operations"][0]["actor"], "casey@example.com")
        self.assertEqual(operations["operations"][0]["role"], "model-risk")
        self.assertEqual(operations["operations"][0]["source"], "approval-console")
        self.assertEqual(operations["operations"][0]["request_id"], "req-approve-context")
        self.assertEqual(operations["operations"][0]["reason"], "validated replay")

    def test_threshold_healing_execution_and_rollback_changes_policy(self):
        approved = self._post_json(
            "/v1/healing/actions/heal_mobile_threshold/approve",
            {
                "actor": "casey@example.com",
                "role": "model-risk",
                "request_id": "req-threshold-execute",
            },
        )

        self.assertEqual(approved["status"], "running")
        self.assertEqual(approved["execution"]["kind"], "policy_threshold")
        self.assertEqual(self.engine.policy.review_threshold, 0.62)
        self.assertIn("heal_mobile_threshold", self.engine.policy.version)

        rolled_back = self._post_json(
            "/v1/healing/actions/heal_mobile_threshold/rollback",
            {
                "actor": "casey@example.com",
                "role": "model-risk",
                "request_id": "req-threshold-rollback",
            },
        )

        self.assertEqual(rolled_back["status"], "rolled_back")
        self.assertEqual(rolled_back["outcome"]["rollback_effect"]["kind"], "policy_threshold")
        self.assertEqual(self.engine.policy.review_threshold, 0.65)

    def test_dashboard_shell_is_served(self):
        with urlopen(self.base_url + "/", timeout=2) as response:
            body = response.read().decode("utf-8")

        self.assertEqual(response.status, 200)
        self.assertIn("Tenta Runtime Dashboard", body)
        self.assertIn("/dashboard/app.js", body)

    def _get_json(self, path):
        with urlopen(self.base_url + path, timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post_json(self, path, payload):
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
