import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from tenta_runtime import RuleBasedModelWrapper, RuntimeEngine, load_workload_spec  # noqa: E402


class ExampleFilesTest(unittest.TestCase):
    def test_decision_request_scores(self):
        payload = json.loads((ROOT / "examples" / "decision_request.json").read_text(encoding="utf-8"))
        engine = RuntimeEngine(model=RuleBasedModelWrapper())

        result = engine.score(payload)

        self.assertEqual(result["decision_request_id"], payload["decision_request_id"])
        self.assertEqual(result["workload_id"], "decision_risk")
        self.assertIn(result["decision"], {"allow", "review", "block"})

    def test_claims_triage_workload_loads(self):
        workload = load_workload_spec(ROOT / "examples" / "claims_triage_workload.json")

        self.assertEqual(workload.workload_id, "claims_triage")
        self.assertEqual(workload.domain, "insurance")
        self.assertEqual(workload.policy.review_threshold, 0.55)

    def test_postgres_provision_payload_is_documented_shape(self):
        payload = json.loads((ROOT / "examples" / "postgres_provision.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["backend"], "postgres")
        self.assertTrue(payload["storage_url"].startswith("postgresql://"))
        self.assertEqual(payload["role"], "admin")


if __name__ == "__main__":
    unittest.main()
