"""Operational audit events for control-plane mutations."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class OperationEvent:
    operation_type: str
    actor: str
    target: Optional[str] = None
    status: str = "succeeded"
    request: Dict[str, Any] = field(default_factory=dict)
    result: Dict[str, Any] = field(default_factory=dict)
    message: Optional[str] = None
    role: Optional[str] = None
    source: Optional[str] = None
    request_id: Optional[str] = None
    reason: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    previous_hash: Optional[str] = None
    event_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "operation_type": self.operation_type,
            "actor": self.actor,
            "target": self.target,
            "status": self.status,
            "request": dict(self.request),
            "result": dict(self.result),
            "message": self.message,
            "role": self.role,
            "source": self.source,
            "request_id": self.request_id,
            "reason": self.reason,
            "created_at": self.created_at,
            "previous_hash": self.previous_hash,
            "event_hash": self.event_hash,
        }

    def with_integrity(self, previous_hash: Optional[str]) -> "OperationEvent":
        event_with_previous = replace(self, previous_hash=previous_hash, event_hash=None)
        payload = event_with_previous.to_dict()
        payload.pop("event_hash", None)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        event_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return replace(event_with_previous, event_hash=event_hash)


def operation_from_dict(payload: Dict[str, Any]) -> OperationEvent:
    return OperationEvent(
        id=payload["id"],
        operation_type=payload["operation_type"],
        actor=payload["actor"],
        target=payload.get("target"),
        status=payload.get("status", "succeeded"),
        request=dict(payload.get("request") or {}),
        result=dict(payload.get("result") or {}),
        message=payload.get("message"),
        role=payload.get("role"),
        source=payload.get("source"),
        request_id=payload.get("request_id"),
        reason=payload.get("reason"),
        created_at=payload["created_at"],
        previous_hash=payload.get("previous_hash"),
        event_hash=payload.get("event_hash"),
    )
