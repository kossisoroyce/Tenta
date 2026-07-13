"""HTTP routing for the operations console control plane.

Kept separate from ``api.py`` so the scoring/persistence surface and the console
surface can evolve independently. ``ConsoleRoutes.dispatch`` returns a
``(status, payload)`` tuple when it handles a request, or ``None`` to let the
core runtime handler take it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote

from .artifacts import ArtifactValidationError, TimberArtifactManifest
from .audit import InMemoryAuditSink
from .control_plane import ControlPlane
from .database import RuntimeConfig, load_runtime_config, save_runtime_config
from .engine import RuntimeEngine
from .governance import ActorContext, GovernanceError
from .healing_executor import HealingExecutor
from .integrity import combine_reports
from .models import TimberModelWrapper
from .policy import DecisionPolicy
from .replay import run_replay
from .storage import InMemoryRuntimeStore

Result = Optional[Tuple[int, Dict[str, Any]]]


class ConsoleRoutes:
    def __init__(
        self,
        engine: RuntimeEngine,
        control_plane: ControlPlane,
        config_path: Optional[str] = None,
        workload_dir: Optional[Path] = None,
    ) -> None:
        self.engine = engine
        self.cp = control_plane
        self.executor = HealingExecutor(engine, control_plane)
        self.config_path = config_path
        self.workload_dir = workload_dir
        if workload_dir is not None:
            self.engine.workloads.user_workload_dir = workload_dir

    # ------------------------------------------------------------------
    def dispatch(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]],
        query: Optional[Dict[str, List[str]]] = None,
        request_context: Optional[Dict[str, Any]] = None,
    ) -> Result:
        body = body or {}
        query = query or {}
        request_context = request_context or {}
        base_url = str(request_context.get("base_url") or "http://127.0.0.1:8080").rstrip("/")
        actor_context = ActorContext.from_payload(
            body,
            default_actor="viewer@console",
            default_role="viewer",
            default_source="console",
        )
        try:
            if method == "GET":
                return self._get(path, query, base_url)
            if method == "POST":
                return self._post(path, body, actor_context, base_url)
        except GovernanceError as exc:
            return 403, {
                "error": "forbidden",
                "message": str(exc),
                "operation": exc.operation,
                "role": exc.role,
                "allowed_roles": exc.allowed_roles,
            }
        except KeyError as exc:
            return 404, {"error": "not_found", "message": str(exc).strip("'")}
        except ValueError as exc:
            return 409, {"error": "conflict", "message": str(exc)}
        except Exception as exc:  # pragma: no cover - defensive boundary
            return 500, {"error": "internal_error", "message": str(exc)}
        return None

    # ------------------------------------------------------------------
    def _get(self, path: str, query: Dict[str, List[str]], base_url: str) -> Result:
        if path == "/v1/overview":
            return 200, self._overview()
        if path == "/v1/serving-endpoint":
            return 200, self._serving_endpoint(base_url)
        if path == "/v1/workloads":
            return 200, self.engine.workload_registry()
        if path == "/v1/workloads/active":
            return 200, self.engine.workloads.active().to_dict()
        if path.startswith("/v1/workloads/") and path.endswith("/export"):
            workload_id = path[len("/v1/workloads/"):-len("/export")]
            return 200, {
                "workload_id": workload_id,
                "spec": self.engine.export_workload(workload_id),
            }
        if path.startswith("/v1/workloads/") and path.endswith("/sample"):
            workload_id = path[len("/v1/workloads/"):-len("/sample")]
            return 200, {
                "workload_id": workload_id,
                "sample_payload": self.engine.workloads.get(workload_id).sample_payload,
            }
        if path.startswith("/v1/workloads/"):
            workload_id = path[len("/v1/workloads/"):]
            return 200, self.engine.workload(workload_id)
        if path == "/v1/models":
            return 200, self._models_payload(base_url)
        if path.startswith("/v1/models/") and path.endswith("/endpoint"):
            model_id = unquote(path[len("/v1/models/"):-len("/endpoint")])
            return 200, self._serving_endpoint(base_url, model_id=model_id)
        if path.startswith("/v1/models/"):
            model_id = unquote(path[len("/v1/models/"):])
            return 200, self._decorate_model(self.cp.model(model_id), base_url)
        if path == "/v1/healing/actions":
            return 200, self.cp.healing_actions()
        if path == "/v1/drift":
            return 200, self.cp.drift()
        if path == "/v1/policy/history":
            return 200, self.cp.policy_history()
        if path == "/v1/operations":
            return 200, self.cp.operations(limit=_parse_limit(query.get("limit", ["50"])[0]))
        if path == "/v1/audit/integrity":
            return 200, combine_reports(self.engine.integrity(), self.cp.integrity())
        if path == "/v1/feedback":
            return 200, self.cp.feedback()
        if path == "/v1/benchmarks":
            return 200, self.cp.benchmarks(live_latencies=self._live_latencies())
        return None

    def _post(
        self,
        path: str,
        body: Dict[str, Any],
        actor_context: ActorContext,
        base_url: str,
    ) -> Result:
        if path == "/v1/workloads/import":
            self._authorize(actor_context, "workload.import", target=str(body.get("workload_id") or "workload"))
            spec = body.get("spec")
            if not isinstance(spec, dict):
                spec = body
            persist = bool(body.get("persist", True))
            activate = bool(body.get("activate", False))
            workload = self.engine.import_workload(spec, persist=persist)
            active = None
            if activate:
                active = self.engine.activate_workload(workload["workload_id"])
                self._persist_active_workload(workload["workload_id"])
            operation = self.cp.record_operation(
                "workload.import",
                actor_context.actor,
                target=workload["workload_id"],
                request={
                    "workload_id": workload["workload_id"],
                    "version": workload["version"],
                    "persist": persist,
                    "activate": activate,
                },
                result={
                    "workload_id": workload["workload_id"],
                    "version": workload["version"],
                    "active": active["workload_id"] if active else self.engine.workloads.active_id,
                },
                role=actor_context.role,
                source=actor_context.source,
                request_id=actor_context.request_id,
                reason=actor_context.reason,
            )
            return 200, {"workload": workload, "active": active, "operation": operation}

        if path == "/v1/workloads/validate":
            payload = body.get("payload")
            if not isinstance(payload, dict):
                payload = body
            workload_id = body.get("workload_id")
            return 200, self.engine.validate_workload_payload(
                payload,
                workload_id=str(workload_id).strip() if workload_id else None,
            )
        if path == "/v1/workloads/activate":
            workload_id = str(body.get("workload_id") or "").strip()
            self._authorize(actor_context, "workload.activate", target=workload_id)
            before = self.engine.workloads.active().summary()
            workload = self.engine.activate_workload(workload_id)
            self._persist_active_workload(workload_id)
            operation = self.cp.record_operation(
                "workload.activate",
                actor_context.actor,
                target=workload_id,
                request={"workload_id": workload_id},
                result={"before": before, "after": {k: workload[k] for k in ("workload_id", "name", "version", "domain")}},
                role=actor_context.role,
                source=actor_context.source,
                request_id=actor_context.request_id,
                reason=actor_context.reason,
            )
            return 200, {"active": workload, "operation": operation}

        # Models
        if path == "/v1/models/load":
            self._authorize(actor_context, "model.load", target=str(body.get("artifact_id") or ""))
            artifact_id = str(body.get("artifact_id") or "")
            model = self.cp.load_model(
                artifact_id,
                actor=actor_context.actor,
                operation_context=actor_context.to_dict(),
            )
            return 200, self._decorate_model(model, base_url)
        if path == "/v1/models/register":
            self._authorize(actor_context, "model.register", target=str(body.get("model_id") or "manifest"))
            manifest_payload = body.get("manifest")
            if not isinstance(manifest_payload, dict):
                manifest_payload = body
            manifest_path = str(body.get("manifest_path") or "").strip() or None
            manifest = TimberArtifactManifest.from_mapping(
                manifest_payload,
                manifest_path=Path(manifest_path) if manifest_path else None,
            )
            artifact_validation = manifest.validation_report()
            if not artifact_validation["valid"]:
                raise ValueError("artifact manifest is invalid: " + "; ".join(artifact_validation["errors"]))
            compatibility = manifest.compatibility_report(self.engine.workloads.active())
            model = self.cp.register_model_manifest(
                manifest.to_dict(),
                manifest_path=manifest_path,
                artifact_validation=artifact_validation,
                workload_compatibility=compatibility,
                actor=actor_context.actor,
                operation_context=actor_context.to_dict(),
            )
            return 200, self._decorate_model(model, base_url)
        if path == "/v1/models/upload":
            self._authorize(actor_context, "model.upload", target=str(body.get("model_id") or ""))
            model = self.cp.upload_model(
                body,
                actor=actor_context.actor,
                operation_context=actor_context.to_dict(),
            )
            return 200, self._decorate_model(model, base_url)
        if path == "/v1/models/rollback":
            self._authorize(actor_context, "model.rollback")
            self._require_reason(
                actor_context,
                "model.rollback",
                target="champion",
                detail="Rolling back the live champion model",
            )
            model = self.cp.rollback_model(
                actor=actor_context.actor,
                operation_context=actor_context.to_dict(),
            )
            return 200, self._decorate_model(model, base_url)
        if path.startswith("/v1/models/") and path.endswith("/promote"):
            model_id = unquote(path[len("/v1/models/"):-len("/promote")])
            self._authorize(actor_context, "model.promote", target=model_id)
            stage = str(body.get("stage") or "shadow")
            promotion_gate = self._promotion_gate(model_id)
            if stage == "champion" and promotion_gate.get("valid"):
                self._require_reason(
                    actor_context,
                    "model.promote",
                    target=model_id,
                    detail=f"Promoting {model_id} to champion",
                )
            model = self.cp.promote_model(
                model_id,
                stage,
                actor=actor_context.actor,
                operation_context=actor_context.to_dict(),
                promotion_gate=promotion_gate,
            )
            return 200, self._decorate_model(model, base_url)

        if path == "/v1/drift/events":
            self._authorize(actor_context, "drift.ingest")
            return 200, self.cp.record_drift_event(
                body,
                actor=actor_context.actor,
                operation_context=actor_context.to_dict(),
            )

        # Healing actions
        if path.startswith("/v1/healing/actions/"):
            rest = path[len("/v1/healing/actions/"):]
            if "/" in rest:
                action_id, verb = rest.split("/", 1)
                if verb == "approve":
                    self._authorize(actor_context, "healing.approve", target=action_id)
                    action = self._healing_action(action_id)
                    if action.get("risk") == "high" or action.get("policy_gate") == "human_approval_required":
                        self._require_reason(
                            actor_context,
                            "healing.approve",
                            target=action_id,
                            detail=f"Approving healing action {action_id}",
                        )
                    self.cp.decide_action(
                        action_id,
                        "approve",
                        actor_context.actor,
                        operation_context=actor_context.to_dict(),
                    )
                    return 200, self.executor.execute(action_id, actor_context)
                if verb == "reject":
                    self._authorize(actor_context, "healing.reject", target=action_id)
                    return 200, self.cp.decide_action(
                        action_id,
                        "reject",
                        actor_context.actor,
                        operation_context=actor_context.to_dict(),
                    )
                if verb == "rollback":
                    self._authorize(actor_context, "healing.rollback", target=action_id)
                    return 200, self.executor.rollback(action_id, actor_context)

        # Drift
        if path.startswith("/v1/drift/"):
            rest = path[len("/v1/drift/"):]
            if "/" in rest:
                monitor_id, verb = rest.split("/", 1)
                if verb in {"acknowledge", "escalate"}:
                    self._authorize(actor_context, f"drift.{verb}", target=monitor_id)
                    return 200, self.cp.update_drift(
                        monitor_id,
                        verb,
                        actor_context.actor,
                        operation_context=actor_context.to_dict(),
                    )

        if path == "/v1/feedback":
            target_id = str(body.get("decision_request_id") or body.get("transaction_id") or "")
            self._authorize(actor_context, "feedback.record", target=target_id)
            payload = dict(body)
            if not payload.get("transaction_id") and payload.get("decision_request_id"):
                payload["transaction_id"] = payload["decision_request_id"]
            transaction_id = str(payload.get("transaction_id") or "").strip()
            if transaction_id and not payload.get("model_decision"):
                decision = self.engine.transaction(transaction_id)
                if decision is not None:
                    payload["model_decision"] = decision.get("decision")
            return 200, self.cp.add_feedback(
                payload,
                actor=actor_context.actor,
                operation_context=actor_context.to_dict(),
            )

        return None

    def _persist_active_workload(self, workload_id: str) -> None:
        if not self.config_path:
            return
        config = load_runtime_config(self.config_path)
        save_runtime_config(
            RuntimeConfig(
                storage_url=config.storage_url,
                active_workload_id=workload_id,
                updated_at=datetime.now(timezone.utc).isoformat(),
            ),
            self.config_path,
        )

    def _authorize(self, actor_context: ActorContext, operation: str, target: Optional[str] = None) -> None:
        try:
            actor_context.require(operation)
        except GovernanceError as exc:
            self.cp.record_operation(
                "governance.denied",
                actor_context.actor,
                target=target,
                status="denied",
                request={"operation": operation, **actor_context.to_dict()},
                result={"allowed_roles": exc.allowed_roles},
                message=str(exc),
                role=actor_context.role,
                source=actor_context.source,
                request_id=actor_context.request_id,
                reason=actor_context.reason,
            )
            raise

    def _require_reason(
        self,
        actor_context: ActorContext,
        operation: str,
        *,
        target: Optional[str],
        detail: str,
    ) -> None:
        if actor_context.reason:
            return
        message = f"{detail} requires a justification note."
        self.cp.record_operation(
            "governance.denied",
            actor_context.actor,
            target=target,
            status="denied",
            request={"operation": operation, "reason_required": True, **actor_context.to_dict()},
            result={"required": "reason"},
            message=message,
            role=actor_context.role,
            source=actor_context.source,
            request_id=actor_context.request_id,
            reason=actor_context.reason,
        )
        raise ValueError(message)

    def _healing_action(self, action_id: str) -> Dict[str, Any]:
        action = next((item for item in self.cp.healing_actions()["actions"] if item["id"] == action_id), None)
        if action is None:
            raise KeyError(f"healing action '{action_id}' not found")
        return action

    def _models_payload(self, base_url: str) -> Dict[str, Any]:
        payload = self.cp.models()
        payload["models"] = [self._decorate_model(model, base_url) for model in payload["models"]]
        payload["serving_endpoint"] = self._serving_endpoint(base_url)
        return payload

    def _promotion_gate(self, model_id: str) -> Dict[str, Any]:
        model = self.cp.model(model_id)
        checks: Dict[str, Any] = {
            "artifact": {"valid": True, "status": "skipped", "reason": "seeded model record"},
            "workload": {"valid": True, "status": "skipped", "reason": "seeded model record"},
            "replay": {"valid": True, "status": "skipped", "reason": "seeded model record"},
        }
        manifest_payload = model.get("artifact_manifest")
        if isinstance(manifest_payload, dict):
            try:
                manifest = TimberArtifactManifest.from_mapping(manifest_payload)
                artifact = manifest.validation_report()
                compatibility = manifest.compatibility_report(self.engine.workloads.active())
                replay = self._run_manifest_replay(manifest)
            except ArtifactValidationError as exc:
                artifact = {"valid": False, "status": "invalid", "errors": [str(exc)]}
                compatibility = {"valid": False, "status": "not_checked", "errors": ["artifact manifest invalid"]}
                replay = {"valid": False, "status": "not_checked", "errors": ["artifact manifest invalid"]}
            checks = {
                "artifact": artifact,
                "workload": compatibility,
                "replay": replay,
            }
            self.cp.update_model_checks(
                model_id,
                artifact_validation=artifact,
                workload_compatibility=compatibility,
            )
        valid = all(bool(check.get("valid")) for check in checks.values())
        gate = {
            "valid": valid,
            "status": "passed" if valid else "failed",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "workload_id": self.engine.workloads.active_id,
            "checks": checks,
        }
        if not valid:
            failures = []
            for name, check in checks.items():
                if not check.get("valid"):
                    failures.extend(f"{name}: {error}" for error in check.get("errors", ["failed"]))
            raise ValueError("model promotion gate failed: " + "; ".join(failures))
        return gate

    def _run_manifest_replay(self, manifest: TimberArtifactManifest) -> Dict[str, Any]:
        workload = self.engine.workloads.active()
        replay_engine = RuntimeEngine(
            model=TimberModelWrapper(manifest),
            policy=DecisionPolicy.from_workload(workload),
            audit_sink=InMemoryAuditSink(),
            store=InMemoryRuntimeStore(),
            workloads=self.engine.workloads,
        )
        summary = run_replay(replay_engine, workload.workload_id)
        errors = []
        if summary["count"] == 0:
            errors.append(f"no replay cases found for workload {workload.workload_id}")
        if summary["status"] != "passed":
            errors.append("replay cases failed")
        return {
            "valid": not errors,
            "status": "passed" if not errors else "failed",
            "errors": errors,
            "workload_id": workload.workload_id,
            "passed": summary["passed"],
            "failed": summary["failed"],
            "count": summary["count"],
            "results": summary["results"],
        }

    def _decorate_model(self, model: Dict[str, Any], base_url: str) -> Dict[str, Any]:
        response = dict(model)
        response["serving_endpoint"] = self._serving_endpoint(base_url, model=response)
        return response

    def _serving_endpoint(
        self,
        base_url: str,
        *,
        model_id: Optional[str] = None,
        model: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        active = self.cp.active_model()
        selected = dict(model) if model is not None else None
        if selected is None:
            selected = self.cp.model(model_id) if model_id else active

        is_champion = selected.get("model_id") == active.get("model_id") and selected.get("stage") == "champion"
        endpoint_url = f"{base_url}/v1/decision-requests" if is_champion else None
        return {
            "model_id": selected.get("model_id"),
            "model_version": selected.get("version"),
            "stage": selected.get("stage"),
            "status": "serving" if is_champion else "registered_not_serving",
            "url": endpoint_url,
            "endpoint_url": endpoint_url,
            "method": "POST",
            "content_type": "application/json",
            "contract": "decision_request.v1",
            "serving_mode": "governed_decision_runtime",
            "workload_id": self.engine.workloads.active_id,
            "health_url": f"{base_url}/v1/health",
            "workload_url": f"{base_url}/v1/workloads/active",
            "decision_lookup_url": f"{base_url}/v1/decision-requests/{{decision_request_id}}",
            "promotion_url": f"{base_url}/v1/models/{selected.get('model_id')}/promote",
            "notes": (
                "Applications should call this governed decision endpoint. The Timber artifact "
                "runs behind Tenta policy, audit, idempotency, workload validation, and rollback."
                if is_champion
                else "This model is registered but not the live champion. Promote it to champion to expose the app endpoint."
            ),
        }

    # ------------------------------------------------------------------
    def _live_latencies(self) -> List[float]:
        events = self.engine.decisions(limit=100).get("decisions", [])
        return [float(e.get("latency_ms", 0.0)) for e in events if e.get("latency_ms") is not None]

    def _overview(self) -> Dict[str, Any]:
        health = self.engine.health()
        summary = self.cp.summary()
        events = self.engine.decisions(limit=100).get("decisions", [])
        counts = {"allow": 0, "review": 0, "block": 0}
        latencies: List[float] = []
        for event in events:
            decision = event.get("decision")
            if decision in counts:
                counts[decision] += 1
            if event.get("latency_ms") is not None:
                latencies.append(float(event["latency_ms"]))
        total = sum(counts.values())
        block_rate = counts["block"] / total if total else 0.0
        review_rate = counts["review"] / total if total else 0.0
        ordered = sorted(latencies)
        latency = {
            "p50": round(_pct(ordered, 0.50), 3),
            "p95": round(_pct(ordered, 0.95), 3),
            "p99": round(_pct(ordered, 0.99), 3),
            "samples": len(ordered),
        }
        return {
            "health": health,
            "control_plane": self.cp.persistence_health(),
            "summary": summary,
            "runtime_controls": self.cp.runtime_controls(),
            "distribution": {**counts, "total": total,
                             "block_rate": round(block_rate, 4),
                             "review_rate": round(review_rate, 4)},
            "latency": latency,
            "recent": events[:8],
        }


def _pct(ordered: List[float], q: float) -> float:
    if not ordered:
        return 0.0
    idx = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return ordered[idx]


def _parse_limit(raw: str) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 50
