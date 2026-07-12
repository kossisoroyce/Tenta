import json
import tempfile
import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from tenta_runtime import (  # noqa: E402
    ArtifactValidationError,
    TimberArtifactManifest,
    TimberModelWrapper,
    default_workload_registry,
    sha256_file,
)
from tenta_runtime.models import ScoringRequest  # noqa: E402


class TimberArtifactManifestTests(unittest.TestCase):
    def test_manifest_validates_hash_signature_and_workload_contract(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path, manifest_payload = write_manifest(Path(temp_dir))

            manifest = TimberArtifactManifest.load(manifest_path)
            validation = manifest.validation_report()
            compatibility = manifest.compatibility_report(default_workload_registry().active())

            self.assertTrue(validation["valid"])
            self.assertEqual(validation["actual_sha256"], manifest_payload["artifact"]["sha256"])
            self.assertTrue(compatibility["valid"])

    def test_manifest_rejects_bad_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path, manifest_payload = write_manifest(Path(temp_dir))
            manifest_payload["artifact"]["sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")

            manifest = TimberArtifactManifest.load(manifest_path)
            validation = manifest.validation_report()

            self.assertFalse(validation["valid"])
            self.assertIn("artifact sha256 does not match manifest", validation["errors"])

    def test_manifest_requires_features(self):
        with self.assertRaises(ArtifactValidationError):
            TimberArtifactManifest.from_mapping(
                {
                    "model": {"model_id": "bad-model", "version": "1.0.0"},
                    "artifact": {"path": "artifact.timber", "sha256": "0" * 64, "signature": "ed25519:verified"},
                    "feature_contract": {"features": []},
                }
            )

    def test_timber_model_wrapper_scores_with_manifest_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path, _ = write_manifest(Path(temp_dir), score_gain=1.1)
            wrapper = TimberModelWrapper(TimberArtifactManifest.load(manifest_path))
            request = ScoringRequest.from_mapping(default_workload_registry().active().sample_payload)

            prediction = wrapper.predict(request)

            self.assertEqual(prediction.model_id, "decision-risk-xgb-v14")
            self.assertEqual(prediction.model_version, "14.0.0")
            self.assertGreater(prediction.score, 0)
            self.assertEqual(wrapper.health()["status"], "healthy")


def write_manifest(directory: Path, *, score_gain: float = 1.0, features=None):
    artifact_path = directory / "decision-risk-v14.timber"
    artifact_path.write_text("timber artifact fixture\n", encoding="utf-8")
    feature_names = features or [
        "merchant_risk",
        "velocity_10m",
        "account_age_days",
        "chargeback_count",
        "is_high_risk_country",
    ]
    payload = {
        "schema_version": "tenta.timber-manifest.v1",
        "model": {
            "model_id": "decision-risk-xgb-v14",
            "version": "14.0.0",
            "backend": "timber",
            "trained_on": "2026-07-12",
        },
        "artifact": {
            "path": "decision-risk-v14.timber",
            "sha256": sha256_file(artifact_path),
            "signature": "ed25519:verified",
            "signature_status": "verified",
        },
        "feature_contract": {
            "workload_id": "decision_risk",
            "features": feature_names,
        },
        "metrics": {
            "auc": 0.978,
            "pr_auc": 0.862,
            "fpr": 0.008,
            "recall": 0.904,
            "precision": 0.924,
            "p99_latency_ms": 5.8,
        },
        "scoring": {"score_gain": score_gain, "score_bias": 0.0},
        "runtime": {"predictor": "rule_based"},
    }
    manifest_path = directory / "decision-risk-v14.tenta.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    return manifest_path, payload


if __name__ == "__main__":
    unittest.main()
