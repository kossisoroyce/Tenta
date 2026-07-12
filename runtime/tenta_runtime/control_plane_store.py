"""Persistence backends for control-plane operational state."""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol

from .operations import OperationEvent, operation_from_dict
from .storage import DEFAULT_STORAGE_URL


CONTROL_PLANE_NAMESPACE = "default"
CONTROL_PLANE_SCHEMA_VERSION = 2
CONTROL_PLANE_MIGRATION_COMPONENT = "control_plane"


class ControlPlaneStore(Protocol):
    def load(self) -> Optional[Dict[str, Any]]:
        ...

    def save(self, snapshot: Dict[str, Any]) -> None:
        ...

    def record_operation(self, event: OperationEvent) -> OperationEvent:
        ...

    def list_operations(self, limit: int = 50) -> List[OperationEvent]:
        ...

    def health(self) -> Dict[str, Any]:
        ...


class InMemoryControlPlaneStore:
    def __init__(self) -> None:
        self._snapshot: Optional[Dict[str, Any]] = None
        self._operations: List[OperationEvent] = []
        self._lock = threading.RLock()

    def load(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._snapshot)

    def save(self, snapshot: Dict[str, Any]) -> None:
        with self._lock:
            self._snapshot = copy.deepcopy(snapshot)

    def record_operation(self, event: OperationEvent) -> OperationEvent:
        with self._lock:
            previous_hash = self._operations[-1].event_hash if self._operations else None
            event = event.with_integrity(previous_hash)
            self._operations.append(event)
            self._operations = self._operations[-500:]
            return event

    def list_operations(self, limit: int = 50) -> List[OperationEvent]:
        with self._lock:
            return list(reversed(self._operations[-limit:]))

    def health(self) -> Dict[str, Any]:
        with self._lock:
            has_snapshot = self._snapshot is not None
            operation_events = len(self._operations)
        return {
            "status": "healthy",
            "backend": "memory",
            "schema_version": CONTROL_PLANE_SCHEMA_VERSION,
            "has_snapshot": has_snapshot,
            "operation_events": operation_events,
        }


class SQLiteControlPlaneStore:
    def __init__(self, path: str, namespace: str = CONTROL_PLANE_NAMESPACE) -> None:
        self.path = path
        self.namespace = namespace
        self._lock = threading.RLock()
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def load(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT payload_json
                FROM control_plane_snapshots
                WHERE namespace = ?
                """,
                (self.namespace,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload_json"])

    def save(self, snapshot: Dict[str, Any]) -> None:
        payload_json = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
        updated_at = _now()
        with self._lock:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO control_plane_snapshots (namespace, payload_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(namespace) DO UPDATE SET
                      payload_json = excluded.payload_json,
                      updated_at = excluded.updated_at
                    """,
                    (self.namespace, payload_json, updated_at),
                )

    def record_operation(self, event: OperationEvent) -> OperationEvent:
        with self._lock:
            with self._connection:
                previous_hash = self._latest_operation_hash()
                event = event.with_integrity(previous_hash)
                event_json = json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"))
                request_json = json.dumps(event.request, sort_keys=True, separators=(",", ":"))
                result_json = json.dumps(event.result, sort_keys=True, separators=(",", ":"))
                self._connection.execute(
                    """
                    INSERT INTO operation_events (
                      id,
                      operation_type,
                      actor,
                      target,
                      status,
                      request_json,
                      result_json,
                      message,
                      previous_hash,
                      event_hash,
                      event_json,
                      created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.id,
                        event.operation_type,
                        event.actor,
                        event.target,
                        event.status,
                        request_json,
                        result_json,
                        event.message,
                        event.previous_hash,
                        event.event_hash,
                        event_json,
                        event.created_at,
                    ),
                )
        return event

    def list_operations(self, limit: int = 50) -> List[OperationEvent]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT event_json
                FROM operation_events
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [operation_from_dict(json.loads(row["event_json"])) for row in rows]

    def health(self) -> Dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT updated_at
                FROM control_plane_snapshots
                WHERE namespace = ?
                """,
                (self.namespace,),
            ).fetchone()
            operation_row = self._connection.execute(
                "SELECT COUNT(*) AS count FROM operation_events"
            ).fetchone()
        return {
            "status": "healthy",
            "backend": "sqlite",
            "path": self.path,
            "namespace": self.namespace,
            "schema_version": self._schema_version(),
            "has_snapshot": row is not None,
            "updated_at": row["updated_at"] if row else None,
            "operation_events": int(operation_row["count"]),
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
                    CREATE TABLE IF NOT EXISTS control_plane_snapshots (
                      namespace TEXT PRIMARY KEY,
                      payload_json TEXT NOT NULL,
                      updated_at TEXT NOT NULL
                    )
                    """
                )
                self._connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS operation_events (
                      id TEXT PRIMARY KEY,
                      operation_type TEXT NOT NULL,
                      actor TEXT NOT NULL,
                      target TEXT,
                      status TEXT NOT NULL,
                      request_json TEXT NOT NULL,
                      result_json TEXT NOT NULL,
                      message TEXT,
                      previous_hash TEXT,
                      event_hash TEXT,
                      event_json TEXT NOT NULL,
                      created_at TEXT NOT NULL
                    )
                    """
                )
                self._connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_operation_events_created_at
                    ON operation_events(created_at)
                    """
                )
                self._connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_operation_events_target
                    ON operation_events(target)
                    """
                )
                self._connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_operation_events_event_hash
                    ON operation_events(event_hash)
                    """
                )
                self._connection.execute(
                    """
                    INSERT OR IGNORE INTO schema_migrations (component, version, applied_at)
                    VALUES (?, ?, ?)
                    """,
                    (CONTROL_PLANE_MIGRATION_COMPONENT, CONTROL_PLANE_SCHEMA_VERSION, _now()),
                )

    def _latest_operation_hash(self) -> Optional[str]:
        row = self._connection.execute(
            """
            SELECT event_hash
            FROM operation_events
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
            (CONTROL_PLANE_MIGRATION_COMPONENT,),
        ).fetchone()
        return int(row["version"] or 0)


