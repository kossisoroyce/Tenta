"""Workload registry for domain-specific decision runtime configuration."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


DEFAULT_WORKLOAD_ID = "decision_risk"
DEFAULT_WORKLOAD_DIR = Path(__file__).resolve().parent / "workload_packs"
DEFAULT_USER_WORKLOAD_DIR = Path("data/workloads")


class WorkloadValidationError(ValueError):
    """Raised when a workload spec or workload payload is invalid."""


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    label: str
    type: str = "number"
    aliases: List[str] = field(default_factory=list)
    default: Any = None
    required: bool = False
    description: str = ""

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "FeatureSpec":
        name = _required_string(payload, "name")
        return cls(
            name=name,
            label=str(payload.get("label") or name.replace("_", " ").title()),
            type=str(payload.get("type") or "number"),
            aliases=[str(item) for item in payload.get("aliases", [])],
            default=payload.get("default"),
            required=bool(payload.get("required", False)),
            description=str(payload.get("description") or ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "aliases": list(self.aliases),
            "default": self.default,
            "required": self.required,
            "description": self.description,
        }


@dataclass(frozen=True)
class ReasonRule:
    feature: str
    reason_code: str
    impact_gte: Optional[float] = None
    value_equals: Any = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ReasonRule":
        impact = payload.get("impact_gte")
        return cls(
            feature=_required_string(payload, "feature"),
            reason_code=_required_string(payload, "reason_code"),
            impact_gte=float(impact) if impact is not None else None,
            value_equals=payload.get("value_equals"),
        )

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "feature": self.feature,
            "reason_code": self.reason_code,
        }
        if self.impact_gte is not None:
            payload["impact_gte"] = self.impact_gte
        if self.value_equals is not None:
            payload["value_equals"] = self.value_equals
        return payload


@dataclass(frozen=True)
class PolicySpec:
    version: str
    review_threshold: float
    block_threshold: float

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "PolicySpec":
        return cls(
            version=str(payload.get("version") or "policy-baseline-0.1.0"),
            review_threshold=float(payload.get("review_threshold", 0.65)),
            block_threshold=float(payload.get("block_threshold", 0.85)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "review_threshold": self.review_threshold,
            "block_threshold": self.block_threshold,
        }


@dataclass(frozen=True)
class WorkloadSpec:
    workload_id: str
    name: str
    version: str
    description: str
    domain: str
    request_aliases: Dict[str, List[str]]
    features: List[FeatureSpec]
    policy: PolicySpec
    reason_rules: List[ReasonRule]
    reason_labels: Dict[str, str]
    outcome_labels: Dict[str, str]
    sample_payload: Dict[str, Any]
    status: str = "active"

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "WorkloadSpec":
        workload_id = _required_string(payload, "workload_id")
        features = [FeatureSpec.from_mapping(item) for item in payload.get("features", [])]
        if not features:
            raise WorkloadValidationError(f"workload '{workload_id}' must declare at least one feature")

        request_aliases = {
            str(key): [str(alias) for alias in value]
            for key, value in dict(payload.get("request_aliases") or {}).items()
            if isinstance(value, list)
        }
        sample = dict(payload.get("sample_payload") or {})
        return cls(
            workload_id=workload_id,
            name=str(payload.get("name") or workload_id.replace("_", " ").title()),
            version=str(payload.get("version") or "0.1.0"),
            description=str(payload.get("description") or ""),
            domain=str(payload.get("domain") or "general"),
            request_aliases=request_aliases,
            features=features,
            policy=PolicySpec.from_mapping(dict(payload.get("policy") or {})),
            reason_rules=[ReasonRule.from_mapping(item) for item in payload.get("reason_rules", [])],
            reason_labels={str(k): str(v) for k, v in dict(payload.get("reason_labels") or {}).items()},
            outcome_labels={str(k): str(v) for k, v in dict(payload.get("outcome_labels") or {}).items()},
            sample_payload=sample,
            status=str(payload.get("status") or "active"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workload_id": self.workload_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "domain": self.domain,
            "status": self.status,
            "request_aliases": copy.deepcopy(self.request_aliases),
            "features": [feature.to_dict() for feature in self.features],
            "policy": self.policy.to_dict(),
            "reason_rules": [rule.to_dict() for rule in self.reason_rules],
            "reason_labels": dict(self.reason_labels),
            "outcome_labels": dict(self.outcome_labels),
            "sample_payload": copy.deepcopy(self.sample_payload),
        }

    def summary(self) -> Dict[str, Any]:
        return {
            "workload_id": self.workload_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "domain": self.domain,
            "status": self.status,
            "feature_count": len(self.features),
            "policy": self.policy.to_dict(),
        }

    def feature_aliases(self) -> Dict[str, str]:
        aliases: Dict[str, str] = {}
        for feature in self.features:
            aliases[feature.name] = feature.name
            for alias in feature.aliases:
                aliases[alias] = feature.name
        return aliases

    def aliases_for(self, field_name: str, defaults: Iterable[str] = ()) -> tuple[str, ...]:
        aliases = list(defaults)
        aliases.extend(self.request_aliases.get(field_name, []))
        seen: set[str] = set()
        unique: List[str] = []
        for alias in aliases:
            if alias != field_name and alias not in seen:
                seen.add(alias)
                unique.append(alias)
        return tuple(unique)

    def normalize_features(self, features: Mapping[str, Any]) -> Dict[str, Any]:
        aliases = self.feature_aliases()
        normalized: Dict[str, Any] = {}
        for raw_key, value in features.items():
            key = str(raw_key)
            canonical = aliases.get(key, key)
            if canonical not in normalized or canonical == key:
                normalized[canonical] = value
        for feature in self.features:
            if feature.required and feature.name not in normalized:
                continue
            if feature.default is not None and feature.name not in normalized:
                normalized[feature.name] = copy.deepcopy(feature.default)
        return normalized

    def validate_payload(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        errors: List[str] = []
        for field_name, defaults in _BASE_REQUEST_ALIASES.items():
            names = (field_name, *self.aliases_for(field_name, defaults))
            if not any(_has_value(payload.get(name)) for name in names):
                errors.append(f"{field_name} is required as one of: {', '.join(names)}")

        features = payload.get("features", {})
        normalized_features: Dict[str, Any] = {}
        if not isinstance(features, Mapping):
            errors.append("features must be an object")
        else:
            normalized_features = self.normalize_features(features)
            by_name = {feature.name: feature for feature in self.features}
            for feature in self.features:
                if feature.required and feature.name not in normalized_features:
                    all_names = ", ".join((feature.name, *feature.aliases))
                    errors.append(f"feature {feature.name} is required as one of: {all_names}")
            for name, value in normalized_features.items():
                feature = by_name.get(name)
                if feature and not _matches_type(value, feature.type):
                    errors.append(f"feature {name} must be {feature.type}")

        return {
            "valid": not errors,
            "workload_id": self.workload_id,
            "errors": errors,
            "normalized": {
                "features": normalized_features,
            },
        }


class WorkloadRegistry:
    def __init__(
        self,
        workloads: Iterable[WorkloadSpec],
        active_id: str = DEFAULT_WORKLOAD_ID,
        user_workload_dir: Optional[Path] = None,
    ) -> None:
        self._workloads = {workload.workload_id: workload for workload in workloads}
        if not self._workloads:
            raise WorkloadValidationError("at least one workload spec is required")
        if active_id not in self._workloads:
            raise WorkloadValidationError(f"unknown active workload: {active_id}")
        self._active_id = active_id
        self.user_workload_dir = user_workload_dir

    @property
    def active_id(self) -> str:
        return self._active_id

    def active(self) -> WorkloadSpec:
        return self._workloads[self._active_id]

    def get(self, workload_id: str) -> WorkloadSpec:
        try:
            return self._workloads[workload_id]
        except KeyError as exc:
            raise WorkloadValidationError(f"unknown workload: {workload_id}") from exc

    def resolve_for_payload(self, payload: Mapping[str, Any]) -> WorkloadSpec:
        raw = payload.get("workload_id")
        if isinstance(raw, str) and raw.strip():
            return self.get(raw.strip())
        return self.active()

    def list(self) -> List[WorkloadSpec]:
        return sorted(self._workloads.values(), key=lambda workload: workload.workload_id)

    def activate(self, workload_id: str) -> WorkloadSpec:
        workload = self.get(workload_id)
        self._active_id = workload.workload_id
        return workload

    def import_spec(self, payload: Mapping[str, Any], persist: bool = False) -> WorkloadSpec:
        workload = WorkloadSpec.from_mapping(payload)
        self._workloads[workload.workload_id] = workload
        if persist:
            self.persist(workload)
        return workload

    def export_spec(self, workload_id: str) -> Dict[str, Any]:
        return self.get(workload_id).to_dict()

    def persist(self, workload: WorkloadSpec) -> Path:
        if self.user_workload_dir is None:
            raise WorkloadValidationError("user workload directory is not configured")
        return save_workload_spec(workload, self.user_workload_dir)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "active_workload_id": self._active_id,
            "active": self.active().to_dict(),
            "workloads": [workload.summary() for workload in self.list()],
        }


def default_workload_registry(
    active_id: str = DEFAULT_WORKLOAD_ID,
    user_workload_dir: Path = DEFAULT_USER_WORKLOAD_DIR,
) -> WorkloadRegistry:
    workloads = [WorkloadSpec.from_mapping(payload) for payload in _load_workload_payloads(user_workload_dir)]
    resolved_active_id = active_id if any(w.workload_id == active_id for w in workloads) else DEFAULT_WORKLOAD_ID
    return WorkloadRegistry(
        workloads,
        active_id=resolved_active_id,
        user_workload_dir=user_workload_dir,
    )


def load_workload_spec(path: Path) -> WorkloadSpec:
    return WorkloadSpec.from_mapping(json.loads(path.read_text(encoding="utf-8")))


def save_workload_spec(workload: WorkloadSpec, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{workload.workload_id}.json"
    path.write_text(json.dumps(workload.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _load_workload_payloads(user_workload_dir: Path) -> List[Dict[str, Any]]:
    payloads: List[Dict[str, Any]] = []
    if DEFAULT_WORKLOAD_DIR.exists():
        for path in sorted(DEFAULT_WORKLOAD_DIR.glob("*.json")):
            payloads.append(json.loads(path.read_text(encoding="utf-8")))
    if user_workload_dir.exists():
        user_payloads = {
            str(payload.get("workload_id")): payload
            for payload in (
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted(user_workload_dir.glob("*.json"))
            )
        }
        builtins = {str(payload.get("workload_id")): payload for payload in payloads}
        builtins.update(user_payloads)
        payloads = list(builtins.values())
    if payloads:
        return payloads
    return [_FALLBACK_DECISION_RISK]


_BASE_REQUEST_ALIASES: Dict[str, tuple[str, ...]] = {
    "decision_request_id": ("transaction_id", "request_id"),
    "subject_id": ("account_id", "entity_id"),
    "context_id": ("merchant_id", "application_id"),
    "value": ("amount",),
    "currency": (),
    "channel": (),
    "requested_at": ("event_time",),
}


def _required_string(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise WorkloadValidationError(f"{field_name} is required and must be a non-empty string")
    return value.strip()


def _has_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


def _matches_type(value: Any, type_name: str) -> bool:
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "string":
        return isinstance(value, str)
    return True


_FALLBACK_DECISION_RISK: Dict[str, Any] = {
    "workload_id": DEFAULT_WORKLOAD_ID,
    "name": "Decision Risk",
    "version": "0.1.0",
    "domain": "general",
    "description": "Generic high-stakes decision risk workload.",
    "request_aliases": {
        "decision_request_id": ["transaction_id", "request_id"],
        "subject_id": ["account_id", "entity_id"],
        "context_id": ["merchant_id", "application_id"],
        "value": ["amount"],
        "requested_at": ["event_time"],
    },
    "policy": {"version": "policy-baseline-0.1.0", "review_threshold": 0.65, "block_threshold": 0.85},
    "features": [
        {"name": "merchant_risk", "label": "Entity risk", "type": "number", "aliases": ["entity_risk", "subject_risk"], "default": 0.25},
        {"name": "velocity_10m", "label": "Recent velocity", "type": "number", "aliases": ["activity_velocity_10m"], "default": 0},
        {"name": "account_age_days", "label": "Subject age", "type": "number", "aliases": ["subject_age_days"], "default": 90},
        {"name": "chargeback_count", "label": "Prior adverse events", "type": "number", "aliases": ["prior_adverse_events", "adverse_event_count"], "default": 0},
        {"name": "is_high_risk_country", "label": "High-risk segment", "type": "boolean", "aliases": ["high_risk_segment"], "default": False},
    ],
    "reason_rules": [
        {"feature": "merchant_risk", "impact_gte": 0.25, "reason_code": "merchant_risk_high"},
        {"feature": "velocity_10m", "impact_gte": 0.10, "reason_code": "velocity_high"},
        {"feature": "amount", "impact_gte": 0.12, "reason_code": "amount_high"},
        {"feature": "is_high_risk_country", "value_equals": True, "reason_code": "high_risk_country"},
    ],
    "reason_labels": {},
    "outcome_labels": {"adverse": "Adverse outcome", "expected": "Expected outcome"},
    "sample_payload": {
        "decision_request_id": "req-sample",
        "workload_id": DEFAULT_WORKLOAD_ID,
        "subject_id": "subject-sample",
        "context_id": "reference-workload",
        "value": 120,
        "currency": "USD",
        "channel": "api",
        "requested_at": "2026-07-11T12:00:00Z",
        "features": {
            "entity_risk": 0.2,
            "velocity_10m": 2,
            "subject_age_days": 180,
            "prior_adverse_events": 0,
            "high_risk_segment": False,
        },
    },
}
