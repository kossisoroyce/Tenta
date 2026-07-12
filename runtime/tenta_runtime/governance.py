"""Role gates for mutating runtime/control-plane operations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Set


ROLE_ADMIN = "admin"
ROLE_MODEL_RISK = "model-risk"
ROLE_OPERATOR = "operator"
ROLE_ANALYST = "analyst"
ROLE_DETECTOR = "detector"
ROLE_SYSTEM = "system"

VALID_ROLES = {
    ROLE_ADMIN,
    ROLE_MODEL_RISK,
    ROLE_OPERATOR,
    ROLE_ANALYST,
    ROLE_DETECTOR,
    ROLE_SYSTEM,
}

PERMISSIONS: Dict[str, Set[str]] = {
    "database.provision": {ROLE_ADMIN, ROLE_MODEL_RISK},
    "database.connect": {ROLE_ADMIN, ROLE_MODEL_RISK},
    "workload.activate": {ROLE_ADMIN, ROLE_MODEL_RISK},
    "workload.import": {ROLE_ADMIN, ROLE_MODEL_RISK},
    "model.load": {ROLE_ADMIN, ROLE_MODEL_RISK},
    "model.register": {ROLE_ADMIN, ROLE_MODEL_RISK},
    "model.upload": {ROLE_ADMIN, ROLE_MODEL_RISK},
    "model.promote": {ROLE_ADMIN, ROLE_MODEL_RISK},
    "model.rollback": {ROLE_ADMIN, ROLE_MODEL_RISK},
    "healing.approve": {ROLE_ADMIN, ROLE_MODEL_RISK},
    "healing.reject": {ROLE_ADMIN, ROLE_MODEL_RISK},
    "healing.rollback": {ROLE_ADMIN, ROLE_MODEL_RISK},
    "drift.ingest": {ROLE_ADMIN, ROLE_MODEL_RISK, ROLE_DETECTOR},
    "drift.acknowledge": {ROLE_ADMIN, ROLE_MODEL_RISK, ROLE_OPERATOR},
    "drift.escalate": {ROLE_ADMIN, ROLE_MODEL_RISK, ROLE_OPERATOR},
    "feedback.record": {ROLE_ADMIN, ROLE_MODEL_RISK, ROLE_OPERATOR, ROLE_ANALYST},
}


class GovernanceError(PermissionError):
    def __init__(self, operation: str, role: str, actor: str, allowed_roles: Iterable[str]) -> None:
        self.operation = operation
        self.role = role
        self.actor = actor
        self.allowed_roles = sorted(allowed_roles)
        super().__init__(
            f"role '{role}' is not allowed to perform {operation}; "
            f"allowed roles: {', '.join(self.allowed_roles)}"
        )


@dataclass(frozen=True)
class ActorContext:
    actor: str
    role: str
    source: str = "api"
    request_id: str = ""
    reason: Optional[str] = None

    @classmethod
    def from_payload(
        cls,
        payload: Dict[str, Any],
        *,
        default_actor: str,
        default_role: Optional[str] = None,
        default_source: str = "api",
    ) -> "ActorContext":
        actor = str(payload.get("actor") or default_actor).strip() or default_actor
        role = normalize_role(str(payload.get("role") or default_role or infer_role(actor)))
        source = str(payload.get("source") or default_source).strip() or default_source
        request_id = str(payload.get("request_id") or uuid.uuid4()).strip()
        reason = payload.get("reason")
        return cls(
            actor=actor,
            role=role,
            source=source,
            request_id=request_id,
            reason=str(reason).strip() if reason else None,
        )

    def require(self, operation: str) -> None:
        allowed = PERMISSIONS.get(operation, {ROLE_ADMIN})
        if self.role not in allowed:
            raise GovernanceError(operation, self.role, self.actor, allowed)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "actor": self.actor,
            "role": self.role,
            "source": self.source,
            "request_id": self.request_id,
            "reason": self.reason,
        }


def normalize_role(role: str) -> str:
    normalized = role.strip().lower().replace("_", "-")
    if normalized == "modelrisk":
        normalized = ROLE_MODEL_RISK
    if normalized not in VALID_ROLES:
        return ROLE_OPERATOR
    return normalized


def infer_role(actor: str) -> str:
    lowered = actor.strip().lower()
    if not lowered:
        return ROLE_OPERATOR
    if "self-healing" in lowered or lowered.startswith("system") or lowered.startswith("policy-engine"):
        return ROLE_SYSTEM
    if "admin" in lowered:
        return ROLE_ADMIN
    if "detector" in lowered:
        return ROLE_DETECTOR
    if "analyst" in lowered:
        return ROLE_ANALYST
    if "model-risk" in lowered or "model_risk" in lowered or "risk" in lowered:
        return ROLE_MODEL_RISK
    # The current dashboard labels this operator as Model-risk in the top bar
    # while sending the actor string below.
    if lowered == "operator@console":
        return ROLE_MODEL_RISK
    return ROLE_OPERATOR
