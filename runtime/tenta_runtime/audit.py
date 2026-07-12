"""Structured audit events for runtime decisions."""

from __future__ import annotations

import json
import os
import hashlib
import threading
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Protocol


@dataclass(frozen=True)
class DecisionEvent:
    transaction_id: str
    event_time: str
    model_id: str
    model_version: str
    policy_version: str
    score: float
    decision: str
    reason_codes: List[str]
    latency_ms: float
    degraded_mode: bool = False
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    previous_hash: Optional[str] = None
    event_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "transaction_id": self.transaction_id,
            "event_time": self.event_time,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "policy_version": self.policy_version,
            "score": self.score,
            "decision": self.decision,
            "reason_codes": list(self.reason_codes),
            "latency_ms": self.latency_ms,
            "degraded_mode": self.degraded_mode,
            "created_at": self.created_at,
            "previous_hash": self.previous_hash,
            "event_hash": self.event_hash,
        }

    def with_integrity(self, previous_hash: Optional[str]) -> "DecisionEvent":
        event_with_previous = replace(self, previous_hash=previous_hash, event_hash=None)
        payload = event_with_previous.to_dict()
        payload.pop("event_hash", None)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        event_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        return replace(event_with_previous, event_hash=event_hash)


class AuditSink(Protocol):
    def append(self, event: DecisionEvent) -> None:
        ...

    def health(self) -> Dict[str, Any]:
        ...


class InMemoryAuditSink:
    """Thread-safe audit sink for local tests and development."""

    def __init__(self) -> None:
        self._events: List[DecisionEvent] = []
        self._lock = threading.RLock()

    def append(self, event: DecisionEvent) -> None:
        with self._lock:
            self._events.append(event)

    def list_events(self) -> List[DecisionEvent]:
        with self._lock:
            return list(self._events)

    def health(self) -> Dict[str, Any]:
        with self._lock:
            count = len(self._events)
        return {"status": "healthy", "sink": "memory", "events_written": count}


class JsonlAuditSink:
    """Append-only JSONL audit sink for local runtime operation."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()

    def append(self, event: DecisionEvent) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        if directory:
            os.makedirs(directory, exist_ok=True)

        line = json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"))
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as audit_file:
                audit_file.write(line + "\n")

    def health(self) -> Dict[str, Any]:
        return {"status": "healthy", "sink": "jsonl", "path": self.path}


class CompositeAuditSink:
    """Fan out decision events to multiple sinks."""

    def __init__(self, sinks: Iterable[AuditSink]) -> None:
        self._sinks = list(sinks)

    def append(self, event: DecisionEvent) -> None:
        for sink in self._sinks:
            sink.append(event)

    def health(self) -> Dict[str, Any]:
        statuses = [sink.health() for sink in self._sinks]
        overall = "healthy" if all(item.get("status") == "healthy" for item in statuses) else "degraded"
        return {"status": overall, "sinks": statuses}
