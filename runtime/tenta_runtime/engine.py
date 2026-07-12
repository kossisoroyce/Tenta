"""Runtime engine for validating, scoring, policy evaluation, and audit."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Mapping, Optional

from .audit import AuditSink, DecisionEvent, InMemoryAuditSink
from .integrity import verify_runtime_store
from .models import ModelWrapper, PayloadValidationError, ScoreResponse, ScoringRequest
from .policy import DecisionPolicy
from .storage import InMemoryRuntimeStore, RuntimeStore
from .workloads import WorkloadRegistry, WorkloadValidationError, default_workload_registry


class IdempotencyConflictError(ValueError):
    """Raised when a transaction id is retried with a different request body."""


class RuntimeEngine:
    """Synchronous scoring runtime for workload-aware decision APIs."""

    def __init__(
        self,
        model: ModelWrapper,
        policy: Optional[DecisionPolicy] = None,
        audit_sink: Optional[AuditSink] = None,
        store: Optional[RuntimeStore] = None,
        workloads: Optional[WorkloadRegistry] = None,
    ) -> None:
        self.workloads = workloads or default_workload_registry()
        self.model = model
        self.policy = policy or DecisionPolicy.from_workload(self.workloads.active())
        self.audit_sink = audit_sink or InMemoryAuditSink()
        self.store = store or InMemoryRuntimeStore()
        self._lock = threading.RLock()
        self._last_audit_error: Optional[str] = None

    def score(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        try:
            workload = self.workloads.resolve_for_payload(payload)
        except WorkloadValidationError as exc:
            raise PayloadValidationError(str(exc)) from exc
        request = ScoringRequest.from_mapping(payload, workload=workload)
        fingerprint = request.fingerprint()

        cached = self.store.get_cached_decision(request.transaction_id)
        if cached is not None:
            if cached.fingerprint != fingerprint:
                raise IdempotencyConflictError(
                    "transaction_id was already scored with a different payload"
                )
            return dict(cached.response)

        start = time.perf_counter()
        prediction = self.model.predict(request)
        policy = self.policy if workload.workload_id == self.workloads.active_id else DecisionPolicy.from_workload(workload)
        policy_decision = policy.evaluate(request, prediction)
        latency_ms = round((time.perf_counter() - start) * 1000.0, 3)

        model_health = self.model.health()
        degraded_mode = model_health.get("status") != "healthy" or self._last_audit_error is not None
        response = ScoreResponse(
            transaction_id=request.transaction_id,
            score=prediction.score,
            decision=policy_decision.decision,
            model_id=prediction.model_id,
            model_version=prediction.model_version,
            policy_version=policy_decision.policy_version,
            reason_codes=policy_decision.reason_codes,
            latency_ms=latency_ms,
            workload_id=request.workload_id,
        ).to_dict()

        event = DecisionEvent(
            transaction_id=request.transaction_id,
            event_time=request.event_time,
            model_id=prediction.model_id,
            model_version=prediction.model_version,
            policy_version=policy_decision.policy_version,
            score=prediction.score,
            decision=policy_decision.decision,
            reason_codes=policy_decision.reason_codes,
            latency_ms=latency_ms,
            degraded_mode=degraded_mode,
        )

        with self._lock:
            event = self.store.record_decision(
                transaction_id=request.transaction_id,
                fingerprint=fingerprint,
                response=response,
                event=event,
            )
        self._append_audit_event(event)

        return response

    def decisions(self, limit: int = 25) -> Dict[str, Any]:
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100

        return {
            "decisions": [event.to_dict() for event in self.store.list_decisions(limit)],
            "limit": limit,
        }

    def transaction(self, transaction_id: str) -> Optional[Dict[str, Any]]:
        event = self.store.get_decision(transaction_id)
        if event is None:
            return None
        return event.to_dict()

    def replace_store(self, store: RuntimeStore) -> None:
        with self._lock:
            old_store = self.store
            self.store = store
        close = getattr(old_store, "close", None)
        if callable(close):
            close()

    def replace_policy(self, policy: DecisionPolicy) -> None:
        with self._lock:
            self.policy = policy

    def workload_registry(self) -> Dict[str, Any]:
        return self.workloads.to_dict()

    def workload(self, workload_id: str) -> Dict[str, Any]:
        return self.workloads.get(workload_id).to_dict()

    def export_workload(self, workload_id: str) -> Dict[str, Any]:
        return self.workloads.export_spec(workload_id)

    def import_workload(self, spec: Mapping[str, Any], persist: bool = False) -> Dict[str, Any]:
        with self._lock:
            workload = self.workloads.import_spec(spec, persist=persist)
            return workload.to_dict()

    def activate_workload(self, workload_id: str) -> Dict[str, Any]:
        with self._lock:
            workload = self.workloads.activate(workload_id)
            self.policy = DecisionPolicy.from_workload(workload)
            return workload.to_dict()

    def validate_workload_payload(
        self,
        payload: Mapping[str, Any],
        workload_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        workload = self.workloads.get(workload_id) if workload_id else self.workloads.resolve_for_payload(payload)
        result = workload.validate_payload(payload)
        if result["valid"]:
            request = ScoringRequest.from_mapping(payload, workload=workload)
            result["normalized"] = request.to_dict()
        return result

    def integrity(self) -> Dict[str, Any]:
        return verify_runtime_store(self.store)

    def health(self) -> Dict[str, Any]:
        model_health = self.model.health()
        policy_health = self.policy.health()
        audit_health = self.audit_sink.health()
        storage_health = self.store.health()
        components = {
            "model": model_health,
            "policy": policy_health,
            "audit": audit_health,
            "storage": storage_health,
        }

        status = "healthy"
        if any(component.get("status") != "healthy" for component in components.values()):
            status = "degraded"
        if self._last_audit_error is not None:
            status = "degraded"
            audit_health = dict(audit_health)
            audit_health["last_error"] = self._last_audit_error
            components["audit"] = audit_health

        return {
            "status": status,
            "runtime": {"status": status, "cached_decisions": self.store.count_cached_decisions()},
            "workload": self.workloads.active().summary(),
            **components,
        }

    def _append_audit_event(self, event: DecisionEvent) -> None:
        try:
            self.audit_sink.append(event)
            self._last_audit_error = None
        except Exception as exc:  # pragma: no cover - exercised by custom sinks in integration tests.
            self._last_audit_error = str(exc)
