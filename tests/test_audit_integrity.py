import hashlib
import json
import unittest
from dataclasses import replace
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))

from tenta_runtime import OperationEvent, verify_operation_events  # noqa: E402


class AuditIntegrityTests(unittest.TestCase):
    def test_legacy_operation_hash_format_is_partial_not_invalid(self):
        event = OperationEvent(
            operation_type="database.provision",
            actor="admin@test",
            target="sqlite",
            request={"storage_url": "sqlite:data/tenta.sqlite3"},
        ).with_integrity(None)
        legacy_payload = event.to_dict()
        legacy_payload.pop("event_hash", None)
        for key in ("role", "source", "request_id", "reason"):
            legacy_payload.pop(key, None)
        legacy_hash = hashlib.sha256(
            json.dumps(legacy_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()

        report = verify_operation_events([replace(event, event_hash=legacy_hash)], total_events=1)

        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["events_verified"], 1)
        self.assertEqual(report["issues"], [])
        self.assertEqual(report["warnings"][0]["type"], "legacy_hash_format")


if __name__ == "__main__":
    unittest.main()