class PostgresControlPlaneStore:
    def __init__(self, dsn: str, namespace: str = CONTROL_PLANE_NAMESPACE) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - depends on optional extra.
            raise RuntimeError("Postgres control-plane storage requires `pip install tenta[postgres]`.") from exc

        self.dsn = dsn
        self.namespace = namespace
        self._lock = threading.RLock()
        self._connection = psycopg.connect(dsn, row_factory=dict_row)
        self._initialize()

    def load(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT payload_json
                    FROM control_plane_snapshots
                    WHERE namespace = %s
                    """,
                    (self.namespace,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return _decode_json(row["payload_json"])

    def save(self, snapshot: Dict[str, Any]) -> None:
        payload_json = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
        updated_at = _now()
        with self._lock:
            with self._connection.transaction():
                with self._connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO control_plane_snapshots (namespace, payload_json, updated_at)
                        VALUES (%s, %s::jsonb, %s)
                        ON CONFLICT(namespace) DO UPDATE SET
                          payload_json = EXCLUDED.payload_json,
                          updated_at = EXCLUDED.updated_at
                        """,
                        (self.namespace, payload_json, updated_at),
                    )

    def record_operation(self, event: OperationEvent) -> OperationEvent:
        with self._lock:
            with self._connection.transaction():
                with self._connection.cursor() as cursor:
                    previous_hash = self._latest_operation_hash(cursor)
                    event = event.with_integrity(previous_hash)
                    event_json = json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"))
                    request_json = json.dumps(event.request, sort_keys=True, separators=(",", ":"))
                    result_json = json.dumps(event.result, sort_keys=True, separators=(",", ":"))
                    cursor.execute(
                        """
                        INSERT INTO operation_events (
                          id,
                          operation_type,
                          actor,
                          target,
                          status,
                          request_json,
                          result_json,
                          message,
                          previous_hash,
                          event_hash,
                          event_json,
                          created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s::jsonb, %s)
                        """,
                        (
                            event.id,
                            event.operation_type,
                            event.actor,
                            event.target,
                            event.status,
                            request_json,
                            result_json,
                            event.message,
                            event.previous_hash,
                            event.event_hash,
                            event_json,
                            event.created_at,
                        ),
                    )
        return event

    def list_operations(self, limit: int = 50) -> List[OperationEvent]:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT event_json
                    FROM operation_events
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [operation_from_dict(_decode_json(row["event_json"])) for row in rows]

    def health(self) -> Dict[str, Any]:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT updated_at
                    FROM control_plane_snapshots
                    WHERE namespace = %s
                    """,
                    (self.namespace,),
                )
                row = cursor.fetchone()
                cursor.execute("SELECT COUNT(*) AS count FROM operation_events")
                operation_count = int(cursor.fetchone()["count"])
        return {
            "status": "healthy",
            "backend": "postgres",
            "dsn": _redact_dsn(self.dsn),
            "namespace": self.namespace,
            "schema_version": self._schema_version(),
            "has_snapshot": row is not None,
            "updated_at": _coerce_datetime(row["updated_at"]) if row else None,
            "operation_events": operation_count,
        }

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _initialize(self) -> None:
        with self._lock:
            with self._connection.transaction():
                with self._connection.cursor() as cursor:
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS schema_migrations (
                          component TEXT NOT NULL,
                          version INTEGER NOT NULL,
                          applied_at TIMESTAMPTZ NOT NULL,
                          PRIMARY KEY(component, version)
                        )
                        """
                    )
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS control_plane_snapshots (
                          namespace TEXT PRIMARY KEY,
                          payload_json JSONB NOT NULL,
                          updated_at TIMESTAMPTZ NOT NULL
                        )
                        """
                    )
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS operation_events (
                          id TEXT PRIMARY KEY,
                          operation_type TEXT NOT NULL,
                          actor TEXT NOT NULL,
                          target TEXT,
                          status TEXT NOT NULL,
                          request_json JSONB NOT NULL,
                          result_json JSONB NOT NULL,
                          message TEXT,
                          previous_hash TEXT,
                          event_hash TEXT,
                          event_json JSONB NOT NULL,
                          created_at TIMESTAMPTZ NOT NULL
                        )
                        """
                    )
                    cursor.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_operation_events_created_at
                        ON operation_events(created_at)
                        """
                    )
                    cursor.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_operation_events_target
                        ON operation_events(target)
                        """
                    )
                    cursor.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_operation_events_event_hash
                        ON operation_events(event_hash)
                        """
                    )
                    cursor.execute(
                        """
                        INSERT INTO schema_migrations (component, version, applied_at)
                        VALUES (%s, %s, %s)
                        ON CONFLICT(component, version) DO NOTHING
                        """,
                        (CONTROL_PLANE_MIGRATION_COMPONENT, CONTROL_PLANE_SCHEMA_VERSION, _now()),
                    )

    def _schema_version(self) -> int:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT MAX(version) AS version
                    FROM schema_migrations
                    WHERE component = %s
                    """,
                    (CONTROL_PLANE_MIGRATION_COMPONENT,),
                )
                row = cursor.fetchone()
        return int(row["version"] or 0)

    def _latest_operation_hash(self, cursor: Any) -> Optional[str]:
        cursor.execute(
            """
            SELECT event_hash
            FROM operation_events
            WHERE event_hash IS NOT NULL
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return row["event_hash"]


def create_control_plane_store(storage_url: Optional[str] = None) -> ControlPlaneStore:
    resolved = (storage_url or DEFAULT_STORAGE_URL).strip()
    if resolved in {"memory", "memory://", ":memory:"}:
        return InMemoryControlPlaneStore()
    if resolved.startswith("sqlite:"):
        return SQLiteControlPlaneStore(_sqlite_path_from_url(resolved))
    if resolved.startswith("postgresql://") or resolved.startswith("postgres://"):
        return PostgresControlPlaneStore(resolved)
    raise ValueError(f"unsupported control-plane storage URL: {storage_url}")


def _sqlite_path_from_url(storage_url: str) -> str:
    raw = storage_url.removeprefix("sqlite:")
    if raw in {"", "///"}:
        return "data/tenta.sqlite3"
    if raw == "///:memory:":
        return ":memory:"
    if raw.startswith("///"):
        return raw[3:]
    if raw.startswith("//"):
        return raw[2:]
    return raw


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode_json(value: Any) -> Dict[str, Any]:
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _coerce_datetime(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _redact_dsn(dsn: str) -> str:
    if "@" not in dsn or "://" not in dsn:
        return dsn
    scheme, rest = dsn.split("://", 1)
    credentials, host = rest.split("@", 1)
    if ":" not in credentials:
        return dsn
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"
