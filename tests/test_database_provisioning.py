import tempfile
import unittest
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))

from tenta_runtime import (  # noqa: E402
    CommandResult,
    ControlPlane,
    DatabaseProvisioner,
    DecisionPolicy,
    InMemoryAuditSink,
    InMemoryControlPlaneStore,
    InMemoryRuntimeStore,
    RuleBasedModelWrapper,
    RuntimeEngine,
)
from tenta_runtime.database import load_runtime_config  # noqa: E402


class DatabaseProvisioningTests(unittest.TestCase):
    def test_provision_sqlite_connects_engine_and_saves_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "runtime.sqlite3")
            config_path = str(Path(temp_dir) / "runtime-config.json")
            engine = RuntimeEngine(
                model=RuleBasedModelWrapper(),
                policy=DecisionPolicy(),
                audit_sink=InMemoryAuditSink(),
                store=InMemoryRuntimeStore(),
            )
            provisioner = DatabaseProvisioner(engine, config_path=config_path)

            result = provisioner.provision_sqlite(path=db_path)

            self.assertEqual(result["status"], "connected")
            self.assertTrue(result["provisioned"])
            self.assertEqual(engine.health()["storage"]["backend"], "sqlite")
            self.assertEqual(engine.health()["storage"]["path"], db_path)
            self.assertTrue(Path(db_path).exists())
            self.assertEqual(load_runtime_config(config_path).storage_url, f"sqlite:{db_path}")

    def test_status_reports_available_backends(self):
        engine = RuntimeEngine(
            model=RuleBasedModelWrapper(),
            policy=DecisionPolicy(),
            audit_sink=InMemoryAuditSink(),
            store=InMemoryRuntimeStore(),
        )
        provisioner = DatabaseProvisioner(engine)

        status = provisioner.status()

        self.assertEqual(status["connected"]["backend"], "memory")
        self.assertEqual([item["backend"] for item in status["available_backends"]], ["sqlite", "postgres"])
        self.assertTrue(status["available_backends"][1]["provisionable"])
        self.assertEqual(status["available_backends"][1]["provisioner"], "docker-compose")

    def test_provision_postgres_runs_compose_before_connect(self):
        class RecordingProvisioner(DatabaseProvisioner):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.connected = {}

            def connect(self, storage_url, persist=True, provisioned=False, provisioning=None, **metadata):
                self.connected = {
                    "storage_url": storage_url,
                    "persist": persist,
                    "provisioned": provisioned,
                    "provisioning": provisioning,
                    "metadata": metadata,
                }
                return {
                    "status": "connected",
                    "storage_url": storage_url,
                    "provisioned": provisioned,
                    "provisioning": provisioning,
                }

        with tempfile.TemporaryDirectory() as temp_dir:
            compose_file = str(Path(temp_dir) / "compose.yaml")
            Path(compose_file).write_text("services: {}\n", encoding="utf-8")
            commands = []

            def runner(command):
                commands.append(command)
                return CommandResult(command=command, returncode=0, stdout="ready")

            engine = RuntimeEngine(
                model=RuleBasedModelWrapper(),
                policy=DecisionPolicy(),
                audit_sink=InMemoryAuditSink(),
                store=InMemoryRuntimeStore(),
            )
            provisioner = RecordingProvisioner(engine, command_runner=runner)

            result = provisioner.provision_postgres(
                storage_url="postgresql://tenta:tenta@127.0.0.1:5432/tenta",
                compose_file=compose_file,
                check_driver=False,
                actor="admin@test",
                request_id="req-postgres-provision",
            )

            self.assertEqual(commands, [["docker", "compose", "-f", compose_file, "up", "-d", "--wait", "postgres"]])
            self.assertEqual(result["status"], "connected")
            self.assertTrue(result["provisioned"])
            self.assertTrue(result["provisioning"]["started"])
            self.assertEqual(result["provisioning"]["command"]["returncode"], 0)
            self.assertTrue(provisioner.connected["provisioned"])
            self.assertEqual(provisioner.connected["metadata"]["request_id"], "req-postgres-provision")

    def test_failed_postgres_provision_records_operation(self):
        engine = RuntimeEngine(
            model=RuleBasedModelWrapper(),
            policy=DecisionPolicy(),
            audit_sink=InMemoryAuditSink(),
            store=InMemoryRuntimeStore(),
        )
        control_plane = ControlPlane(store=InMemoryControlPlaneStore())
        provisioner = DatabaseProvisioner(
            engine,
            control_plane=control_plane,
            command_runner=lambda command: CommandResult(command=command, returncode=0),
        )

        with self.assertRaises(RuntimeError) as error:
            provisioner.provision_postgres(
                compose_file="missing-compose.yaml",
                check_driver=False,
                actor="admin@test",
                role="admin",
                source="unit-test",
                request_id="req-postgres-failed",
                reason="missing compose should be audited",
            )

        self.assertIn("compose file", str(error.exception))
        operation = control_plane.operations(limit=1)["operations"][0]
        self.assertEqual(operation["operation_type"], "database.provision")
        self.assertEqual(operation["status"], "failed")
        self.assertEqual(operation["target"], "postgres")
        self.assertEqual(operation["actor"], "admin@test")
        self.assertEqual(operation["role"], "admin")
        self.assertEqual(operation["source"], "unit-test")
        self.assertEqual(operation["request_id"], "req-postgres-failed")
        self.assertEqual(operation["reason"], "missing compose should be audited")


if __name__ == "__main__":
    unittest.main()
