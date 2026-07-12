"""Optional Postgres RuntimeStore backend."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .audit import DecisionEvent
from .storage import CachedDecision, RUNTIME_MIGRATION_COMPONENT, RUNTIME_SCHEMA_VERSION, _event_from_dict


class PostgresRuntimeStore:
    """Postgres-backed audit + idempotency store.

    This backend is optional so the default Python package remains self-contained.
    Install it with ``pip install tenta[postgres]``.
    """

    def __init__(self, dsn: str) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - depends on optional extra.
            raise RuntimeError("Postgres storage requires `pip install tenta[postgres]`.") from exc

        self.dsn = dsn
        self._lock = threading.RLock()
        self._connection = psycopg.connect(dsn, row_factory=dict_row)
        self._initialize()

    def get_cached_decision(self, transaction_id: str) -> Optional[CachedDecision]:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT transaction_id, fingerprint, response_json, created_at
                    FROM idempotency_keys
                    WHERE transaction_id = %s
                    """,
                    (transaction_id,),
                )
                row = cursor.fetchone()

        if row is None:
            return None
        return CachedDecision(
            transaction_id=row["transaction_id"],
            fingerprint=row["fingerprint"],
            response=_decode_json(row["response_json"]),
            created_at=_coerce_datetime(row["created_at"]),
        )

    def record_decision(self, transaction_id: str, fingerprint: str, response: Dict[str, Any], event: DecisionEvent) -> DecisionEvent:
        response_json = json.dumps(response, sort_keys=True, separators=(",", ":"))
        created_at = datetime.now(timezone.utc).isoformat()

        with self._lock:
            with self._connection.transaction():
                with self._connection.cursor() as cursor:
                    previous_hash = self._latest_event_hash(cursor)
                    event = event.with_integrity(previous_hash)
                    event_json = json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"))
                    reason_codes_json = json.dumps(event.reason_codes, sort_keys=True, separators=(",", ":"))
                    cursor.execute(
                        """
                        INSERT INTO idempotency_keys (transaction_id, fingerprint, response_json, created_at)
                        VALUES (%s, %s, %s::jsonb, %s)
                        ON CONFLICT(transaction_id) DO UPDATE SET
                          fingerprint = EXCLUDED.fingerprint,
                          response_json = EXCLUDED.response_json
                        WHERE idempotency_keys.fingerprint = EXCLUDED.fingerprint
                        RETURNING transaction_id
                        """,
                        (transaction_id, fingerprint, response_json, created_at),
                    )
                    if cursor.fetchone() is None:
                        raise ValueError("transaction_id was already recorded with a different fingerprint")
                    cursor.execute(
                        """
                        INSERT INTO decision_events (
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
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s::jsonb, %s)
                        ON CONFLICT(id) DO NOTHING
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
                            event.degraded_mode,
                            event.previous_hash,
                            event.event_hash,
                            event_json,
                            event.created_at,
                        ),
                    )
        return event

    def get_decision(self, transaction_id: str) -> Optional[DecisionEvent]:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT event_json
                    FROM decision_events
                    WHERE transaction_id = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    """,
                    (transaction_id,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return _event_from_dict(_decode_json(row["event_json"]))

    def list_decisions(self, limit: int = 25) -> List[DecisionEvent]:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT event_json
                    FROM decision_events
                    ORDER BY created_at DESC, id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [_event_from_dict(_decode_json(row["event_json"])) for row in rows]

    def count_cached_decisions(self) -> int:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS count FROM idempotency_keys")
                row = cursor.fetchone()
        return int(row["count"])

    def health(self) -> Dict[str, Any]:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS count FROM idempotency_keys")
                cache_count = int(cursor.fetchone()["count"])
                cursor.execute("SELECT COUNT(*) AS count FROM decision_events")
                event_count = int(cursor.fetchone()["count"])
        return {
            "status": "healthy",
            "backend": "postgres",
            "dsn": _redact_dsn(self.dsn),
            "schema_version": self._schema_version(),
            "cached_decisions": cache_count,
            "decision_events": event_count,
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
                        CREATE TABLE IF NOT EXISTS idempotency_keys (
                          transaction_id TEXT PRIMARY KEY,
                          fingerprint TEXT NOT NULL,
                          response_json JSONB NOT NULL,
                          created_at TIMESTAMPTZ NOT NULL
                        )
                        """
                    )
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS decision_events (
                          id TEXT PRIMARY KEY,
                          transaction_id TEXT NOT NULL,
                          event_time TEXT NOT NULL,
                          model_id TEXT NOT NULL,
                          model_version TEXT NOT NULL,
                          policy_version TEXT NOT NULL,
                          score DOUBLE PRECISION NOT NULL,
                          decision TEXT NOT NULL,
                          reason_codes_json JSONB NOT NULL,
                          latency_ms DOUBLE PRECISION NOT NULL,
                          degraded_mode BOOLEAN NOT NULL,
                          previous_hash TEXT,
                          event_hash TEXT,
                          event_json JSONB NOT NULL,
                          created_at TIMESTAMPTZ NOT NULL
                        )
                        """
                    )
                    cursor.execute("ALTER TABLE decision_events ADD COLUMN IF NOT EXISTS previous_hash TEXT")
                    cursor.execute("ALTER TABLE decision_events ADD COLUMN IF NOT EXISTS event_hash TEXT")
                    cursor.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_decision_events_transaction_id
                        ON decision_events(transaction_id)
                        """
                    )
                    cursor.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_decision_events_created_at
                        ON decision_events(created_at)
                        """
                    )
                    cursor.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_decision_events_event_hash
                        ON decision_events(event_hash)
                        """
                    )
                    cursor.execute(
                        """
                        INSERT INTO schema_migrations (component, version, applied_at)
                        VALUES (%s, %s, %s)
                        ON CONFLICT(component, version) DO NOTHING
                        """,
                        (RUNTIME_MIGRATION_COMPONENT, RUNTIME_SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
                    )

    def _latest_event_hash(self, cursor: Any) -> Optional[str]:
        cursor.execute(
            """
            SELECT event_hash
            FROM decision_events
            WHERE event_hash IS NOT NULL
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return row["event_hash"]

    def _schema_version(self) -> int:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT MAX(version) AS version
                    FROM schema_migrations
                    WHERE component = %s
                    """,
                    (RUNTIME_MIGRATION_COMPONENT,),
                )
                row = cursor.fetchone()
        return int(row["version"] or 0)


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
