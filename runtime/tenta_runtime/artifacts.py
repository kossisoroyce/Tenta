"""Timber artifact manifest parsing and validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .workloads import WorkloadSpec


MANIFEST_SCHEMA_VERSION = "tenta.timber-manifest.v1"


class ArtifactValidationError(ValueError):
    """Raised when a Timber artifact manifest cannot be trusted."""


@dataclass(frozen=True)
class TimberArtifactManifest:
    model_id: str
    version: str
    artifact_path: str
    artifact_sha256: str
    signature: str
    signature_status: str
    feature_names: List[str]
    workload_id: Optional[str] = None
    backend: str = "timber"
    schema_version: str = MANIFEST_SCHEMA_VERSION
    metrics: Dict[str, Any] = field(default_factory=dict)
    score_gain: float = 1.0
    score_bias: float = 0.0
    trained_on: str = ""
    runtime: Dict[str, Any] = field(default_factory=dict)
    manifest_path: Optional[str] = None

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        manifest_path: Optional[Path] = None,
    ) -> "TimberArtifactManifest":
        if not isinstance(payload, Mapping):
            raise ArtifactValidationError("manifest must be a JSON object")
        model = _mapping(payload.get("model"))
        artifact = _mapping(payload.get("artifact"))
        feature_contract = _mapping(payload.get("feature_contract") or payload.get("workload"))
        scoring = _mapping(payload.get("scoring"))

        model_id = _string(model.get("model_id") or payload.get("model_id"), "model_id")
        version = _string(model.get("version") or payload.get("version"), "version")
        raw_path = _string(
            artifact.get("path") or artifact.get("artifact_path") or payload.get("artifact_path"),
            "artifact.path",
        )
        resolved_path = _resolve_path(raw_path, manifest_path)
        raw_hash = _string(
            artifact.get("sha256") or artifact.get("artifact_sha256") or artifact.get("artifact_hash") or payload.get("artifact_hash"),
            "artifact.sha256",
        )
        signature = _string(artifact.get("signature") or payload.get("signature"), "artifact.signature")
        signature_status = str(
            artifact.get("signature_status")
            or artifact.get("status")
            or payload.get("signature_status")
            or ("verified" if signature == "ed25519:verified" else "")
        ).strip().lower()
        features = _feature_names(feature_contract.get("features") or payload.get("features"))

        return cls(
            schema_version=str(payload.get("schema_version") or MANIFEST_SCHEMA_VERSION),
            model_id=model_id,
            version=version,
            backend=str(model.get("backend") or payload.get("backend") or "timber"),
            artifact_path=str(resolved_path),
            artifact_sha256=_normalize_sha256(raw_hash),
            signature=signature,
            signature_status=signature_status,
            workload_id=_optional_string(feature_contract.get("workload_id") or payload.get("workload_id")),
            feature_names=features,
            metrics=dict(payload.get("metrics") or model.get("metrics") or {}),
            score_gain=float(scoring.get("score_gain", payload.get("score_gain", 1.0)) or 1.0),
            score_bias=float(scoring.get("score_bias", payload.get("score_bias", 0.0)) or 0.0),
            trained_on=str(model.get("trained_on") or payload.get("trained_on") or ""),
            runtime=dict(payload.get("runtime") or {}),
            manifest_path=str(manifest_path) if manifest_path else _optional_string(payload.get("manifest_path")),
        )

    @classmethod
    def load(cls, path: Path) -> "TimberArtifactManifest":
        return cls.from_mapping(json.loads(path.read_text(encoding="utf-8")), manifest_path=path)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "model": {
                "model_id": self.model_id,
                "version": self.version,
                "backend": self.backend,
                "trained_on": self.trained_on,
            },
            "artifact": {
                "path": self.artifact_path,
                "sha256": self.artifact_sha256,
                "signature": self.signature,
                "signature_status": self.signature_status,
            },
            "feature_contract": {
                "workload_id": self.workload_id,
                "features": list(self.feature_names),
            },
            "metrics": dict(self.metrics),
            "scoring": {"score_gain": self.score_gain, "score_bias": self.score_bias},
            "runtime": dict(self.runtime),
            "manifest_path": self.manifest_path,
        }

    def validation_report(self) -> Dict[str, Any]:
        errors: List[str] = []
        path = Path(self.artifact_path)
        actual_hash = None
        size_mb = 0.0
        if not path.is_file():
            errors.append(f"artifact file not found: {path}")
        else:
            actual_hash = sha256_file(path)
            size_mb = round(path.stat().st_size / 1_000_000, 3)
            if actual_hash != self.artifact_sha256:
                errors.append("artifact sha256 does not match manifest")
        if self.schema_version != MANIFEST_SCHEMA_VERSION:
            errors.append(f"unsupported schema_version: {self.schema_version}")
        if self.backend != "timber":
            errors.append("backend must be timber")
        if self.signature_status not in {"verified", "valid"}:
            errors.append("artifact signature_status must be verified")
        if not self.signature.startswith("ed25519:"):
            errors.append("artifact signature must be an ed25519 signature reference")
        if not self.feature_names:
            errors.append("feature_contract.features must not be empty")
        return {
            "valid": not errors,
            "status": "valid" if not errors else "invalid",
            "errors": errors,
            "artifact_path": str(path),
            "expected_sha256": self.artifact_sha256,
            "actual_sha256": actual_hash,
            "signature_status": self.signature_status,
            "size_mb": size_mb,
        }

    def compatibility_report(self, workload: WorkloadSpec) -> Dict[str, Any]:
        workload_features = {feature.name for feature in workload.features}
        model_features = set(self.feature_names)
        missing = sorted(workload_features - model_features)
        extra = sorted(model_features - workload_features)
        errors = []
        if self.workload_id and self.workload_id != workload.workload_id:
            errors.append(
                f"manifest workload_id {self.workload_id} does not match active workload {workload.workload_id}"
            )
        if missing:
            errors.append(f"model feature contract is missing: {', '.join(missing)}")
        return {
            "valid": not errors,
            "status": "compatible" if not errors else "incompatible",
            "errors": errors,
            "workload_id": workload.workload_id,
            "manifest_workload_id": self.workload_id,
            "required_features": sorted(workload_features),
            "model_features": sorted(model_features),
            "missing_features": missing,
            "extra_features": extra,
        }

    def model_record(
        self,
        *,
        artifact_validation: Dict[str, Any],
        workload_compatibility: Dict[str, Any],
        created_at: str,
        stage: str = "candidate",
    ) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": self.version,
            "backend": self.backend,
            "stage": stage,
            "artifact_hash": self.artifact_sha256,
            "signature": self.signature,
            "signature_status": self.signature_status,
            "score_gain": self.score_gain,
            "score_bias": self.score_bias,
            "traffic_pct": 0,
            "metrics": dict(self.metrics) or None,
            "trained_on": self.trained_on,
            "promoted_at": None,
            "created_at": created_at,
            "notes": "Registered from signed Timber manifest. Promotion requires compatibility and replay gates.",
            "registered_from": "timber_manifest",
            "artifact_path": self.artifact_path,
            "artifact_manifest": self.to_dict(),
            "artifact_validation": dict(artifact_validation),
            "workload_compatibility": dict(workload_compatibility),
            "promotion_gate": {"status": "pending", "valid": False, "checks": {}},
        }


def load_timber_manifest(path: Path) -> TimberArtifactManifest:
    return TimberArtifactManifest.load(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArtifactValidationError(f"{field_name} is required")
    return value.strip()


def _optional_string(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _feature_names(value: Any) -> List[str]:
    if not isinstance(value, list):
        raise ArtifactValidationError("feature_contract.features must be a list")
    names: List[str] = []
    for item in value:
        raw = item.get("name") if isinstance(item, Mapping) else item
        if isinstance(raw, str) and raw.strip():
            names.append(raw.strip())
    if not names:
        raise ArtifactValidationError("feature_contract.features must include at least one feature")
    return names


def _normalize_sha256(value: str) -> str:
    normalized = value.removeprefix("sha256:").strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ArtifactValidationError("artifact.sha256 must be a 64-character SHA-256 hex digest")
    return normalized


def _resolve_path(raw_path: str, manifest_path: Optional[Path]) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    if manifest_path is not None:
        return (manifest_path.parent / path).resolve()
    return path.resolve()
