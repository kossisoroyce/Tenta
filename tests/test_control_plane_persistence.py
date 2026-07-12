import tempfile
import unittest
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))

from tenta_runtime import (  # noqa: E402
    ControlPlane,
    DatabaseProvisioner,
    DecisionPolicy,
    InMemoryAuditSink,
    InMemoryControlPlaneStore,
    InMemoryRuntimeStore,
    RuleBasedModelWrapper,
    RuntimeEngine,
    SQLiteControlPlaneStore,
)
from tenta_runtime.control_plane_store import CONTROL_PLANE_SCHEMA_VERSION  # noqa: E402


class ControlPlanePersistenceTests(unittest.TestCase):
    def test_sqlite_snapshot_survives_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "control.sqlite3")
            first_store = SQLiteControlPlaneStore(db_path)
            first = ControlPlane(store=first_store)

            first.promote_model("fraud-xgb-v13-rc2", "champion", actor="model-risk@test")
            first.decide_action("heal_eu_review", "approve", actor="risk@test")
            first.update_drift("drift_velocity_mobile", "acknowledge", actor="risk@test")
            first_store.close()

            second_store = SQLiteControlPlaneStore(db_path)
            second = ControlPlane(store=second_store)

            self.assertEqual(second.summary()["champion"], "fraud-xgb-v13-rc2")
            action = next(a for a in second.healing_actions()["actions"] if a["id"] == "heal_eu_review")
            monitor = next(m for m in second.drift()["monitors"] if m["id"] == "drift_velocity_mobile")
            history = second.policy_history()["entries"]
            operations = second.operations(limit=3)["operations"]

            self.assertEqual(action["status"], "running")
            self.assertEqual(monitor["status"], "acknowledged")
            self.assertEqual(history[0]["kind"], "increase_manual_review")
            self.assertEqual(operations[0]["operation_type"], "drift.acknowledge")
            self.assertEqual(operations[1]["operation_type"], "healing.approve")
            self.assertEqual(operations[0]["previous_hash"], operations[1]["event_hash"])
            self.assertTrue(second.persistence_health()["has_snapshot"])
            self.assertEqual(second.persistence_health()["schema_version"], CONTROL_PLANE_SCHEMA_VERSION)
            second_store.close()

    def test_database_provisioner_moves_control_plane_to_new_store(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "runtime.sqlite3")
            control_plane = ControlPlane(store=InMemoryControlPlaneStore())
            control_plane.promote_model("fraud-xgb-v13-rc2", "champion", actor="model-risk@test")
            engine = RuntimeEngine(
                model=RuleBasedModelWrapper(),
                policy=DecisionPolicy(),
                audit_sink=InMemoryAuditSink(),
                store=InMemoryRuntimeStore(),
            )
            provisioner = DatabaseProvisioner(
                engine,
                config_path=str(Path(temp_dir) / "runtime-config.json"),
                control_plane=control_plane,
            )

            result = provisioner.provision_sqlite(db_path)

            restarted = ControlPlane(store=SQLiteControlPlaneStore(db_path))
            self.assertEqual(result["control_plane"]["backend"], "sqlite")
            self.assertEqual(restarted.summary()["champion"], "fraud-xgb-v13-rc2")

    def test_feedback_survives_restart_and_records_operation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "feedback.sqlite3")
            first_store = SQLiteControlPlaneStore(db_path)
            first = ControlPlane(store=first_store)

            first.add_feedback(
                {
                    "transaction_id": "txn-feedback-001",
                    "analyst_label": "fraud",
                    "model_decision": "allow",
                    "delay_hours": 2.5,
                    "segment": "Mobile",
                },
                actor="analyst@test",
            )
            first_store.close()

            second_store = SQLiteControlPlaneStore(db_path)
            second = ControlPlane(store=second_store)
            feedback = second.feedback()
            operations = second.operations(limit=1)["operations"]

            self.assertEqual(feedback["recent"][0]["transaction_id"], "txn-feedback-001")
            self.assertFalse(feedback["recent"][0]["agreement"])
            self.assertEqual(operations[0]["operation_type"], "feedback.record")
            self.assertEqual(operations[0]["target"], "txn-feedback-001")
            second_store.close()

    def test_drift_ingestion_survives_restart_and_proposes_action(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "drift.sqlite3")
            first_store = SQLiteControlPlaneStore(db_path)
            first = ControlPlane(store=first_store)

            response = first.record_drift_event(
                {
                    "segment": "Issuer · Test Bank",
                    "feature": "merchant_risk",
                    "detector": "Population Stability Index",
                    "statistic": 0.24,
                    "threshold": 0.1,
                    "confidence": 0.93,
                    "population": 12000,
                },
                actor="detector@test",
            )
            first_store.close()

            second_store = SQLiteControlPlaneStore(db_path)
            second = ControlPlane(store=second_store)
            monitors = second.drift()["monitors"]
            actions = second.healing_actions()["actions"]
            operations = second.operations(limit=2)["operations"]
            monitor = next(m for m in monitors if m["id"] == response["monitor"]["id"])
            action = next(a for a in actions if a["id"] == response["action"]["id"])

            self.assertEqual(monitor["severity"], "critical")
            self.assertEqual(action["linked_drift"], monitor["id"])
            self.assertEqual(action["status"], "proposed")
            self.assertEqual(operations[0]["operation_type"], "healing.propose")
            self.assertEqual(operations[1]["operation_type"], "drift.ingest")
            self.assertEqual(operations[0]["previous_hash"], operations[1]["event_hash"])
            second_store.close()

    def test_repeated_drift_signal_does_not_duplicate_open_action(self):
        control_plane = ControlPlane(store=InMemoryControlPlaneStore())
        spec = {
            "segment": "Issuer · Repeat Bank",
            "feature": "velocity_10m",
            "detector": "Population Stability Index",
            "statistic": 0.2,
            "threshold": 0.1,
        }

        first = control_plane.record_drift_event(spec, actor="detector@test")
        second = control_plane.record_drift_event(spec, actor="detector@test")

        linked = [
            action for action in control_plane.healing_actions()["actions"]
            if action["linked_drift"] == first["monitor"]["id"]
            and action["status"] in {"proposed", "running"}
        ]
        self.assertIsNotNone(first["action"])
        self.assertIsNone(second["action"])
        self.assertEqual(len(linked), 1)


if __name__ == "__main__":
    unittest.main()
