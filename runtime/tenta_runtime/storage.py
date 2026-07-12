"""Storage contracts and embedded backends for runtime audit and memory."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol

from .audit import DecisionEvent


DEFAULT_SQLITE_PATH = "data/tenta.sqlite3"
DEFAULT_STORAGE_URL = f"sqlite:{DEFAULT_SQLITE_PATH}"
RUNTIME_SCHEMA_VERSION = 2
RUNTIME_MIGRATION_COMPONENT = "runtime"


@dataclass(frozen=True)
class CachedDecision:
    transaction_id: str
    fingerprint: str
    response: Dict[str, Any]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RuntimeStore(Protocol):
    """Audit + memory interface used by the scoring engine."""

    def get_cached_decision(self, transaction_id: str) -> Optional[CachedDecision]:
        ...

    def record_decision(self, transaction_id: str, fingerprint: str, response: Dict[str, Any], event: DecisionEvent) -> DecisionEvent:
        ...

    def get_decision(self, transaction_id: str) -> Optional[DecisionEvent]:
        ...

    def list_decisions(self, limit: int = 25) -> List[DecisionEvent]:
        ...

    def count_cached_decisions(self) -> int:
        ...

    def health(self) -> Dict[str, Any]:
        ...


class InMemoryRuntimeStore:
    """Thread-safe store for tests and ephemeral local runs."""

    def __init__(self) -> None:
        self._cache: Dict[str, CachedDecision] = {}
        self._events: List[DecisionEvent] = []
        self._lock = threading.RLock()

    def get_cached_decision(self, transaction_id: str) -> Optional[CachedDecision]:
        with self._lock:
            return self._cache.get(transaction_id)

    def record_decision(self, transaction_id: str, fingerprint: str, response: Dict[str, Any], event: DecisionEvent) -> DecisionEvent:
        with self._lock:
            previous_hash = self._events[-1].event_hash if self._events else None
            event = event.with_integrity(previous_hash)
            self._cache[transaction_id] = CachedDecision(
                transaction_id=transaction_id,
                fingerprint=fingerprint,
                response=dict(response),
            )
            self._events.append(event)
            self._events = self._events[-100:]
            return event

    def get_decision(self, transaction_id: str) -> Optional[DecisionEvent]:
        with self._lock:
            for event in reversed(self._events):
                if event.transaction_id == transaction_id:
                    return event
        return None

    def list_decisions(self, limit: int = 25) -> List[DecisionEvent]:
        with self._lock:
            return list(reversed(self._events[-limit:]))

    def count_cached_decisions(self) -> int:
        with self._lock:
            return len(self._cache)

    def health(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "status": "healthy",
                "backend": "memory",
                "schema_version": RUNTIME_SCHEMA_VERSION,
                "cached_decisions": len(self._cache),
                "decision_events": len(self._events),
            }


class SQLiteRuntimeStore:
    """Embedded persistent store for self-contained local runtime operation."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def get_cached_decision(self, transaction_id: str) -> Optional[CachedDecision]:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT transaction_id, fingerprint, response_json, created_at
                FROM idempotency_keys
                WHERE transaction_id = ?
                """,
                (transaction_id,),
            ).fetchone()

        if row is None:
            return None
        return CachedDecision(
            transaction_id=row["transaction_id"],
            fingerprint=row["fingerprint"],
            response=json.loads(row["response_json"]),
            created_at=row["created_at"],
        )

    def record_decision(self, transaction_id: str, fingerprint: str, response: Dict[str, Any], event: DecisionEvent) -> DecisionEvent:
        response_json = json.dumps(response, sort_keys=True, separators=(",", ":"))
        created_at = datetime.now(timezone.utc).isoformat()

        with self._lock:
            with self._connection:
                previous_hash = self._latest_event_hash()
                event = event.with_integrity(previous_hash)
                event_payload = event.to_dict()
                event_json = json.dumps(event_payload, sort_keys=True, separators=(",", ":"))
                reason_codes_json = json.dumps(event.reason_codes, sort_keys=True, separators=(",", ":"))
                cursor = self._connection.execute(
                    """
                    INSERT INTO idempotency_keys (transaction_id, fingerprint, response_json, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(transaction_id) DO UPDATE SET
                      fingerprint = excluded.fingerprint,
                      response_json = excluded.response_json
                    WHERE idempotency_keys.fingerprint = excluded.fingerprint
                    """,
                    (transaction_id, fingerprint, response_json, created_at),
                )
                if cursor.rowcount == 0:
                    raise ValueError("transaction_id was already recorded with a different fingerprint")
                self._connection.execute(
                    """
                    INSERT OR IGNORE INTO decision_events (
                      id,
                      transaction_id,
                      event_time,
                      model_id,
                      model_version,
                      policy_version,
                      score,
                      decision,
                      reason_codes_json,
                      latency_ms,
                      degraded_mode,
                      previous_hash,
                      event_hash,
                      event_json,
                      created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.id,
                        event.transaction_id,
                        event.event_time,
                        event.model_id,
                        event.model_version,
                        event.policy_version,
                        event.score,
                        event.decision,
                        reason_codes_json,
                        event.latency_ms,
                        1 if event.degraded_mode else 0,
                        event.previous_hash,
                        event.event_hash,
                        event_json,
                        event.created_at,
                    ),
                )
        return event

    def get_decision(self, transaction_id: str) -> Optional[DecisionEvent]:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT event_json
                FROM decision_events
                WHERE transaction_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (transaction_id,),
            ).fetchone()
        if row is None:
            return None
        return _event_from_dict(json.loads(row["event_json"]))

    def list_decisions(self, limit: int = 25) -> List[DecisionEvent]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT event_json
                FROM decision_events
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_event_from_dict(json.loads(row["event_json"])) for row in rows]

    def count_cached_decisions(self) -> int:
        with self._lock:
            row = self._connection.execute("SELECT COUNT(*) AS count FROM idempotency_keys").fetchone()
        return int(row["count"])

    def health(self) -> Dict[str, Any]:
        with self._lock:
            cache_count = self.count_cached_decisions()
            row = self._connection.execute("SELECT COUNT(*) AS count FROM decision_events").fetchone()
        return {
            "status": "healthy",
            "backend": "sqlite",
            "path": self.path,
            "schema_version": self._schema_version(),
            "cached_decisions": cache_count,
            "decision_events": int(row["count"]),
        }

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _initialize(self) -> None:
        with self._lock:
            with self._connection:
                self._connection.execute("PRAGMA journal_mode=WAL")
                self._connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                      component TEXT NOT NULL,
                      version INTEGER NOT NULL,
                      applied_at TEXT NOT NULL,
                      PRIMARY KEY(component, version)
                    )
                    """
                )
                self._connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS idempotency_keys (
                      transaction_id TEXT PRIMARY KEY,
                      fingerprint TEXT NOT NULL,
                      response_json TEXT NOT NULL,
                      created_at TEXT NOT NULL
                    )
                    """
                )
                self._connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS decision_events (
                      id TEXT PRIMARY KEY,
                      transaction_id TEXT NOT NULL,
                      event_time TEXT NOT NULL,
                      model_id TEXT NOT NULL,
                      model_version TEXT NOT NULL,
                      policy_version TEXT NOT NULL,
                      score REAL NOT NULL,
                      decision TEXT NOT NULL,
                      reason_codes_json TEXT NOT NULL,
                      latency_ms REAL NOT NULL,
                      degraded_mode INTEGER NOT NULL,
                      previous_hash TEXT,
                      event_hash TEXT,
                      event_json TEXT NOT NULL,
                      created_at TEXT NOT NULL
                    )
                    """
                )
                _sqlite_add_column_if_missing(self._connection, "decision_events", "previous_hash", "TEXT")
                _sqlite_add_column_if_missing(self._connection, "decision_events", "event_hash", "TEXT")
                self._connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_decision_events_transaction_id
                    ON decision_events(transaction_id)
                    """
                )
                self._connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_decision_events_created_at
                    ON decision_events(created_at)
                    """
                )
                self._connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_decision_events_event_hash
                    ON decision_events(event_hash)
                    """
                )
                self._mark_schema_version(RUNTIME_SCHEMA_VERSION)

    def _latest_event_hash(self) -> Optional[str]:
        row = self._connection.execute(
            """
            SELECT event_hash
            FROM decision_events
            WHERE event_hash IS NOT NULL
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        return row["event_hash"]

    def _schema_version(self) -> int:
        row = self._connection.execute(
            """
            SELECT MAX(version) AS version
            FROM schema_migrations
            WHERE component = ?
            """,
            (RUNTIME_MIGRATION_COMPONENT,),
        ).fetchone()
        return int(row["version"] or 0)

    def _mark_schema_version(self, version: int) -> None:
        self._connection.execute(
            """
            INSERT OR IGNORE INTO schema_migrations (component, version, applied_at)
            VALUES (?, ?, ?)
            """,
            (RUNTIME_MIGRATION_COMPONENT, version, datetime.now(timezone.utc).isoformat()),
        )


def create_runtime_store(storage_url: Optional[str] = None) -> RuntimeStore:
    """Create a RuntimeStore from a storage URL.

    Supported URLs:
    - ``memory`` or ``memory://``
    - ``sqlite:path/to/tenta.sqlite3``
    - ``sqlite:///:memory:``
    - ``postgresql://user:pass@host:5432/db`` or ``postgres://...``
    """

    resolved = (storage_url or DEFAULT_STORAGE_URL).strip()
    if resolved in {"memory", "memory://", ":memory:"}:
        return InMemoryRuntimeStore()
    if resolved.startswith("sqlite:"):
        return SQLiteRuntimeStore(_sqlite_path_from_url(resolved))
    if resolved.startswith("postgresql://") or resolved.startswith("postgres://"):
        from .storage_postgres import PostgresRuntimeStore

        return PostgresRuntimeStore(resolved)
    raise ValueError(f"unsupported storage URL: {storage_url}")


def storage_url_from_options(
    *,
    storage_url: Optional[str] = None,
    storage_path: Optional[str] = None,
    memory_storage: bool = False,
) -> str:
    if memory_storage:
        return "memory"
    if storage_url:
        return storage_url
    if storage_path:
        return f"sqlite:{storage_path}"
    return DEFAULT_STORAGE_URL


def _sqlite_path_from_url(storage_url: str) -> str:
    raw = storage_url.removeprefix("sqlite:")
    if raw in {"", "///"}:
        return DEFAULT_SQLITE_PATH
    if raw == "///:memory:":
        return ":memory:"
    if raw.startswith("///"):
        return raw[3:]
    if raw.startswith("//"):
        return raw[2:]
    return raw


def _event_from_dict(payload: Dict[str, Any]) -> DecisionEvent:
    return DecisionEvent(
        id=payload["id"],
        transaction_id=payload["transaction_id"],
        event_time=payload["event_time"],
        model_id=payload["model_id"],
        model_version=payload["model_version"],
        policy_version=payload["policy_version"],
        score=float(payload["score"]),
        decision=payload["decision"],
        reason_codes=list(payload.get("reason_codes", [])),
        latency_ms=float(payload["latency_ms"]),
        degraded_mode=bool(payload.get("degraded_mode", False)),
        created_at=payload["created_at"],
        previous_hash=payload.get("previous_hash"),
        event_hash=payload.get("event_hash"),
    )


def _sqlite_add_column_if_missing(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    columns = {row["name"] if isinstance(row, sqlite3.Row) else row[1] for row in rows}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
