"""Model wrapper contracts and scoring payload models."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Protocol

from .workloads import DEFAULT_WORKLOAD_ID, WorkloadSpec


class PayloadValidationError(ValueError):
    """Raised when an incoming score request violates the runtime contract."""


@dataclass(frozen=True)
class ScoringRequest:
    transaction_id: str
    account_id: str
    amount: float
    currency: str
    merchant_id: str
    channel: str
    event_time: str
    workload_id: str = DEFAULT_WORKLOAD_ID
    features: Mapping[str, Any] = field(default_factory=dict)
    workload: Optional[WorkloadSpec] = field(default=None, compare=False, repr=False)

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        workload: Optional[WorkloadSpec] = None,
    ) -> "ScoringRequest":
        if not isinstance(payload, Mapping):
            raise PayloadValidationError("request payload must be a JSON object")

        workload_id = _workload_id(payload, workload)
        transaction_id = _required_string_any(
            payload,
            "decision_request_id",
            _aliases(workload, "decision_request_id", ("transaction_id", "request_id")),
        )
        account_id = _required_string_any(
            payload,
            "subject_id",
            _aliases(workload, "subject_id", ("account_id", "entity_id")),
        )
        merchant_id = _required_string_any(
            payload,
            "context_id",
            _aliases(workload, "context_id", ("merchant_id", "workload_id", "application_id")),
        )
        channel = _required_string(payload, "channel")
        currency = _required_string(payload, "currency").upper()
        event_time = _required_event_time(payload, _aliases(workload, "requested_at", ("event_time",)))
        amount = _required_amount(payload, _aliases(workload, "value", ("amount",)))
        features = payload.get("features", {})

        if not isinstance(features, Mapping):
            raise PayloadValidationError("features must be an object")

        return cls(
            transaction_id=transaction_id,
            account_id=account_id,
            amount=amount,
            currency=currency,
            merchant_id=merchant_id,
            channel=channel,
            event_time=event_time,
            workload_id=workload_id,
            features=_normalize_features(features, workload),
            workload=workload,
        )

    def fingerprint(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "account_id": self.account_id,
            "amount": self.amount,
            "currency": self.currency,
            "merchant_id": self.merchant_id,
            "channel": self.channel,
            "event_time": self.event_time,
            "workload_id": self.workload_id,
            "features": dict(self.features),
        }


@dataclass(frozen=True)
class ModelPrediction:
    model_id: str
    model_version: str
    score: float
    confidence: Optional[float] = None
    features_used: List[str] = field(default_factory=list)
    explanations: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "score": self.score,
            "confidence": self.confidence,
            "features_used": list(self.features_used),
            "explanations": list(self.explanations),
        }


@dataclass(frozen=True)
class ScoreResponse:
    transaction_id: str
    score: float
    decision: str
    model_id: str
    model_version: str
    policy_version: str
    reason_codes: List[str]
    latency_ms: float
    workload_id: str = DEFAULT_WORKLOAD_ID

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "decision_request_id": self.transaction_id,
            "workload_id": self.workload_id,
            "score": self.score,
            "decision": self.decision,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "policy_version": self.policy_version,
            "reason_codes": list(self.reason_codes),
            "latency_ms": self.latency_ms,
        }


class ModelWrapper(Protocol):
    """Stable interface for Timber-backed and fallback decision models."""

    model_id: str
    model_version: str

    def predict(self, request: ScoringRequest) -> ModelPrediction:
        ...

    def health(self) -> Dict[str, Any]:
        ...


class RuleBasedModelWrapper:
    """Deterministic local model used until a signed Timber artifact is loaded."""

    model_id = "fraud-rule-baseline"
    model_version = "0.1.0"

    def predict(self, request: ScoringRequest) -> ModelPrediction:
        merchant_risk = _feature_float(request, "merchant_risk", 0.25)
        velocity_10m = _feature_float(request, "velocity_10m", 0.0)
        account_age_days = _feature_float(request, "account_age_days", 90.0)
        chargeback_count = _feature_float(request, "chargeback_count", 0.0)
        high_risk_country = _feature_bool(request, "is_high_risk_country", False)

        amount_component = min(request.amount / 10_000.0, 1.0) * 0.20
        merchant_component = _clamp(merchant_risk) * 0.35
        velocity_component = min(max(velocity_10m, 0.0) / 20.0, 1.0) * 0.20
        chargeback_component = min(max(chargeback_count, 0.0) / 5.0, 1.0) * 0.15
        new_account_component = (1.0 - min(max(account_age_days, 0.0) / 180.0, 1.0)) * 0.06
        country_component = 0.04 if high_risk_country else 0.0

        impacts = {
            "amount": amount_component,
            "merchant_risk": merchant_component,
            "velocity_10m": velocity_component,
            "chargeback_count": chargeback_component,
            "account_age_days": new_account_component,
            "is_high_risk_country": country_component,
        }
        score = _clamp(0.03 + sum(impacts.values()))
        confidence = round(_clamp(0.50 + abs(score - 0.50)), 4)

        explanations = [
            {"feature": feature, "impact": round(impact, 4)}
            for feature, impact in sorted(impacts.items(), key=lambda item: item[1], reverse=True)
            if impact > 0.0
        ]
        features_used = ["amount"] + sorted(str(name) for name in request.features.keys())

        return ModelPrediction(
            model_id=self.model_id,
            model_version=self.model_version,
            score=round(score, 6),
            confidence=confidence,
            features_used=features_used,
            explanations=explanations,
        )

    def health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "model_id": self.model_id,
            "model_version": self.model_version,
            "backend": "rule_based",
            "artifact_hash": None,
        }


def _required_string(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise PayloadValidationError(f"{field_name} is required and must be a non-empty string")
    return value.strip()


def _required_string_any(
    payload: Mapping[str, Any],
    field_name: str,
    aliases: tuple[str, ...],
) -> str:
    for candidate in (field_name, *aliases):
        value = payload.get(candidate)
        if isinstance(value, str) and value.strip():
            return value.strip()
    all_names = ", ".join((field_name, *aliases))
    raise PayloadValidationError(f"{field_name} is required as one of: {all_names}")


def _required_amount(payload: Mapping[str, Any], aliases: tuple[str, ...]) -> float:
    value = None
    for candidate in ("value", *aliases):
        if candidate in payload:
            value = payload.get(candidate)
            break
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise PayloadValidationError("amount is required and must be numeric")
    amount = float(value)
    if amount < 0:
        raise PayloadValidationError("amount must be greater than or equal to zero")
    return amount


def _required_event_time(payload: Mapping[str, Any], aliases: tuple[str, ...]) -> str:
    raw = None
    for candidate in ("requested_at", *aliases):
        if candidate in payload:
            raw = payload.get(candidate)
            break
    if not isinstance(raw, str) or not raw.strip():
        raise PayloadValidationError("event_time is required and must be an ISO-8601 string")

    value = raw.strip()
    parse_value = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(parse_value)
    except ValueError as exc:
        raise PayloadValidationError("event_time must be a valid ISO-8601 timestamp") from exc
    return value


def _normalize_features(features: Mapping[str, Any], workload: Optional[WorkloadSpec] = None) -> Dict[str, Any]:
    if workload is not None:
        return workload.normalize_features(features)
    aliases = {
        "entity_risk": "merchant_risk",
        "subject_risk": "merchant_risk",
        "subject_age_days": "account_age_days",
        "prior_adverse_events": "chargeback_count",
        "adverse_event_count": "chargeback_count",
        "high_risk_segment": "is_high_risk_country",
    }
    normalized: Dict[str, Any] = {}
    for raw_key, value in features.items():
        key = str(raw_key)
        canonical = aliases.get(key, key)
        if canonical not in normalized or canonical == key:
            normalized[canonical] = value
    return normalized


def _aliases(
    workload: Optional[WorkloadSpec],
    field_name: str,
    defaults: tuple[str, ...],
) -> tuple[str, ...]:
    if workload is None:
        return defaults
    return workload.aliases_for(field_name, defaults)


def _workload_id(payload: Mapping[str, Any], workload: Optional[WorkloadSpec]) -> str:
    raw = payload.get("workload_id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if workload is not None:
        return workload.workload_id
    return DEFAULT_WORKLOAD_ID


def _feature_float(request: ScoringRequest, name: str, default: float) -> float:
    value = request.features.get(name, default)
    if isinstance(value, bool):
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _feature_bool(request: ScoringRequest, name: str, default: bool) -> bool:
    value = request.features.get(name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))
