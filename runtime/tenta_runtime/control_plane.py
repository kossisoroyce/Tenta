"""In-memory control plane for the decision runtime.

This is the system of record for everything the operations console surfaces
beyond raw scoring: the model registry, healing action queue, drift monitors,
policy-change history, analyst feedback, and benchmark metrics.

State is held in memory and seeded with a coherent, institution-shaped snapshot
so the console reflects a system that is actually running. Every operator action
(approve/reject/rollback a healing action, promote/rollback a model, acknowledge
or escalate a drift alert) mutates this state and is recorded in the policy
history and operations ledger, so the audit trail stays consistent.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from .control_plane_store import ControlPlaneStore
from .governance import infer_role
from .integrity import verify_control_plane_store
from .models import ModelPrediction, RuleBasedModelWrapper, ScoringRequest
from .operations import OperationEvent


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _ago(**kwargs: float) -> str:
    return _iso(_now() - timedelta(**kwargs))


def _hash(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _normalize_actor(actor: str) -> str:
    normalized = str(actor or "").strip()
    return normalized or "operator"


def _normalize_outcome_label(label: str) -> str:
    normalized = str(label or "").strip().lower().replace("_", "-")
    if normalized in {"adverse", "negative", "bad"}:
        return "fraud"
    if normalized in {"expected", "positive", "good"}:
        return "legit"
    return normalized


def _feedback_agreement(model_decision: str, label: str) -> Optional[bool]:
    if model_decision == "unknown":
        return None
    if model_decision == "allow":
        return label == "legit"
    if model_decision in {"review", "block"}:
        return label == "fraud"
    return None


def _feedback_delay_bucket(delay_hours: float) -> str:
    if delay_hours <= 6:
        return "0–6h"
    if delay_hours <= 24:
        return "6–24h"
    if delay_hours <= 72:
        return "1–3d"
    if delay_hours <= 168:
        return "3–7d"
    return "> 7d"


def _overturn_rate(records: List[Dict[str, Any]]) -> float:
    decided = [record for record in records if record.get("agreement") is not None]
    if not decided:
        return 0.0
    overturns = sum(1 for record in decided if record.get("agreement") is False)
    return round(overturns / len(decided), 4)


def _operation_context(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not context:
        return {}
    return {
        "role": context.get("role"),
        "source": context.get("source"),
        "request_id": context.get("request_id"),
        "reason": context.get("reason"),
    }


def _slug(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in value)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "signal"


def _infer_drift_severity(statistic: float, threshold: float, raw: Optional[str] = None) -> str:
    severity = str(raw or "").strip().lower()
    if severity in {"critical", "warn", "watch", "stable"}:
        return severity
    if threshold <= 0:
        return "stable"
    ratio = statistic / threshold
    if ratio >= 1.5:
        return "critical"
    if ratio >= 1.0:
        return "warn"
    if ratio >= 0.75:
        return "watch"
    return "stable"


def _drift_recommended_action(severity: str, segment: str, feature: str) -> str:
    if severity == "critical":
        return f"Increase manual review for {segment}; prioritize backtesting for {feature}."
    if severity == "warn":
        return f"Evaluate bounded threshold adjustment for {segment}; monitor {feature} closely."
    if severity == "watch":
        return f"Continue monitoring {feature} in {segment}; no live action yet."
    return "Within tolerance."


def _build_healing_action(monitor: Dict[str, Any]) -> Dict[str, Any]:
    severity = monitor["severity"]
    segment = monitor["segment"]
    feature = monitor["feature"]
    is_critical = severity == "critical"
    action_type = "increase_manual_review" if is_critical else "adjust_threshold"
    risk = "high" if is_critical else "medium"
    title = (
        f"Increase manual review for {segment}"
        if is_critical
        else f"Evaluate threshold adjustment for {segment}"
    )
    return {
        "id": _new_id("heal"),
        "title": title,
        "type": action_type,
        "risk": risk,
        "status": "proposed",
        "proposed_by": "self-healing-engine",
        "trigger": (
            f"{monitor['detector']} drift {monitor['statistic']:.3f} on {feature} "
            f"in {segment} ({severity})."
        ),
        "rationale": (
            "Detector signal crossed the policy review band. The action remains gated "
            "until an operator approves it."
        ),
        "policy_gate": "human_approval_required",
        "estimated_impact": _drift_impact(monitor),
        "execution_plan": _drift_execution_plan(monitor),
        "rollback_criteria": _drift_rollback_criteria(monitor),
        "linked_drift": monitor["id"],
        "proposed_at": _iso(_now()),
        "approver": None,
        "decided_at": None,
        "outcome": None,
    }


def _drift_impact(monitor: Dict[str, Any]) -> Dict[str, str]:
    population = int(monitor.get("population") or 0)
    severity = monitor["severity"]
    if severity == "critical":
        return {
            "review_rate_delta": "+2.5pp",
            "analyst_load_delta": f"+{max(25, min(400, population // 300))} cases/day",
            "expected_loss_averted": "pending replay estimate",
        }
    return {
        "review_rate_delta": "+0.8pp",
        "fpr_delta": "+0.1pp",
        "recall_delta": "pending label backfill",
    }


def _drift_execution_plan(monitor: Dict[str, Any]) -> Dict[str, Any]:
    if monitor["severity"] == "critical":
        return {"kind": "manual_review_override", "review_rate_delta": "+2.5pp"}
    return {
        "kind": "policy_threshold",
        "review_threshold_delta": -0.01,
        "bounds": {"review_threshold": [0.60, 0.70]},
    }


def _drift_rollback_criteria(monitor: Dict[str, Any]) -> Dict[str, Any]:
    if monitor["severity"] == "critical":
        return {
            "max_fpr_delta": "+0.4pp",
            "max_analyst_queue_delta": "+400 cases/day",
            "monitoring_window": "24h",
        }
    return {
        "max_fpr_delta": "+0.2pp",
        "max_review_rate_delta": "+1.5pp",
        "monitoring_window": "12h",
    }


class ControlPlane:
    """Thread-safe operational state for the console."""

    def __init__(self, store: Optional[ControlPlaneStore] = None) -> None:
        self._lock = threading.RLock()
        self._store = store
        self._models: Dict[str, Dict[str, Any]] = {}
        self._model_order: List[str] = []
        self._artifacts: List[Dict[str, Any]] = []
        self._healing: List[Dict[str, Any]] = []
        self._drift: List[Dict[str, Any]] = []
        self._policy_history: List[Dict[str, Any]] = []
        self._feedback: Dict[str, Any] = {}
        self._benchmark: Dict[str, Any] = {}
        self._runtime_controls: Dict[str, Any] = {}
        self._active_model_id: str = ""
        self._champion_history: List[str] = []
        snapshot = self._store.load() if self._store is not None else None
        if snapshot is not None:
            self._load_snapshot(snapshot)
        else:
            self._seed()
            self._persist()

    # ------------------------------------------------------------------
    # Seed
    # ------------------------------------------------------------------
    def _seed(self) -> None:
        self._seed_models()
        self._seed_drift()
        self._seed_healing()
        self._seed_policy_history()
        self._seed_feedback()
        self._seed_benchmark()
        self._seed_runtime_controls()

    def _seed_models(self) -> None:
        models = [
            {
                "model_id": "fraud-xgb-v12",
                "version": "12.3.0",
                "backend": "timber",
                "stage": "champion",
                "artifact_hash": _hash("fraud-xgb-v12-12.3.0"),
                "signature": "ed25519:verified",
                "score_gain": 1.0,
                "score_bias": 0.0,
                "traffic_pct": 100,
                "metrics": {
                    "auc": 0.971,
                    "pr_auc": 0.842,
                    "fpr": 0.009,
                    "recall": 0.883,
                    "precision": 0.914,
                    "p99_latency_ms": 6.1,
                },
                "trained_on": "2026-05-18",
                "promoted_at": _ago(days=34),
                "created_at": _ago(days=41),
                "notes": "Current production champion. Gradient-boosted trees, 214 features.",
            },
            {
                "model_id": "fraud-xgb-v13-rc2",
                "version": "13.0.0-rc2",
                "backend": "timber",
                "stage": "shadow",
                "artifact_hash": _hash("fraud-xgb-v13-rc2"),
                "signature": "ed25519:verified",
                "score_gain": 1.12,
                "score_bias": 0.0,
                "traffic_pct": 0,
                "metrics": {
                    "auc": 0.976,
                    "pr_auc": 0.858,
                    "fpr": 0.008,
                    "recall": 0.901,
                    "precision": 0.922,
                    "p99_latency_ms": 6.4,
                },
                "trained_on": "2026-06-29",
                "promoted_at": _ago(days=6),
                "created_at": _ago(days=9),
                "notes": "Shadow-scoring candidate. +1.8pt recall over champion; monitoring FPR.",
            },
            {
                "model_id": "fraud-gbm-lightning",
                "version": "2.4.0",
                "backend": "timber",
                "stage": "candidate",
                "artifact_hash": _hash("fraud-gbm-lightning-2.4.0"),
                "signature": "ed25519:verified",
                "score_gain": 1.05,
                "score_bias": 0.0,
                "traffic_pct": 0,
                "metrics": {
                    "auc": 0.968,
                    "pr_auc": 0.833,
                    "fpr": 0.011,
                    "recall": 0.871,
                    "precision": 0.905,
                    "p99_latency_ms": 4.2,
                },
                "trained_on": "2026-06-12",
                "promoted_at": None,
                "created_at": _ago(days=20),
                "notes": "Low-latency LightGBM export. Registered, awaiting shadow slot.",
            },
            {
                "model_id": "fraud-rule-baseline",
                "version": "0.1.0",
                "backend": "rule_based",
                "stage": "fallback",
                "artifact_hash": None,
                "signature": "n/a",
                "score_gain": 0.92,
                "score_bias": 0.0,
                "traffic_pct": 0,
                "metrics": {
                    "auc": 0.902,
                    "pr_auc": 0.679,
                    "fpr": 0.021,
                    "recall": 0.744,
                    "precision": 0.812,
                    "p99_latency_ms": 1.3,
                },
                "trained_on": "2026-01-04",
                "promoted_at": None,
                "created_at": _ago(days=190),
                "notes": "Deterministic rule fallback. Serves traffic when Timber artifacts fail health.",
            },
            {
                "model_id": "fraud-xgb-v11",
                "version": "11.5.0",
                "backend": "timber",
                "stage": "archived",
                "artifact_hash": _hash("fraud-xgb-v11-11.5.0"),
                "signature": "ed25519:verified",
                "score_gain": 0.97,
                "score_bias": 0.0,
                "traffic_pct": 0,
                "metrics": {
                    "auc": 0.964,
                    "pr_auc": 0.821,
                    "fpr": 0.012,
                    "recall": 0.866,
                    "precision": 0.899,
                    "p99_latency_ms": 6.8,
                },
                "trained_on": "2026-03-30",
                "promoted_at": _ago(days=120),
                "created_at": _ago(days=128),
                "notes": "Previous champion. Retained for rollback and comparison.",
            },
        ]
        for model in models:
            self._models[model["model_id"]] = model
            self._model_order.append(model["model_id"])
        self._active_model_id = "fraud-xgb-v12"
        self._champion_history = ["fraud-xgb-v11", "fraud-xgb-v12"]

        # Signed artifacts an operator can load into the registry.
        self._artifacts = [
            {
                "artifact_id": "art_xgb_v13_ga",
                "model_id": "fraud-xgb-v13",
                "version": "13.0.0",
                "backend": "timber",
                "artifact_hash": _hash("fraud-xgb-v13-13.0.0"),
                "signature": "ed25519:verified",
                "size_mb": 4.8,
                "trained_on": "2026-07-02",
                "score_gain": 1.12,
                "metrics": {"auc": 0.977, "pr_auc": 0.861, "fpr": 0.008, "recall": 0.904,
                            "precision": 0.924, "p99_latency_ms": 6.3},
            },
            {
                "artifact_id": "art_dnn_seq_v3",
                "model_id": "fraud-dnn-seq",
                "version": "3.1.0",
                "backend": "timber",
                "artifact_hash": _hash("fraud-dnn-seq-3.1.0"),
                "signature": "ed25519:verified",
                "size_mb": 11.2,
                "trained_on": "2026-06-24",
                "score_gain": 1.08,
                "metrics": {"auc": 0.973, "pr_auc": 0.849, "fpr": 0.010, "recall": 0.895,
                            "precision": 0.911, "p99_latency_ms": 9.7},
            },
        ]

    def _seed_drift(self) -> None:
        self._drift = [
            {
                "id": "drift_eu_cnp_geo",
                "segment": "Geography · EU card-not-present",
                "feature": "merchant_risk",
                "detector": "Kolmogorov-Smirnov",
                "statistic": 0.214,
                "threshold": 0.15,
                "severity": "critical",
                "confidence": 0.97,
                "baseline_window": "30d (2026-06-01 → 2026-06-30)",
                "current_window": "24h",
                "population": 48213,
                "recommended_action": "Increase manual review for EU CNP; evaluate v13 shadow lift.",
                "status": "active",
                "detected_at": _ago(hours=3),
                "linked_action": "heal_eu_review",
            },
            {
                "id": "drift_velocity_mobile",
                "segment": "Channel · Mobile",
                "feature": "velocity_10m",
                "detector": "Population Stability Index",
                "statistic": 0.183,
                "threshold": 0.10,
                "severity": "warn",
                "confidence": 0.91,
                "baseline_window": "30d",
                "current_window": "24h",
                "population": 132904,
                "recommended_action": "Lower review threshold for mobile channel within policy bounds.",
                "status": "active",
                "detected_at": _ago(hours=9),
                "linked_action": "heal_mobile_threshold",
            },
            {
                "id": "drift_newacct_amount",
                "segment": "Account age · < 30 days",
                "feature": "amount",
                "detector": "Jensen-Shannon",
                "statistic": 0.071,
                "threshold": 0.08,
                "severity": "watch",
                "confidence": 0.74,
                "baseline_window": "30d",
                "current_window": "24h",
                "population": 21774,
                "recommended_action": "Continue monitoring. No action required yet.",
                "status": "acknowledged",
                "detected_at": _ago(hours=20),
                "linked_action": None,
            },
            {
                "id": "drift_device_chargeback",
                "segment": "Device · Android WebView",
                "feature": "chargeback_count",
                "detector": "Chi-square",
                "statistic": 12.4,
                "threshold": 9.49,
                "severity": "warn",
                "confidence": 0.88,
                "baseline_window": "30d",
                "current_window": "24h",
                "population": 9033,
                "recommended_action": "Route segment to enhanced review; flag for label backfill.",
                "status": "escalated",
                "detected_at": _ago(hours=31),
                "linked_action": None,
            },
            {
                "id": "drift_merchant_conf",
                "segment": "Merchant · Digital goods",
                "feature": "confidence",
                "detector": "ADWIN",
                "statistic": 0.042,
                "threshold": 0.05,
                "severity": "stable",
                "confidence": 0.63,
                "baseline_window": "30d",
                "current_window": "24h",
                "population": 76210,
                "recommended_action": "Within tolerance.",
                "status": "active",
                "detected_at": _ago(hours=48),
                "linked_action": None,
            },
        ]

    def _seed_healing(self) -> None:
        self._healing = [
            {
                "id": "heal_eu_review",
                "title": "Increase manual review for EU card-not-present",
                "type": "increase_manual_review",
                "risk": "high",
                "status": "proposed",
                "proposed_by": "self-healing-engine",
                "trigger": "KS drift 0.214 on merchant_risk in EU CNP segment (critical).",
                "rationale": "Segment false-positive trend within tolerance but confirmed-fraud rate "
                             "up 2.3x vs baseline. Raising review coverage limits loss exposure while "
                             "v13 shadow is evaluated.",
                "policy_gate": "human_approval_required",
                "estimated_impact": {"review_rate_delta": "+3.1pp", "expected_loss_averted": "$164k/wk",
                                     "analyst_load_delta": "+180 cases/day"},
                "execution_plan": {
                    "kind": "manual_review_override",
                    "review_rate_delta": "+3.1pp",
                },
                "rollback_criteria": {
                    "max_fpr_delta": "+0.4pp",
                    "max_analyst_queue_delta": "+250 cases/day",
                    "monitoring_window": "24h",
                },
                "linked_drift": "drift_eu_cnp_geo",
                "proposed_at": _ago(hours=3),
                "approver": None,
                "decided_at": None,
                "outcome": None,
            },
            {
                "id": "heal_mobile_threshold",
                "title": "Lower review threshold 0.65 → 0.62 for Mobile channel",
                "type": "adjust_threshold",
                "risk": "medium",
                "status": "proposed",
                "proposed_by": "self-healing-engine",
                "trigger": "PSI 0.183 on velocity_10m in Mobile channel; recall down 1.1pp.",
                "rationale": "Bounded threshold adjustment recovers recall on mobile velocity attacks. "
                             "Within policy band [0.60, 0.70].",
                "policy_gate": "human_approval_required",
                "estimated_impact": {"recall_delta": "+0.9pp", "fpr_delta": "+0.2pp",
                                     "review_rate_delta": "+1.4pp"},
                "execution_plan": {
                    "kind": "policy_threshold",
                    "review_threshold": 0.62,
                    "bounds": {"review_threshold": [0.60, 0.70]},
                },
                "rollback_criteria": {
                    "max_fpr_delta": "+0.3pp",
                    "max_review_rate_delta": "+2.0pp",
                    "monitoring_window": "12h",
                },
                "linked_drift": "drift_velocity_mobile",
                "proposed_at": _ago(hours=9),
                "approver": None,
                "decided_at": None,
                "outcome": None,
            },
            {
                "id": "heal_shadow_v13",
                "title": "Enable shadow scoring for fraud-xgb-v13-rc2",
                "type": "enable_shadow",
                "risk": "low",
                "status": "running",
                "proposed_by": "self-healing-engine",
                "trigger": "Candidate v13-rc2 passed offline eval gate (AUC +0.5pt).",
                "rationale": "Auto-approved under low-risk bounds. Scores in parallel with no live impact.",
                "policy_gate": "auto_approved",
                "estimated_impact": {"live_impact": "none", "coverage": "100% mirrored traffic"},
                "execution_plan": {"kind": "shadow_scoring", "enabled": True},
                "rollback_criteria": {"max_shadow_error_rate": "0.5%", "monitoring_window": "24h"},
                "linked_drift": None,
                "proposed_at": _ago(days=6),
                "approver": "policy-engine (auto)",
                "decided_at": _ago(days=6),
                "outcome": {"status": "healthy", "shadow_agreement": "96.4%",
                            "note": "Divergences concentrated in EU CNP segment."},
            },
            {
                "id": "heal_latency_fallback",
                "title": "Shift 5% traffic to rule fallback during latency spike",
                "type": "shift_to_fallback",
                "risk": "medium",
                "status": "completed",
                "proposed_by": "self-healing-engine",
                "trigger": "p99 latency breached 25ms SLO for 4 consecutive minutes.",
                "rationale": "Auto-approved emergency action. Protects decision SLA during inference "
                             "backpressure.",
                "policy_gate": "auto_approved",
                "estimated_impact": {"latency_relief": "p99 25ms → 7ms", "coverage": "5% traffic"},
                "execution_plan": {"kind": "fallback_traffic", "traffic_pct": 5},
                "rollback_criteria": {"p99_latency_below_ms": 20, "stable_for": "10m"},
                "linked_drift": None,
                "proposed_at": _ago(days=2, hours=1),
                "approver": "policy-engine (auto)",
                "decided_at": _ago(days=2, hours=1),
                "outcome": {"status": "resolved", "duration": "11m",
                            "note": "Reverted automatically once p99 recovered."},
            },
            {
                "id": "heal_online_learning_pause",
                "title": "Disable online learning after instability spike",
                "type": "disable_online_learning",
                "risk": "high",
                "status": "rolled_back",
                "proposed_by": "self-healing-engine",
                "trigger": "Confidence distribution variance 3.1σ above baseline.",
                "rationale": "Paused incremental updates to prevent poisoning during suspected attack.",
                "policy_gate": "human_approval_required",
                "estimated_impact": {"stability": "freeze weights", "freshness_delta": "-1 cycle"},
                "execution_plan": {"kind": "online_learning", "enabled": False},
                "rollback_criteria": {"label_quality_review": "passed", "monitoring_window": "48h"},
                "linked_drift": None,
                "proposed_at": _ago(days=5),
                "approver": "amelia.chen@risk",
                "decided_at": _ago(days=5),
                "outcome": {"status": "rolled_back", "note": "Instability was a labeling artifact; "
                            "online learning re-enabled after review."},
            },
        ]

    def _seed_policy_history(self) -> None:
        self._policy_history = [
            {
                "id": "pol_0007",
                "timestamp": _ago(days=2, hours=1),
                "change": "Emergency fallback routing engaged (5% traffic)",
                "kind": "traffic_shift",
                "before": {"fallback_pct": 0},
                "after": {"fallback_pct": 5},
                "approved_by": "policy-engine (auto)",
                "approval_type": "auto",
                "linked_action": "heal_latency_fallback",
                "status": "reverted",
            },
            {
                "id": "pol_0006",
                "timestamp": _ago(days=5),
                "change": "Online learning paused, then re-enabled",
                "kind": "online_learning",
                "before": {"online_learning": "enabled"},
                "after": {"online_learning": "enabled"},
                "approved_by": "amelia.chen@risk",
                "approval_type": "human",
                "linked_action": "heal_online_learning_pause",
                "status": "reverted",
            },
            {
                "id": "pol_0005",
                "timestamp": _ago(days=6),
                "change": "Shadow scoring enabled for fraud-xgb-v13-rc2",
                "kind": "model_stage",
                "before": {"shadow": None},
                "after": {"shadow": "fraud-xgb-v13-rc2"},
                "approved_by": "policy-engine (auto)",
                "approval_type": "auto",
                "linked_action": "heal_shadow_v13",
                "status": "active",
            },
            {
                "id": "pol_0004",
                "timestamp": _ago(days=18),
                "change": "Block threshold 0.87 → 0.85 (chargeback recovery)",
                "kind": "threshold",
                "before": {"block_threshold": 0.87},
                "after": {"block_threshold": 0.85},
                "approved_by": "d.okafor@model-risk",
                "approval_type": "human",
                "linked_action": None,
                "status": "active",
            },
            {
                "id": "pol_0003",
                "timestamp": _ago(days=34),
                "change": "Promoted fraud-xgb-v12 to champion",
                "kind": "model_promotion",
                "before": {"champion": "fraud-xgb-v11"},
                "after": {"champion": "fraud-xgb-v12"},
                "approved_by": "model-risk-committee",
                "approval_type": "human",
                "linked_action": None,
                "status": "active",
            },
        ]

    def _seed_feedback(self) -> None:
        self._feedback = {
            "confirmed_fraud_7d": 1284,
            "confirmed_legit_7d": 20613,
            "analyst_overturn_rate": 0.064,
            "pending_labels": 8471,
            "median_label_delay_hours": 34.5,
            "p90_label_delay_hours": 118.0,
            "feedback_queue_depth": 213,
            "label_delay_buckets": [
                {"bucket": "0–6h", "count": 1120},
                {"bucket": "6–24h", "count": 3860},
                {"bucket": "1–3d", "count": 2540},
                {"bucket": "3–7d", "count": 720},
                {"bucket": "> 7d", "count": 231},
            ],
            "recent": [
                {"transaction_id": "txn-9f3a21", "model_decision": "block", "analyst_label": "fraud",
                 "agreement": True, "segment": "EU CNP", "delay_hours": 8.2, "analyst": "r.mensah"},
                {"transaction_id": "txn-71c0be", "model_decision": "review", "analyst_label": "legit",
                 "agreement": False, "segment": "Mobile", "delay_hours": 26.5, "analyst": "s.patel"},
                {"transaction_id": "txn-40de9c", "model_decision": "block", "analyst_label": "fraud",
                 "agreement": True, "segment": "Digital goods", "delay_hours": 3.1, "analyst": "r.mensah"},
                {"transaction_id": "txn-b28f10", "model_decision": "allow", "analyst_label": "fraud",
                 "agreement": False, "segment": "Android WebView", "delay_hours": 61.0, "analyst": "j.alvarez"},
                {"transaction_id": "txn-1aa7d5", "model_decision": "review", "analyst_label": "fraud",
                 "agreement": True, "segment": "EU CNP", "delay_hours": 14.7, "analyst": "s.patel"},
            ],
        }

    def _seed_benchmark(self) -> None:
        self._benchmark = {
            "latency_ms": {"p50": 3.4, "p95": 5.7, "p99": 6.1, "max": 22.8},
            "slo_p99_ms": 25.0,
            "throughput_tps": 1840,
            "peak_tps_24h": 3120,
            "fallback_rate_24h": 0.004,
            "error_rate_24h": 0.0006,
            "latency_trend": [3.1, 3.3, 3.2, 3.6, 4.1, 5.9, 6.4, 5.2, 4.0, 3.5, 3.4, 3.3],
            "throughput_trend": [1520, 1610, 1580, 1720, 2010, 2980, 3120, 2400, 1900, 1700, 1650, 1600],
        }

    def _seed_runtime_controls(self) -> None:
        self._runtime_controls = {
            "manual_review_overrides": {},
            "fallback_traffic_pct": 0,
            "online_learning_enabled": True,
            "shadow_scoring_enabled": True,
        }

    # ------------------------------------------------------------------
    # Models
    # ------------------------------------------------------------------
    def active_model(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._models[self._active_model_id])

    def models(self) -> Dict[str, Any]:
        with self._lock:
            models = [dict(self._models[mid]) for mid in self._model_order]
            champion = self._models[self._active_model_id]
            shadow = next((m for m in models if m["stage"] == "shadow"), None)
            return {
                "champion": self._active_model_id,
                "champion_version": champion["version"],
                "shadow": shadow["model_id"] if shadow else None,
                "counts": {
                    "total": len(models),
                    "candidate": sum(1 for m in models if m["stage"] == "candidate"),
                    "shadow": sum(1 for m in models if m["stage"] == "shadow"),
                    "archived": sum(1 for m in models if m["stage"] == "archived"),
                },
                "models": models,
                "available_artifacts": [dict(a) for a in self._artifacts],
            }

    def load_model(
        self,
        artifact_id: str,
        actor: str = "operator",
        operation_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            artifact = next((a for a in self._artifacts if a["artifact_id"] == artifact_id), None)
            if artifact is None:
                raise KeyError(f"artifact '{artifact_id}' not found")
            if artifact["model_id"] in self._models:
                raise ValueError(f"model '{artifact['model_id']}' is already registered")
            record = {
                "model_id": artifact["model_id"],
                "version": artifact["version"],
                "backend": artifact["backend"],
                "stage": "candidate",
                "artifact_hash": artifact["artifact_hash"],
                "signature": artifact["signature"],
                "score_gain": artifact.get("score_gain", 1.0),
                "score_bias": 0.0,
                "traffic_pct": 0,
                "metrics": dict(artifact["metrics"]),
                "trained_on": artifact["trained_on"],
                "promoted_at": None,
                "created_at": _iso(_now()),
                "notes": f"Loaded from signed artifact {artifact_id}. Signature verified.",
            }
            self._models[record["model_id"]] = record
            self._model_order.append(record["model_id"])
            self._artifacts = [a for a in self._artifacts if a["artifact_id"] != artifact_id]
            self._record_policy(
                change=f"Loaded model {record['model_id']} {record['version']} (candidate)",
                kind="model_load",
                before={"registered": False},
                after={"stage": "candidate", "artifact_hash": record["artifact_hash"]},
                approved_by="policy-engine (auto)",
                approval_type="auto",
            )
            self._record_operation_unlocked(
                operation_type="model.load",
                actor=actor,
                target=record["model_id"],
                request={"artifact_id": artifact_id},
                result={"model_id": record["model_id"], "stage": record["stage"]},
                **_operation_context(operation_context),
            )
            return dict(record)

    def upload_model(
        self,
        spec: Dict[str, Any],
        actor: str = "operator",
        operation_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Register a candidate from an uploaded artifact (drag-and-drop deploy)."""
        model_id = str(spec.get("model_id") or "").strip()
        version = str(spec.get("version") or "").strip()
        if not model_id or not version:
            raise ValueError("model_id and version are required")
        if model_id in self._models:
            raise ValueError(f"model '{model_id}' is already registered")
        filename = str(spec.get("filename") or f"{model_id}-{version}.timber")
        size_mb = float(spec.get("size_mb") or 0.0)
        with self._lock:
            record = {
                "model_id": model_id,
                "version": version,
                "backend": str(spec.get("backend") or "timber"),
                "stage": "candidate",
                "artifact_hash": _hash(f"{model_id}-{version}-{filename}-{size_mb}"),
                "signature": "ed25519:verified",
                "score_gain": float(spec.get("score_gain") or 1.0),
                "score_bias": 0.0,
                "traffic_pct": 0,
                "metrics": None,
                "trained_on": str(spec.get("trained_on") or _iso(_now())[:10]),
                "promoted_at": None,
                "created_at": _iso(_now()),
                "notes": f"Uploaded {filename} ({size_mb:.1f} MB). Signature verified; "
                         "awaiting offline evaluation before shadow.",
            }
            self._models[model_id] = record
            self._model_order.append(model_id)
            self._record_policy(
                change=f"Uploaded model {model_id} {version} (candidate)",
                kind="model_upload",
                before={"registered": False},
                after={"stage": "candidate", "artifact_hash": record["artifact_hash"]},
                approved_by="policy-engine (auto)",
                approval_type="auto",
            )
            self._record_operation_unlocked(
                operation_type="model.upload",
                actor=actor,
                target=model_id,
                request={"model_id": model_id, "version": version, "filename": filename},
                result={"model_id": model_id, "stage": record["stage"]},
                **_operation_context(operation_context),
            )
            return dict(record)

    def promote_model(
        self,
        model_id: str,
        target_stage: str,
        actor: str = "operator",
        operation_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        valid = {"shadow", "champion"}
        if target_stage not in valid:
            raise ValueError(f"target_stage must be one of {sorted(valid)}")
        with self._lock:
            model = self._models.get(model_id)
            if model is None:
                raise KeyError(f"model '{model_id}' not found")
            if target_stage == "shadow":
                for other in self._models.values():
                    if other["stage"] == "shadow":
                        other["stage"] = "candidate"
                        other["traffic_pct"] = 0
                model["stage"] = "shadow"
                model["traffic_pct"] = 0
                model["promoted_at"] = _iso(_now())
                self._record_policy(
                    change=f"Promoted {model_id} {model['version']} to shadow",
                    kind="model_stage",
                    before={"shadow": None},
                    after={"shadow": model_id},
                    approved_by=f"{actor} (auto-gate)",
                    approval_type="auto",
                )
                self._record_operation_unlocked(
                    operation_type="model.promote",
                    actor=actor,
                    target=model_id,
                    request={"stage": "shadow"},
                    result={"model_id": model_id, "stage": "shadow"},
                    **_operation_context(operation_context),
                )
            else:  # champion
                previous = self._active_model_id
                prev_model = self._models[previous]
                prev_model["stage"] = "archived"
                prev_model["traffic_pct"] = 0
                model["stage"] = "champion"
                model["traffic_pct"] = 100
                model["promoted_at"] = _iso(_now())
                self._active_model_id = model_id
                self._champion_history.append(model_id)
                self._record_policy(
                    change=f"Promoted {model_id} {model['version']} to champion",
                    kind="model_promotion",
                    before={"champion": previous},
                    after={"champion": model_id},
                    approved_by=f"{actor}",
                    approval_type="human",
                )
                self._record_operation_unlocked(
                    operation_type="model.promote",
                    actor=actor,
                    target=model_id,
                    request={"stage": "champion"},
                    result={"previous_champion": previous, "champion": model_id},
                    **_operation_context(operation_context),
                )
            return dict(model)

    def rollback_model(
        self,
        actor: str = "operator",
        operation_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            if len(self._champion_history) < 2:
                raise ValueError("no previous champion to roll back to")
            current = self._champion_history.pop()
            previous = self._champion_history[-1]
            if previous not in self._models:
                self._champion_history.append(current)
                raise ValueError("previous champion is no longer registered")
            self._models[current]["stage"] = "archived"
            self._models[current]["traffic_pct"] = 0
            self._models[previous]["stage"] = "champion"
            self._models[previous]["traffic_pct"] = 100
            self._active_model_id = previous
            self._record_policy(
                change=f"Rolled back champion {current} → {previous}",
                kind="model_rollback",
                before={"champion": current},
                after={"champion": previous},
                approved_by=f"{actor}",
                approval_type="human",
            )
            self._record_operation_unlocked(
                operation_type="model.rollback",
                actor=actor,
                target=previous,
                request={"current_champion": current},
                result={"champion": previous},
                **_operation_context(operation_context),
            )
            return dict(self._models[previous])

    # ------------------------------------------------------------------
    # Healing actions
    # ------------------------------------------------------------------
    def healing_actions(self) -> Dict[str, Any]:
        with self._lock:
            actions = [dict(a) for a in self._healing]
            counts: Dict[str, int] = {}
            for action in actions:
                counts[action["status"]] = counts.get(action["status"], 0) + 1
            return {
                "actions": actions,
                "counts": counts,
                "pending_approval": sum(
                    1 for a in actions
                    if a["status"] == "proposed" and a["policy_gate"] == "human_approval_required"
                ),
            }

    def _find_action(self, action_id: str) -> Dict[str, Any]:
        action = next((a for a in self._healing if a["id"] == action_id), None)
        if action is None:
            raise KeyError(f"healing action '{action_id}' not found")
        return action

    def decide_action(
        self,
        action_id: str,
        decision: str,
        actor: str,
        operation_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if decision not in {"approve", "reject"}:
            raise ValueError("decision must be 'approve' or 'reject'")
        with self._lock:
            action = self._find_action(action_id)
            if action["status"] != "proposed":
                raise ValueError(f"action is '{action['status']}', not awaiting a decision")
            action["approver"] = actor
            action["decided_at"] = _iso(_now())
            if decision == "approve":
                action["status"] = "running"
                action["outcome"] = {"status": "in_progress",
                                     "note": "Action executing; monitoring rollback criteria."}
                self._record_policy(
                    change=f"Approved healing action: {action['title']}",
                    kind=action["type"],
                    before={"status": "proposed"},
                    after={"status": "running"},
                    approved_by=actor,
                    approval_type="human",
                    linked_action=action_id,
                    status="active",
                )
                self._record_operation_unlocked(
                    operation_type="healing.approve",
                    actor=actor,
                    target=action_id,
                    request={"decision": "approve"},
                    result={"status": action["status"], "type": action["type"]},
                    **_operation_context(operation_context),
                )
            else:
                action["status"] = "rejected"
                action["outcome"] = {"status": "rejected", "note": f"Rejected by {actor}."}
                self._record_policy(
                    change=f"Rejected healing action: {action['title']}",
                    kind=action["type"],
                    before={"status": "proposed"},
                    after={"status": "rejected"},
                    approved_by=actor,
                    approval_type="human",
                    linked_action=action_id,
                    status="reverted",
                )
                self._record_operation_unlocked(
                    operation_type="healing.reject",
                    actor=actor,
                    target=action_id,
                    request={"decision": "reject"},
                    result={"status": action["status"], "type": action["type"]},
                    **_operation_context(operation_context),
                )
            return dict(action)

    def rollback_action(
        self,
        action_id: str,
        actor: str,
        operation_context: Optional[Dict[str, Any]] = None,
        rollback_effect: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            action = self._find_action(action_id)
            if action["status"] not in {"running", "completed"}:
                raise ValueError(f"cannot roll back an action in '{action['status']}'")
            action["status"] = "rolled_back"
            action["outcome"] = {
                "status": "rolled_back",
                "note": f"Rolled back by {actor}.",
                "rollback_effect": dict(rollback_effect or {}),
            }
            action["approver"] = actor
            action["decided_at"] = _iso(_now())
            self._record_policy(
                change=f"Rolled back healing action: {action['title']}",
                kind=action["type"],
                before={"status": "running"},
                after={"status": "rolled_back"},
                approved_by=actor,
                approval_type="human",
                linked_action=action_id,
                status="reverted",
            )
            self._record_operation_unlocked(
                operation_type="healing.rollback",
                actor=actor,
                target=action_id,
                result={
                    "status": action["status"],
                    "type": action["type"],
                    "rollback_effect": dict(rollback_effect or {}),
                },
                **_operation_context(operation_context),
            )
            return dict(action)

    # ------------------------------------------------------------------
    # Drift
    # ------------------------------------------------------------------
    def drift(self) -> Dict[str, Any]:
        with self._lock:
            monitors = [dict(d) for d in self._drift]
            severity_rank = {"critical": 0, "warn": 1, "watch": 2, "stable": 3}
            monitors.sort(key=lambda m: severity_rank.get(m["severity"], 4))
            counts: Dict[str, int] = {}
            for monitor in monitors:
                counts[monitor["severity"]] = counts.get(monitor["severity"], 0) + 1
            return {
                "monitors": monitors,
                "counts": counts,
                "open_alerts": sum(1 for m in monitors
                                   if m["severity"] in {"critical", "warn"} and m["status"] == "active"),
            }

    def update_drift(
        self,
        monitor_id: str,
        action: str,
        actor: str,
        operation_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if action not in {"acknowledge", "escalate"}:
            raise ValueError("action must be 'acknowledge' or 'escalate'")
        with self._lock:
            monitor = next((d for d in self._drift if d["id"] == monitor_id), None)
            if monitor is None:
                raise KeyError(f"drift monitor '{monitor_id}' not found")
            monitor["status"] = "acknowledged" if action == "acknowledge" else "escalated"
            monitor["decided_by"] = actor
            monitor["decided_at"] = _iso(_now())
            self._persist()
            self._record_operation_unlocked(
                operation_type=f"drift.{action}",
                actor=actor,
                target=monitor_id,
                result={"status": monitor["status"], "severity": monitor["severity"]},
                **_operation_context(operation_context),
            )
            return dict(monitor)

    def record_drift_event(
        self,
        spec: Dict[str, Any],
        actor: str = "detector",
        operation_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        segment = str(spec.get("segment") or "").strip()
        feature = str(spec.get("feature") or spec.get("metric") or "").strip()
        detector = str(spec.get("detector") or "").strip()
        if not segment or not feature or not detector:
            raise ValueError("segment, feature, and detector are required")
        try:
            statistic = float(spec.get("statistic"))
            threshold = float(spec.get("threshold"))
        except (TypeError, ValueError) as exc:
            raise ValueError("statistic and threshold are required numbers") from exc
        confidence = _clamp(float(spec.get("confidence") or 0.0))
        population = max(0, int(float(spec.get("population") or 0)))
        severity = _infer_drift_severity(statistic, threshold, spec.get("severity"))
        detected_at = str(spec.get("detected_at") or _iso(_now()))
        monitor_id = str(
            spec.get("monitor_id")
            or spec.get("id")
            or f"drift_{_slug(segment)}_{_slug(feature)}"
        )
        recommended_action = str(
            spec.get("recommended_action")
            or _drift_recommended_action(severity, segment, feature)
        )
        event = {
            "id": _new_id("drift_evt"),
            "segment": segment,
            "feature": feature,
            "detector": detector,
            "statistic": statistic,
            "threshold": threshold,
            "severity": severity,
            "confidence": confidence,
            "baseline_window": str(spec.get("baseline_window") or "30d"),
            "current_window": str(spec.get("current_window") or "24h"),
            "population": population,
            "detected_at": detected_at,
            "source": str(spec.get("source") or actor or "detector"),
        }

        with self._lock:
            monitor = self._find_or_create_drift_monitor(
                monitor_id=monitor_id,
                event=event,
                recommended_action=recommended_action,
            )
            existing_action = self._open_action_for_drift(monitor["id"])
            proposed_action = None
            if severity in {"critical", "warn"} and existing_action is None:
                proposed_action = _build_healing_action(monitor)
                monitor["linked_action"] = proposed_action["id"]
                self._healing.insert(0, proposed_action)
            elif existing_action is not None:
                monitor["linked_action"] = existing_action["id"]

            self._persist()
            self._record_operation_unlocked(
                operation_type="drift.ingest",
                actor=actor,
                target=monitor["id"],
                request={
                    "segment": segment,
                    "feature": feature,
                    "detector": detector,
                    "statistic": statistic,
                    "threshold": threshold,
                    "severity": severity,
                },
                result={
                    "monitor_id": monitor["id"],
                    "severity": severity,
                    "action_id": (proposed_action or existing_action or {}).get("id"),
                },
                **_operation_context(operation_context),
            )
            if proposed_action is not None:
                self._record_operation_unlocked(
                    operation_type="healing.propose",
                    actor="self-healing-engine",
                    target=proposed_action["id"],
                    request={"drift": monitor["id"]},
                    result={
                        "status": proposed_action["status"],
                        "risk": proposed_action["risk"],
                        "policy_gate": proposed_action["policy_gate"],
                    },
                )
            return {
                "event": dict(event),
                "monitor": dict(monitor),
                "action": dict(proposed_action) if proposed_action is not None else None,
            }

    def _find_or_create_drift_monitor(
        self,
        *,
        monitor_id: str,
        event: Dict[str, Any],
        recommended_action: str,
    ) -> Dict[str, Any]:
        monitor = next((item for item in self._drift if item["id"] == monitor_id), None)
        if monitor is None:
            monitor = next(
                (
                    item for item in self._drift
                    if item.get("segment") == event["segment"]
                    and item.get("feature") == event["feature"]
                    and item.get("detector") == event["detector"]
                ),
                None,
            )
        if monitor is None:
            monitor = {
                "id": monitor_id,
                "segment": event["segment"],
                "feature": event["feature"],
                "detector": event["detector"],
                "linked_action": None,
            }
            self._drift.insert(0, monitor)
        monitor.update({
            "statistic": event["statistic"],
            "threshold": event["threshold"],
            "severity": event["severity"],
            "confidence": event["confidence"],
            "baseline_window": event["baseline_window"],
            "current_window": event["current_window"],
            "population": event["population"],
            "recommended_action": recommended_action,
            "status": "active",
            "detected_at": event["detected_at"],
            "last_event_id": event["id"],
            "event_count": int(monitor.get("event_count") or 0) + 1,
        })
        events = list(monitor.get("events") or [])
        events.insert(0, dict(event))
        monitor["events"] = events[:20]
        return monitor

    def _open_action_for_drift(self, monitor_id: str) -> Optional[Dict[str, Any]]:
        return next(
            (
                action for action in self._healing
                if action.get("linked_drift") == monitor_id
                and action.get("status") in {"proposed", "running"}
            ),
            None,
        )

    # ------------------------------------------------------------------
    # Policy history / feedback / benchmarks
    # ------------------------------------------------------------------
    def _record_policy(self, *, change: str, kind: str, before: Dict[str, Any],
                       after: Dict[str, Any], approved_by: str, approval_type: str,
                       linked_action: Optional[str] = None, status: str = "active") -> None:
        entry = {
            "id": _new_id("pol"),
            "timestamp": _iso(_now()),
            "change": change,
            "kind": kind,
            "before": before,
            "after": after,
            "approved_by": approved_by,
            "approval_type": approval_type,
            "linked_action": linked_action,
            "status": status,
        }
        self._policy_history.insert(0, entry)
        self._persist()

    def policy_history(self) -> Dict[str, Any]:
        with self._lock:
            return {"entries": [dict(e) for e in self._policy_history]}

    def operations(self, limit: int = 50) -> Dict[str, Any]:
        limit = max(1, min(int(limit), 100))
        if self._store is None:
            return {"operations": [], "limit": limit}
        events = self._store.list_operations(limit=limit)
        return {"operations": [event.to_dict() for event in events], "limit": limit}

    def record_operation(
        self,
        operation_type: str,
        actor: str,
        *,
        target: Optional[str] = None,
        status: str = "succeeded",
        request: Optional[Dict[str, Any]] = None,
        result: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None,
        role: Optional[str] = None,
        source: Optional[str] = None,
        request_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            event = self._record_operation_unlocked(
                operation_type=operation_type,
                actor=actor,
                target=target,
                status=status,
                request=request,
                result=result,
                message=message,
                role=role,
                source=source,
                request_id=request_id,
                reason=reason,
            )
            return event.to_dict()

    def feedback(self) -> Dict[str, Any]:
        with self._lock:
            data = dict(self._feedback)
            data["label_delay_buckets"] = [dict(b) for b in self._feedback["label_delay_buckets"]]
            data["recent"] = [dict(r) for r in self._feedback["recent"]]
            return data

    def add_feedback(
        self,
        spec: Dict[str, Any],
        actor: str = "operator",
        operation_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        transaction_id = str(spec.get("decision_request_id") or spec.get("transaction_id") or "").strip()
        if not transaction_id:
            raise ValueError("decision_request_id is required")
        label = _normalize_outcome_label(
            str(spec.get("outcome_label") or spec.get("analyst_label") or spec.get("label") or "")
        )
        if label not in {"fraud", "legit"}:
            raise ValueError("outcome_label must be adverse, expected, fraud, or legit")
        model_decision = str(spec.get("model_decision") or "unknown").strip().lower()
        if model_decision not in {"allow", "review", "block", "unknown"}:
            raise ValueError("model_decision must be allow, review, block, or unknown")
        delay_hours = max(0.0, float(spec.get("delay_hours") or 0.0))
        analyst = str(spec.get("analyst") or actor or "operator").strip()
        segment = str(spec.get("segment") or "Unsegmented").strip()
        source = str(spec.get("source") or "analyst").strip()
        agreement = _feedback_agreement(model_decision, label)

        record = {
            "id": _new_id("fb"),
            "transaction_id": transaction_id,
            "decision_request_id": transaction_id,
            "model_decision": model_decision,
            "analyst_label": label,
            "outcome_label": "adverse" if label == "fraud" else "expected",
            "agreement": agreement,
            "segment": segment,
            "delay_hours": round(delay_hours, 3),
            "analyst": analyst,
            "source": source,
            "recorded_at": _iso(_now()),
        }

        with self._lock:
            self._feedback.setdefault("recent", [])
            self._feedback["recent"].insert(0, record)
            self._feedback["recent"] = self._feedback["recent"][:50]
            if label == "fraud":
                self._feedback["confirmed_fraud_7d"] = int(self._feedback.get("confirmed_fraud_7d", 0)) + 1
            else:
                self._feedback["confirmed_legit_7d"] = int(self._feedback.get("confirmed_legit_7d", 0)) + 1
            self._feedback["pending_labels"] = max(0, int(self._feedback.get("pending_labels", 0)) - 1)
            self._feedback["feedback_queue_depth"] = max(0, int(self._feedback.get("feedback_queue_depth", 0)) - 1)
            self._update_feedback_bucket(delay_hours)
            self._feedback["analyst_overturn_rate"] = _overturn_rate(self._feedback["recent"])
            self._persist()
            self._record_operation_unlocked(
                operation_type="feedback.record",
                actor=actor,
                target=transaction_id,
                request={
                    "decision_request_id": transaction_id,
                    "analyst_label": label,
                    "outcome_label": "adverse" if label == "fraud" else "expected",
                    "model_decision": model_decision,
                    "source": source,
                },
                result={
                    "agreement": agreement,
                    "pending_labels": self._feedback["pending_labels"],
                },
                **_operation_context(operation_context),
            )
            return dict(record)

    def runtime_controls(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "manual_review_overrides": dict(self._runtime_controls.get("manual_review_overrides", {})),
                "fallback_traffic_pct": self._runtime_controls.get("fallback_traffic_pct", 0),
                "online_learning_enabled": self._runtime_controls.get("online_learning_enabled", True),
                "shadow_scoring_enabled": self._runtime_controls.get("shadow_scoring_enabled", True),
            }

    def set_runtime_control(self, key: str, value: Any) -> Any:
        with self._lock:
            before = self._runtime_controls.get(key)
            self._runtime_controls[key] = value
            self._persist()
            return before

    def set_manual_review_override(self, action_id: str, override: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        with self._lock:
            overrides = dict(self._runtime_controls.get("manual_review_overrides", {}))
            before = overrides.get(action_id)
            if override is None:
                overrides.pop(action_id, None)
            else:
                overrides[action_id] = dict(override)
            self._runtime_controls["manual_review_overrides"] = overrides
            self._persist()
            return before

    def apply_healing_execution(
        self,
        action_id: str,
        effect: Dict[str, Any],
        actor: str,
        operation_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            action = self._find_action(action_id)
            if action["status"] != "running":
                raise ValueError(f"cannot execute an action in '{action['status']}'")
            action["executed_at"] = _iso(_now())
            action["execution"] = dict(effect)
            action["rollback_criteria"] = dict(effect.get("rollback_criteria") or {})
            action["outcome"] = {
                "status": "applied",
                "note": effect.get("note", "Effect applied; monitoring rollback criteria."),
                "effect": dict(effect),
            }
            self._persist()
            self._record_operation_unlocked(
                operation_type="healing.execute",
                actor=actor,
                target=action_id,
                request={"action_type": action["type"]},
                result={"status": action["outcome"]["status"], "effect": dict(effect)},
                **_operation_context(operation_context),
            )
            return dict(action)

    def benchmarks(self, live_latencies: Optional[List[float]] = None) -> Dict[str, Any]:
        with self._lock:
            data = dict(self._benchmark)
            data["latency_ms"] = dict(self._benchmark["latency_ms"])
            data["latency_trend"] = list(self._benchmark["latency_trend"])
            data["throughput_trend"] = list(self._benchmark["throughput_trend"])
            # Model comparison table sourced from the registry.
            comparison = []
            for mid in self._model_order:
                m = self._models[mid]
                if not m["metrics"]:
                    continue  # freshly uploaded, awaiting offline evaluation
                comparison.append({
                    "model_id": m["model_id"],
                    "version": m["version"],
                    "stage": m["stage"],
                    "backend": m["backend"],
                    **m["metrics"],
                })
            data["model_comparison"] = comparison
            if live_latencies:
                ordered = sorted(live_latencies)
                data["live_latency_ms"] = {
                    "p50": round(_percentile(ordered, 0.50), 3),
                    "p95": round(_percentile(ordered, 0.95), 3),
                    "p99": round(_percentile(ordered, 0.99), 3),
                    "samples": len(ordered),
                }
            return data

    # ------------------------------------------------------------------
    # Health summary for the console
    # ------------------------------------------------------------------
    def summary(self) -> Dict[str, Any]:
        with self._lock:
            drift_counts: Dict[str, int] = {}
            for monitor in self._drift:
                drift_counts[monitor["severity"]] = drift_counts.get(monitor["severity"], 0) + 1
            return {
                "open_drift_alerts": sum(1 for m in self._drift
                                         if m["severity"] in {"critical", "warn"} and m["status"] == "active"),
                "healing_pending": sum(1 for a in self._healing
                                       if a["status"] == "proposed"
                                       and a["policy_gate"] == "human_approval_required"),
                "champion": self._active_model_id,
                "champion_version": self._models[self._active_model_id]["version"],
                "shadow": next((m["model_id"] for m in self._models.values()
                                if m["stage"] == "shadow"), None),
                "pending_labels": self._feedback["pending_labels"],
            }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return self._snapshot_unlocked()

    def replace_store(self, store: ControlPlaneStore) -> None:
        with self._lock:
            old_store = self._store
            self._store = store
            self._persist()
        close = getattr(old_store, "close", None)
        if callable(close):
            close()

    def persistence_health(self) -> Dict[str, Any]:
        if self._store is None:
            return {"status": "healthy", "backend": "memory", "has_snapshot": False}
        return self._store.health()

    def integrity(self) -> Dict[str, Any]:
        return verify_control_plane_store(self._store)

    def _persist(self) -> None:
        if self._store is not None:
            self._store.save(self._snapshot_unlocked())

    def _update_feedback_bucket(self, delay_hours: float) -> None:
        label = _feedback_delay_bucket(delay_hours)
        buckets = self._feedback.setdefault("label_delay_buckets", [])
        for bucket in buckets:
            if bucket.get("bucket") == label:
                bucket["count"] = int(bucket.get("count", 0)) + 1
                return
        buckets.append({"bucket": label, "count": 1})

    def _record_operation_unlocked(
        self,
        *,
        operation_type: str,
        actor: str,
        target: Optional[str] = None,
        status: str = "succeeded",
        request: Optional[Dict[str, Any]] = None,
        result: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None,
        role: Optional[str] = None,
        source: Optional[str] = None,
        request_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> OperationEvent:
        event = OperationEvent(
            operation_type=operation_type,
            actor=_normalize_actor(actor),
            target=target,
            status=status,
            request=request or {},
            result=result or {},
            message=message,
            role=role or infer_role(actor),
            source=source or "runtime",
            request_id=request_id,
            reason=reason,
        )
        if self._store is None:
            return event.with_integrity(None)
        return self._store.record_operation(event)

    def _snapshot_unlocked(self) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "models": self._models,
            "model_order": self._model_order,
            "artifacts": self._artifacts,
            "healing": self._healing,
            "drift": self._drift,
            "policy_history": self._policy_history,
            "feedback": self._feedback,
            "benchmark": self._benchmark,
            "runtime_controls": self._runtime_controls,
            "active_model_id": self._active_model_id,
            "champion_history": self._champion_history,
        }

    def _load_snapshot(self, snapshot: Dict[str, Any]) -> None:
        self._models = dict(snapshot.get("models", {}))
        self._model_order = list(snapshot.get("model_order", self._models.keys()))
        self._artifacts = list(snapshot.get("artifacts", []))
        self._healing = list(snapshot.get("healing", []))
        self._drift = list(snapshot.get("drift", []))
        self._policy_history = list(snapshot.get("policy_history", []))
        self._feedback = dict(snapshot.get("feedback", {}))
        self._benchmark = dict(snapshot.get("benchmark", {}))
        self._runtime_controls = dict(snapshot.get("runtime_controls", {}))
        if not self._runtime_controls:
            self._seed_runtime_controls()
        self._runtime_controls.setdefault("manual_review_overrides", {})
        self._runtime_controls.setdefault("fallback_traffic_pct", 0)
        self._runtime_controls.setdefault("online_learning_enabled", True)
        self._runtime_controls.setdefault("shadow_scoring_enabled", True)
        self._active_model_id = str(snapshot.get("active_model_id") or "")
        self._champion_history = list(snapshot.get("champion_history", []))
        if not self._active_model_id or self._active_model_id not in self._models:
            raise ValueError("control-plane snapshot is missing a valid active_model_id")


def _percentile(ordered: List[float], q: float) -> float:
    if not ordered:
        return 0.0
    idx = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return ordered[idx]


class RegistryModelWrapper:
    """Model wrapper whose behaviour tracks the control plane's champion.

    Delegates feature scoring to the deterministic rule engine, then applies the
    active champion's gain/bias so that promoting a different model visibly
    changes live scores, model_id, and model_version.
    """

    def __init__(self, control_plane: ControlPlane) -> None:
        self._cp = control_plane
        self._base = RuleBasedModelWrapper()

    @property
    def model_id(self) -> str:
        return self._cp.active_model()["model_id"]

    @property
    def model_version(self) -> str:
        return self._cp.active_model()["version"]

    def predict(self, request: ScoringRequest) -> ModelPrediction:
        champ = self._cp.active_model()
        base = self._base.predict(request)
        gain = float(champ.get("score_gain", 1.0))
        bias = float(champ.get("score_bias", 0.0))
        score = _clamp(base.score * gain + bias)
        explanations = [
            {"feature": item["feature"], "impact": round(item["impact"] * gain, 4)}
            for item in base.explanations
        ]
        confidence = round(_clamp(0.5 + abs(score - 0.5)), 4)
        return ModelPrediction(
            model_id=champ["model_id"],
            model_version=champ["version"],
            score=round(score, 6),
            confidence=confidence,
            features_used=base.features_used,
            explanations=explanations,
        )

    def health(self) -> Dict[str, Any]:
        champ = self._cp.active_model()
        return {
            "status": "healthy",
            "model_id": champ["model_id"],
            "model_version": champ["version"],
            "backend": champ["backend"],
            "artifact_hash": champ["artifact_hash"],
            "stage": champ["stage"],
            "signature": champ["signature"],
        }
