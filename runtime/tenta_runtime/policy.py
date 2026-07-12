"""Decision policy for score-to-action mapping."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from .models import ModelPrediction, ScoringRequest
from .workloads import WorkloadSpec


@dataclass(frozen=True)
class PolicyDecision:
    decision: str
    policy_version: str
    reason_codes: List[str]


@dataclass(frozen=True)
class DecisionPolicy:
    """Threshold policy for the initial runtime scoring path."""

    version: str = "policy-baseline-0.1.0"
    review_threshold: float = 0.65
    block_threshold: float = 0.85
    workload: Optional[WorkloadSpec] = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.review_threshold <= self.block_threshold <= 1.0:
            raise ValueError("thresholds must satisfy 0 <= review_threshold <= block_threshold <= 1")

    @classmethod
    def from_workload(cls, workload: WorkloadSpec) -> "DecisionPolicy":
        return cls(
            version=workload.policy.version,
            review_threshold=workload.policy.review_threshold,
            block_threshold=workload.policy.block_threshold,
            workload=workload,
        )

    def evaluate(self, request: ScoringRequest, prediction: ModelPrediction) -> PolicyDecision:
        score = prediction.score
        reason_codes: List[str] = []

        if score >= self.block_threshold:
            decision = "block"
            reason_codes.append("score_above_block_threshold")
        elif score >= self.review_threshold:
            decision = "review"
            reason_codes.append("score_above_review_threshold")
        else:
            decision = "allow"
            reason_codes.append("score_below_review_threshold")

        reason_codes.extend(self._feature_reason_codes(request, prediction))
        return PolicyDecision(decision=decision, policy_version=self.version, reason_codes=reason_codes)

    def health(self) -> dict:
        return {
            "status": "healthy",
            "version": self.version,
            "review_threshold": self.review_threshold,
            "block_threshold": self.block_threshold,
            "workload_id": self.workload.workload_id if self.workload else None,
        }

    def _feature_reason_codes(self, request: ScoringRequest, prediction: ModelPrediction) -> List[str]:
        workload = request.workload or self.workload
        if workload is not None and workload.reason_rules:
            return _workload_reason_codes(workload, request, prediction)

        reasons: List[str] = []
        explanations = {item.get("feature"): item.get("impact", 0.0) for item in prediction.explanations}

        if explanations.get("merchant_risk", 0.0) >= 0.25:
            reasons.append("merchant_risk_high")
        if explanations.get("velocity_10m", 0.0) >= 0.10:
            reasons.append("velocity_high")
        if explanations.get("amount", 0.0) >= 0.12:
            reasons.append("amount_high")
        if request.features.get("is_high_risk_country") is True:
            reasons.append("high_risk_country")

        return reasons


def _workload_reason_codes(
    workload: WorkloadSpec,
    request: ScoringRequest,
    prediction: ModelPrediction,
) -> List[str]:
    reasons: List[str] = []
    explanations = {item.get("feature"): item.get("impact", 0.0) for item in prediction.explanations}
    feature_values = {"amount": request.amount, **dict(request.features)}
    for rule in workload.reason_rules:
        if rule.impact_gte is not None and float(explanations.get(rule.feature, 0.0) or 0.0) >= rule.impact_gte:
            reasons.append(rule.reason_code)
            continue
        if rule.value_equals is not None and _same_value(feature_values.get(rule.feature), rule.value_equals):
            reasons.append(rule.reason_code)
    return reasons


def _same_value(left: Any, right: Any) -> bool:
    if isinstance(right, bool):
        return left is right
    return left == right
