import contextlib
import io
import json
from http.server import HTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import unittest


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
from tenta_runtime.cli import _build_parser, main as cli_main  # noqa: E402
from tenta_runtime.console_api import ConsoleRoutes  # noqa: E402
from tenta_runtime.database import DatabaseProvisioner, load_runtime_config  # noqa: E402


class RuntimeCliTests(unittest.TestCase):
    def setUp(self):
        self.static_dir = tempfile.TemporaryDirectory()
        static_path = Path(self.static_dir.name)
        (static_path / "index.html").write_text("<!doctype html><title>Tenta</title>", encoding="utf-8")
        self.engine = RuntimeEngine(
            model=RuleBasedModelWrapper(),
            policy=DecisionPolicy(),
            audit_sink=InMemoryAuditSink(),
        )
        self.control_plane = ControlPlane(store=InMemoryControlPlaneStore())
        self.console = ConsoleRoutes(self.engine, self.control_plane)
        self.config_path = str(static_path / "runtime-config.json")
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

    def test_health_command_prints_runtime_status(self):
        output = self._run_cli("health", "--url", self.base_url)
        payload = json.loads(output)

        self.assertEqual(payload["status"], "healthy")

    def test_top_level_parser_exposes_core_commands(self):
        parser = _build_parser()
        help_text = parser.format_help()

        self.assertIn("serve", help_text)
        self.assertIn("health", help_text)
        self.assertIn("endpoint", help_text)
        self.assertIn("decide", help_text)
        self.assertIn("score", help_text)
        self.assertIn("workload", help_text)
        self.assertIn("replay", help_text)
        self.assertIn("audit", help_text)
        self.assertIn("db", help_text)

    def test_endpoint_command_prints_app_facing_url(self):
        output = self._run_cli("endpoint", "--url", self.base_url)
        payload = json.loads(output)

        self.assertEqual(payload["status"], "serving")
        self.assertEqual(payload["url"], f"{self.base_url}/v1/decision-requests")
        self.assertEqual(payload["contract"], "decision_request.v1")

    def test_score_and_transaction_commands(self):
        score_output = self._run_cli("score", "--url", self.base_url, "--sample")
        score_payload = json.loads(score_output)
        transaction_id = score_payload["transaction_id"]

        lookup_output = self._run_cli("transaction", transaction_id, "--url", self.base_url)
        lookup_payload = json.loads(lookup_output)

        self.assertEqual(lookup_payload["transaction_id"], transaction_id)
        self.assertEqual(lookup_payload["decision"], score_payload["decision"])

    def test_decide_and_decision_commands_use_runtime_contract(self):
        decide_output = self._run_cli("decide", "--url", self.base_url, "--sample")
        decide_payload = json.loads(decide_output)
        decision_request_id = decide_payload["decision_request_id"]

        lookup_output = self._run_cli("decision", decision_request_id, "--url", self.base_url)
        lookup_payload = json.loads(lookup_output)

        self.assertEqual(decision_request_id, lookup_payload["decision_request_id"])
        self.assertEqual(lookup_payload["decision"], decide_payload["decision"])

    def test_feedback_command_records_label(self):
        score_output = self._run_cli("score", "--url", self.base_url, "--sample")
        transaction_id = json.loads(score_output)["transaction_id"]

        output = self._run_cli(
            "feedback",
            transaction_id,
            "--label",
            "legit",
            "--actor",
            "analyst@cli",
            "--url",
            self.base_url,
        )
        payload = json.loads(output)

        self.assertEqual(payload["transaction_id"], transaction_id)
        self.assertEqual(payload["analyst_label"], "legit")
        self.assertEqual(payload["analyst"], "analyst@cli")

    def test_drift_record_command_creates_proposal(self):
        output = self._run_cli(
            "drift",
            "record",
            "--segment",
            "CLI Segment",
            "--feature",
            "merchant_risk",
            "--detector",
            "Population Stability Index",
            "--statistic",
            "0.2",
            "--threshold",
            "0.1",
            "--url",
            self.base_url,
        )
        payload = json.loads(output)

        self.assertEqual(payload["monitor"]["segment"], "CLI Segment")
        self.assertEqual(payload["monitor"]["severity"], "critical")
        self.assertEqual(payload["action"]["status"], "proposed")

    def test_decisions_command_respects_limit(self):
        self._run_cli("score", "--url", self.base_url, "--sample")

        output = self._run_cli("decisions", "--url", self.base_url, "--limit", "1")
        payload = json.loads(output)

        self.assertEqual(payload["limit"], 1)
        self.assertEqual(len(payload["decisions"]), 1)

    def test_workload_commands_manage_registry(self):
        list_output = self._run_cli("workload", "list", "--url", self.base_url)
        list_payload = json.loads(list_output)
        self.assertEqual(list_payload["active_workload_id"], "decision_risk")

        sample_output = self._run_cli("workload", "sample", "decision_risk", "--url", self.base_url)
        sample_payload = json.loads(sample_output)["sample_payload"]

        with tempfile.TemporaryDirectory() as temp_dir:
            payload_path = Path(temp_dir) / "payload.json"
            payload_path.write_text(json.dumps(sample_payload), encoding="utf-8")

            validate_output = self._run_cli(
                "workload",
                "validate",
                "--url",
                self.base_url,
                "--workload-id",
                "decision_risk",
                "--payload",
                str(payload_path),
            )
            validate_payload = json.loads(validate_output)

        self.assertTrue(validate_payload["valid"])

        activate_output = self._run_cli(
            "workload",
            "activate",
            "payment_fraud",
            "--url",
            self.base_url,
            "--reason",
            "cli workload smoke",
        )
        activate_payload = json.loads(activate_output)

        self.assertEqual(activate_payload["active"]["workload_id"], "payment_fraud")
        active_output = self._run_cli("workload", "active", "--url", self.base_url)
        active_payload = json.loads(active_output)
        self.assertEqual(active_payload["workload_id"], "payment_fraud")

    def test_workload_export_import_commands(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            export_path = Path(temp_dir) / "decision-risk-export.json"
            export_output = self._run_cli(
                "workload",
                "export",
                "decision_risk",
                "--url",
                self.base_url,
                "--output",
                str(export_path),
            )
            export_payload = json.loads(export_output)
            spec = json.loads(export_path.read_text(encoding="utf-8"))
            spec["workload_id"] = "decision_risk_cli_variant"
            spec["name"] = "Decision Risk CLI Variant"
            import_path = Path(temp_dir) / "decision-risk-import.json"
            import_path.write_text(json.dumps(spec), encoding="utf-8")

            import_output = self._run_cli(
                "workload",
                "import",
                str(import_path),
                "--activate",
                "--url",
                self.base_url,
            )
            import_payload = json.loads(import_output)

        self.assertEqual(export_payload["status"], "exported")
        self.assertEqual(import_payload["workload"]["workload_id"], "decision_risk_cli_variant")
        self.assertEqual(import_payload["active"]["workload_id"], "decision_risk_cli_variant")

    def test_replay_run_command(self):
        output = self._run_cli("replay", "run", "--url", self.base_url)
        payload = json.loads(output)

        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["failed"], 0)
        self.assertGreaterEqual(payload["count"], 4)

    def test_audit_verify_command_reports_valid_hash_chains(self):
        output = self._run_cli("audit", "verify", "--url", self.base_url)
        payload = json.loads(output)

        self.assertEqual(payload["status"], "valid")
        self.assertEqual(payload["decisions"]["status"], "valid")
        self.assertEqual(payload["operations"]["status"], "valid")

    def test_db_status_and_provision_sqlite_commands(self):
        db_path = str(Path(self.static_dir.name) / "cli.sqlite3")

        status_output = self._run_cli("db", "status", "--url", self.base_url)
        status_payload = json.loads(status_output)
        self.assertEqual(status_payload["connected"]["backend"], "memory")

        provision_output = self._run_cli(
            "db",
            "provision-sqlite",
            "--url",
            self.base_url,
            "--path",
            db_path,
        )
        provision_payload = json.loads(provision_output)

        self.assertEqual(provision_payload["status"], "connected")
        self.assertEqual(provision_payload["storage"]["backend"], "sqlite")
        self.assertEqual(load_runtime_config(self.config_path).storage_url, f"sqlite:{db_path}")

        operations_output = self._run_cli("operations", "--url", self.base_url, "--limit", "1")
        operations_payload = json.loads(operations_output)
        self.assertEqual(operations_payload["operations"][0]["operation_type"], "database.provision")

    def test_db_init_command_initializes_local_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "init.sqlite3")
            config_path = str(Path(temp_dir) / "runtime-config.json")

            output = self._run_cli(
                "db",
                "init",
                "--storage-url",
                f"sqlite:{db_path}",
                "--config-path",
                config_path,
            )
            payload = json.loads(output)

            self.assertEqual(payload["status"], "initialized")
            self.assertTrue(Path(db_path).exists())
            self.assertEqual(payload["control_plane"]["backend"], "sqlite")
            self.assertEqual(load_runtime_config(config_path).storage_url, f"sqlite:{db_path}")

    def test_db_migrate_command_initializes_runtime_and_control_plane_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "migrate.sqlite3")

            output = self._run_cli("db", "migrate", "--storage-url", f"sqlite:{db_path}")
            payload = json.loads(output)

            self.assertEqual(payload["status"], "migrated")
            self.assertEqual(payload["storage"]["backend"], "sqlite")
            self.assertEqual(payload["control_plane"]["backend"], "sqlite")
            self.assertTrue(Path(db_path).exists())

    def _run_cli(self, *args):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            cli_main(list(args))
        return stream.getvalue()


if __name__ == "__main__":
    unittest.main()
