import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
import sys
import sqlite3


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))

from tenta_runtime import (  # noqa: E402
    DecisionPolicy,
    IdempotencyConflictError,
    InMemoryAuditSink,
    RuleBasedModelWrapper,
    RuntimeEngine,
    SQLiteRuntimeStore,
    verify_decision_events,
)
from tenta_runtime.storage import RUNTIME_SCHEMA_VERSION  # noqa: E402

from test_runtime_engine import base_payload  # noqa: E402


class SQLiteRuntimeStoreTests(unittest.TestCase):
    def test_persists_decisions_and_idempotency_across_engine_instances(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "tenta.sqlite3")
            first_store = SQLiteRuntimeStore(db_path)
            first_engine = RuntimeEngine(
                model=RuleBasedModelWrapper(),
                policy=DecisionPolicy(),
                audit_sink=InMemoryAuditSink(),
                store=first_store,
            )

            first_response = first_engine.score(base_payload(transaction_id="txn-persisted"))
            first_store.close()

            second_store = SQLiteRuntimeStore(db_path)
            second_engine = RuntimeEngine(
                model=RuleBasedModelWrapper(),
                policy=DecisionPolicy(),
                audit_sink=InMemoryAuditSink(),
                store=second_store,
            )

            replayed_response = second_engine.score(base_payload(transaction_id="txn-persisted"))
            decisions = second_engine.decisions(limit=5)["decisions"]
            lookup = second_engine.transaction("txn-persisted")

            self.assertEqual(replayed_response, first_response)
            self.assertEqual(len(decisions), 1)
            self.assertEqual(decisions[0]["transaction_id"], "txn-persisted")
            self.assertEqual(lookup["transaction_id"], "txn-persisted")
            self.assertEqual(second_engine.health()["storage"]["backend"], "sqlite")
            second_store.close()

    def test_decision_events_are_hash_chained(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "tenta.sqlite3")
            store = SQLiteRuntimeStore(db_path)
            engine = RuntimeEngine(
                model=RuleBasedModelWrapper(),
                policy=DecisionPolicy(),
                audit_sink=InMemoryAuditSink(),
                store=store,
            )

            engine.score(base_payload(transaction_id="txn-chain-1", amount=100))
            engine.score(base_payload(transaction_id="txn-chain-2", amount=200))
            decisions = engine.decisions(limit=2)["decisions"]

            newest, oldest = decisions
            self.assertIsNotNone(oldest["event_hash"])
            self.assertIsNone(oldest["previous_hash"])
            self.assertEqual(newest["previous_hash"], oldest["event_hash"])
            self.assertIsNotNone(newest["event_hash"])
            self.assertNotEqual(newest["event_hash"], oldest["event_hash"])
            integrity = verify_decision_events(store.list_decisions(limit=2), total_events=2)
            self.assertEqual(integrity["status"], "valid")
            self.assertEqual(integrity["events_checked"], 2)
            store.close()

    def test_integrity_verifier_detects_tampered_decision_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "tenta.sqlite3")
            store = SQLiteRuntimeStore(db_path)
            engine = RuntimeEngine(
                model=RuleBasedModelWrapper(),
                policy=DecisionPolicy(),
                audit_sink=InMemoryAuditSink(),
                store=store,
            )

            engine.score(base_payload(transaction_id="txn-tamper", amount=100))
            event = store.list_decisions(limit=1)[0]
            tampered = replace(event, score=0.99)

            integrity = verify_decision_events([tampered], total_events=1)

            self.assertEqual(integrity["status"], "invalid")
            self.assertEqual(integrity["issues"][0]["type"], "event_hash_mismatch")
            store.close()

    def test_sqlite_store_migrates_legacy_decision_table(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "legacy.sqlite3")
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE idempotency_keys (
                      transaction_id TEXT PRIMARY KEY,
                      fingerprint TEXT NOT NULL,
                      response_json TEXT NOT NULL,
                      created_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE decision_events (
                      id TEXT PRIMARY KEY,
                      transaction_id TEXT NOT NULL,
                      event_time TEXT NOT NULL,
                      model_id TEXT NOT NULL,
                      model_version TEXT NOT NULL,
                      policy_version TEXT NOT NULL,
                      score REAL NOT NULL,
                      decision TEXT NOT NULL,
                      reason_codes_json TEXT NOT NULL,
                      latency_ms REAL NOT NULL,
                      degraded_mode INTEGER NOT NULL,
                      event_json TEXT NOT NULL,
                      created_at TEXT NOT NULL
                    )
                    """
                )
                connection.commit()
            finally:
                connection.close()

            store = SQLiteRuntimeStore(db_path)
            column_connection = sqlite3.connect(db_path)
            try:
                columns = {row[1] for row in column_connection.execute("PRAGMA table_info(decision_events)").fetchall()}
            finally:
                column_connection.close()

            self.assertIn("previous_hash", columns)
            self.assertIn("event_hash", columns)
            self.assertEqual(store.health()["schema_version"], RUNTIME_SCHEMA_VERSION)
            store.close()

    def test_conflicting_replay_uses_persistent_idempotency_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = str(Path(temp_dir) / "tenta.sqlite3")
            store = SQLiteRuntimeStore(db_path)
            engine = RuntimeEngine(
                model=RuleBasedModelWrapper(),
                policy=DecisionPolicy(),
                audit_sink=InMemoryAuditSink(),
                store=store,
            )

            engine.score(base_payload(transaction_id="txn-conflict", amount=100))

            with self.assertRaises(IdempotencyConflictError):
                engine.score(base_payload(transaction_id="txn-conflict", amount=200))

            store.close()


if __name__ == "__main__":
    unittest.main()
