"""Self-contained local authentication for the Tenta console and API keys."""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Protocol

from .governance import ROLE_ADMIN, normalize_role
from .storage import DEFAULT_STORAGE_URL


AUTH_COOKIE_NAME = "tenta_session"
AUTH_SCHEMA_VERSION = 1
AUTH_MIGRATION_COMPONENT = "auth"
DEFAULT_SESSION_TTL_HOURS = 12
API_KEY_PREFIX = "tenta_key"


class AuthError(ValueError):
    pass


class InvalidCredentials(AuthError):
    pass


@dataclass(frozen=True)
class AuthPrincipal:
    user_id: str
    email: str
    display_name: str
    role: str
    source: str = "session"
    session_id: Optional[str] = None
    api_key_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.user_id,
            "email": self.email,
            "display_name": self.display_name,
            "role": self.role,
            "source": self.source,
            "session_id": self.session_id,
            "api_key_id": self.api_key_id,
        }

    def actor_payload(self) -> Dict[str, str]:
        return {
            "actor": self.email,
            "role": self.role,
            "source": "api-key" if self.api_key_id else "console-session",
        }


class AuthStore(Protocol):
    def count_users(self) -> int:
        ...

    def create_user(self, user: Dict[str, Any]) -> Dict[str, Any]:
        ...

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        ...

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        ...

    def update_last_login(self, user_id: str, when: str) -> None:
        ...

    def create_session(self, session: Dict[str, Any]) -> Dict[str, Any]:
        ...

    def get_session(self, session_hash: str) -> Optional[Dict[str, Any]]:
        ...

    def delete_session(self, session_hash: str) -> None:
        ...

    def create_api_key(self, api_key: Dict[str, Any]) -> Dict[str, Any]:
        ...

    def get_api_key(self, key_hash: str) -> Optional[Dict[str, Any]]:
        ...

    def list_api_keys(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        ...

    def revoke_api_key(self, key_id: str, revoked_at: str) -> Optional[Dict[str, Any]]:
        ...

    def record_event(self, event: Dict[str, Any]) -> None:
        ...

    def health(self) -> Dict[str, Any]:
        ...


class InMemoryAuthStore:
    def __init__(self) -> None:
        self._users: Dict[str, Dict[str, Any]] = {}
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._api_keys: Dict[str, Dict[str, Any]] = {}
        self._events: List[Dict[str, Any]] = []
        self._lock = threading.RLock()

    def count_users(self) -> int:
        with self._lock:
            return len(self._users)

    def create_user(self, user: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            email = _normalize_email(user["email"])
            if any(existing["email"] == email for existing in self._users.values()):
                raise AuthError("user already exists")
            record = dict(user)
            record["email"] = email
            self._users[record["id"]] = record
            return copy.deepcopy(record)

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        normalized = _normalize_email(email)
        with self._lock:
            user = next((item for item in self._users.values() if item["email"] == normalized), None)
            return copy.deepcopy(user) if user else None

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            user = self._users.get(user_id)
            return copy.deepcopy(user) if user else None

    def update_last_login(self, user_id: str, when: str) -> None:
        with self._lock:
            if user_id in self._users:
                self._users[user_id]["last_login_at"] = when
                self._users[user_id]["updated_at"] = when

    def create_session(self, session: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._sessions[session["session_hash"]] = dict(session)
            return copy.deepcopy(session)

    def get_session(self, session_hash: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            session = self._sessions.get(session_hash)
            if not session:
                return None
            user = self._users.get(session["user_id"])
            if not user:
                return None
            return copy.deepcopy({**session, **user})

    def delete_session(self, session_hash: str) -> None:
        with self._lock:
            self._sessions.pop(session_hash, None)

    def create_api_key(self, api_key: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._api_keys[api_key["key_hash"]] = dict(api_key)
            return copy.deepcopy(api_key)

    def get_api_key(self, key_hash: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            key = self._api_keys.get(key_hash)
            if not key:
                return None
            user = self._users.get(key["user_id"])
            if not user:
                return None
            return copy.deepcopy({**key, "email": user["email"], "display_name": user["display_name"], "disabled": user.get("disabled", False)})

    def list_api_keys(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            keys = list(self._api_keys.values())
            if user_id:
                keys = [key for key in keys if key["user_id"] == user_id]
            return [copy.deepcopy(key) for key in keys]

    def revoke_api_key(self, key_id: str, revoked_at: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for key in self._api_keys.values():
                if key["id"] == key_id:
                    key["revoked_at"] = revoked_at
                    return copy.deepcopy(key)
        return None

    def record_event(self, event: Dict[str, Any]) -> None:
        with self._lock:
            self._events.append(dict(event))
            self._events = self._events[-500:]

    def health(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "status": "healthy",
                "backend": "memory",
                "schema_version": AUTH_SCHEMA_VERSION,
                "users": len(self._users),
                "sessions": len(self._sessions),
                "api_keys": len(self._api_keys),
            }


class SQLiteAuthStore:
    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()
        directory = os.path.dirname(os.path.abspath(path))
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def count_users(self) -> int:
        row = self._connection.execute("SELECT COUNT(*) AS count FROM auth_users").fetchone()
        return int(row["count"])

    def create_user(self, user: Dict[str, Any]) -> Dict[str, Any]:
        record = dict(user)
        record["email"] = _normalize_email(record["email"])
        with self._lock:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO auth_users (
                      id, email, display_name, role, password_hash, disabled,
                      created_at, updated_at, last_login_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["id"],
                        record["email"],
                        record["display_name"],
                        record["role"],
                        record["password_hash"],
                        1 if record.get("disabled") else 0,
                        record["created_at"],
                        record["updated_at"],
                        record.get("last_login_at"),
                    ),
                )
        return record

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        row = self._connection.execute(
            "SELECT * FROM auth_users WHERE email = ?",
            (_normalize_email(email),),
        ).fetchone()
        return _row_dict(row) if row else None

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        row = self._connection.execute("SELECT * FROM auth_users WHERE id = ?", (user_id,)).fetchone()
        return _row_dict(row) if row else None

    def update_last_login(self, user_id: str, when: str) -> None:
        with self._lock:
            with self._connection:
                self._connection.execute(
                    "UPDATE auth_users SET last_login_at = ?, updated_at = ? WHERE id = ?",
                    (when, when, user_id),
                )

    def create_session(self, session: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO auth_sessions (
                      session_hash, user_id, created_at, expires_at, last_seen_at, user_agent, ip_address
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session["session_hash"],
                        session["user_id"],
                        session["created_at"],
                        session["expires_at"],
                        session.get("last_seen_at"),
                        session.get("user_agent"),
                        session.get("ip_address"),
                    ),
                )
        return dict(session)

    def get_session(self, session_hash: str) -> Optional[Dict[str, Any]]:
        row = self._connection.execute(
            """
            SELECT auth_sessions.*, auth_users.email, auth_users.display_name, auth_users.role, auth_users.disabled
            FROM auth_sessions
            JOIN auth_users ON auth_users.id = auth_sessions.user_id
            WHERE auth_sessions.session_hash = ?
            """,
            (session_hash,),
        ).fetchone()
        return _row_dict(row) if row else None

    def delete_session(self, session_hash: str) -> None:
        with self._lock:
            with self._connection:
                self._connection.execute("DELETE FROM auth_sessions WHERE session_hash = ?", (session_hash,))

    def create_api_key(self, api_key: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO auth_api_keys (
                      id, key_prefix, key_hash, user_id, label, role,
                      created_at, expires_at, last_used_at, revoked_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        api_key["id"],
                        api_key["key_prefix"],
                        api_key["key_hash"],
                        api_key["user_id"],
                        api_key["label"],
                        api_key["role"],
                        api_key["created_at"],
                        api_key.get("expires_at"),
                        api_key.get("last_used_at"),
                        api_key.get("revoked_at"),
                    ),
                )
        return dict(api_key)

    def get_api_key(self, key_hash: str) -> Optional[Dict[str, Any]]:
        row = self._connection.execute(
            """
            SELECT auth_api_keys.*, auth_users.email, auth_users.display_name, auth_users.disabled
            FROM auth_api_keys
            JOIN auth_users ON auth_users.id = auth_api_keys.user_id
            WHERE auth_api_keys.key_hash = ?
            """,
            (key_hash,),
        ).fetchone()
        return _row_dict(row) if row else None

    def list_api_keys(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        query = """
            SELECT id, key_prefix, user_id, label, role, created_at, expires_at, last_used_at, revoked_at
            FROM auth_api_keys
        """
        params: tuple[Any, ...] = ()
        if user_id:
            query += " WHERE user_id = ?"
            params = (user_id,)
        query += " ORDER BY created_at DESC"
        rows = self._connection.execute(query, params).fetchall()
        return [_row_dict(row) for row in rows]

    def revoke_api_key(self, key_id: str, revoked_at: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self._connection:
                self._connection.execute(
                    "UPDATE auth_api_keys SET revoked_at = ? WHERE id = ?",
                    (revoked_at, key_id),
                )
        row = self._connection.execute("SELECT * FROM auth_api_keys WHERE id = ?", (key_id,)).fetchone()
        return _row_dict(row) if row else None

    def record_event(self, event: Dict[str, Any]) -> None:
        with self._lock:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO auth_events (
                      id, event_type, actor, user_id, status, ip_address, user_agent,
                      message, metadata_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event["id"],
                        event["event_type"],
                        event.get("actor"),
                        event.get("user_id"),
                        event["status"],
                        event.get("ip_address"),
                        event.get("user_agent"),
                        event.get("message"),
                        json.dumps(event.get("metadata") or {}, sort_keys=True, separators=(",", ":")),
                        event["created_at"],
                    ),
                )

    def health(self) -> Dict[str, Any]:
        users = self._connection.execute("SELECT COUNT(*) AS count FROM auth_users").fetchone()
        sessions = self._connection.execute("SELECT COUNT(*) AS count FROM auth_sessions").fetchone()
        api_keys = self._connection.execute("SELECT COUNT(*) AS count FROM auth_api_keys").fetchone()
        return {
            "status": "healthy",
            "backend": "sqlite",
            "path": self.path,
            "schema_version": self._schema_version(),
            "users": int(users["count"]),
            "sessions": int(sessions["count"]),
            "api_keys": int(api_keys["count"]),
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
                    CREATE TABLE IF NOT EXISTS auth_users (
                      id TEXT PRIMARY KEY,
                      email TEXT NOT NULL UNIQUE,
                      display_name TEXT NOT NULL,
                      role TEXT NOT NULL,
                      password_hash TEXT NOT NULL,
                      disabled INTEGER NOT NULL DEFAULT 0,
                      created_at TEXT NOT NULL,
                      updated_at TEXT NOT NULL,
                      last_login_at TEXT
                    )
                    """
                )
                self._connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS auth_sessions (
                      session_hash TEXT PRIMARY KEY,
                      user_id TEXT NOT NULL,
                      created_at TEXT NOT NULL,
                      expires_at TEXT NOT NULL,
                      last_seen_at TEXT,
                      user_agent TEXT,
                      ip_address TEXT,
                      FOREIGN KEY(user_id) REFERENCES auth_users(id)
                    )
                    """
                )
                self._connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS auth_api_keys (
                      id TEXT PRIMARY KEY,
                      key_prefix TEXT NOT NULL,
                      key_hash TEXT NOT NULL UNIQUE,
                      user_id TEXT NOT NULL,
                      label TEXT NOT NULL,
                      role TEXT NOT NULL,
                      created_at TEXT NOT NULL,
                      expires_at TEXT,
                      last_used_at TEXT,
                      revoked_at TEXT,
                      FOREIGN KEY(user_id) REFERENCES auth_users(id)
                    )
                    """
                )
                self._connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS auth_events (
                      id TEXT PRIMARY KEY,
                      event_type TEXT NOT NULL,
                      actor TEXT,
                      user_id TEXT,
                      status TEXT NOT NULL,
                      ip_address TEXT,
                      user_agent TEXT,
                      message TEXT,
                      metadata_json TEXT NOT NULL,
                      created_at TEXT NOT NULL
                    )
                    """
                )
                self._connection.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id)")
                self._connection.execute("CREATE INDEX IF NOT EXISTS idx_auth_api_keys_user ON auth_api_keys(user_id)")
                self._connection.execute("CREATE INDEX IF NOT EXISTS idx_auth_events_created_at ON auth_events(created_at)")
                self._connection.execute(
                    """
                    INSERT OR IGNORE INTO schema_migrations (component, version, applied_at)
                    VALUES (?, ?, ?)
                    """,
                    (AUTH_MIGRATION_COMPONENT, AUTH_SCHEMA_VERSION, _now()),
                )

    def _schema_version(self) -> int:
        row = self._connection.execute(
            """
            SELECT MAX(version) AS version
            FROM schema_migrations
            WHERE component = ?
            """,
            (AUTH_MIGRATION_COMPONENT,),
        ).fetchone()
        return int(row["version"] or 0)


class LocalAuthService:
    def __init__(self, store: Optional[AuthStore] = None, session_ttl_hours: int = DEFAULT_SESSION_TTL_HOURS) -> None:
        self.store: AuthStore = store or InMemoryAuthStore()
        self.session_ttl = timedelta(hours=session_ttl_hours)
        self._lock = threading.RLock()

    def replace_store(self, store: AuthStore) -> None:
        with self._lock:
            self.store = store

    def status(self) -> Dict[str, Any]:
        users = self.store.count_users()
        return {
            "enabled": True,
            "users_configured": users > 0,
            "needs_bootstrap": users == 0,
            "cookie_name": AUTH_COOKIE_NAME,
            "password_hasher": password_hasher_name(),
            "storage": self.store.health(),
        }

    def bootstrap(
        self,
        *,
        email: str,
        password: str,
        display_name: Optional[str] = None,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        if self.store.count_users() > 0:
            raise AuthError("auth has already been bootstrapped")
        user = self._create_user(
            email=email,
            password=password,
            display_name=display_name or "Administrator",
            role=ROLE_ADMIN,
        )
        session = self._create_session(user, user_agent=user_agent, ip_address=ip_address)
        self._record_event(
            "auth.bootstrap",
            actor=user["email"],
            user_id=user["id"],
            status="succeeded",
            user_agent=user_agent,
            ip_address=ip_address,
        )
        return {"user": _public_user(user), "session_token": session["token"], "expires_at": session["expires_at"]}

    def login(
        self,
        *,
        email: str,
        password: str,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        user = self.store.get_user_by_email(email)
        if user is None or user.get("disabled"):
            self._record_event("auth.login", actor=email, status="failed", user_agent=user_agent, ip_address=ip_address)
            raise InvalidCredentials("invalid email or password")
        if not verify_password(password, str(user["password_hash"])):
            self._record_event(
                "auth.login",
                actor=email,
                user_id=user["id"],
                status="failed",
                user_agent=user_agent,
                ip_address=ip_address,
            )
            raise InvalidCredentials("invalid email or password")
        now = _now()
        self.store.update_last_login(user["id"], now)
        user["last_login_at"] = now
        session = self._create_session(user, user_agent=user_agent, ip_address=ip_address)
        self._record_event(
            "auth.login",
            actor=user["email"],
            user_id=user["id"],
            status="succeeded",
            user_agent=user_agent,
            ip_address=ip_address,
        )
        return {"user": _public_user(user), "session_token": session["token"], "expires_at": session["expires_at"]}

    def logout(self, session_token: Optional[str], *, user_agent: Optional[str] = None, ip_address: Optional[str] = None) -> None:
        if not session_token:
            return
        session_hash = _token_hash(session_token)
        session = self.store.get_session(session_hash)
        self.store.delete_session(session_hash)
        self._record_event(
            "auth.logout",
            actor=session.get("email") if session else None,
            user_id=session.get("user_id") if session else None,
            status="succeeded",
            user_agent=user_agent,
            ip_address=ip_address,
        )

    def authenticate_session(self, session_token: Optional[str]) -> Optional[AuthPrincipal]:
        if not session_token:
            return None
        session = self.store.get_session(_token_hash(session_token))
        if session is None or _is_expired(session.get("expires_at")) or session.get("disabled"):
            return None
        return AuthPrincipal(
            user_id=session["user_id"],
            email=session["email"],
            display_name=session["display_name"],
            role=normalize_role(str(session["role"])),
            source="session",
            session_id=session["session_hash"],
        )

    def authenticate_api_key(self, token: Optional[str]) -> Optional[AuthPrincipal]:
        if not token:
            return None
        key = self.store.get_api_key(_token_hash(token))
        if key is None or key.get("revoked_at") or key.get("disabled") or _is_expired(key.get("expires_at")):
            return None
        return AuthPrincipal(
            user_id=key["user_id"],
            email=key["email"],
            display_name=key["display_name"],
            role=normalize_role(str(key["role"])),
            source="api-key",
            api_key_id=key["id"],
        )

    def create_api_key(
        self,
        principal: AuthPrincipal,
        *,
        label: str,
        role: Optional[str] = None,
        expires_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        token_secret = secrets.token_urlsafe(32)
        prefix = secrets.token_hex(4)
        token = f"{API_KEY_PREFIX}_{prefix}_{token_secret}"
        now = _now()
        requested_role = normalize_role(role or principal.role)
        if principal.role != ROLE_ADMIN and requested_role != principal.role:
            raise AuthError("only admins can mint API keys for a different role")
        api_key = {
            "id": _new_id("key"),
            "key_prefix": prefix,
            "key_hash": _token_hash(token),
            "user_id": principal.user_id,
            "label": label.strip() or "API key",
            "role": requested_role,
            "created_at": now,
            "expires_at": expires_at,
            "last_used_at": None,
            "revoked_at": None,
        }
        stored = self.store.create_api_key(api_key)
        self._record_event("auth.api_key.create", actor=principal.email, user_id=principal.user_id, status="succeeded")
        return {"api_key": _public_api_key(stored), "token": token}

    def list_api_keys(self, principal: AuthPrincipal) -> List[Dict[str, Any]]:
        return [_public_api_key(key) for key in self.store.list_api_keys(principal.user_id)]

    def revoke_api_key(self, principal: AuthPrincipal, key_id: str) -> Dict[str, Any]:
        key = self.store.revoke_api_key(key_id, _now())
        if key is None or key["user_id"] != principal.user_id:
            raise KeyError("api key not found")
        self._record_event("auth.api_key.revoke", actor=principal.email, user_id=principal.user_id, status="succeeded")
        return _public_api_key(key)

    def _create_user(self, *, email: str, password: str, display_name: str, role: str) -> Dict[str, Any]:
        email = _normalize_email(email)
        if "@" not in email:
            raise AuthError("email must be valid")
        if len(password) < 8:
            raise AuthError("password must be at least 8 characters")
        now = _now()
        user = {
            "id": _new_id("usr"),
            "email": email,
            "display_name": display_name.strip() or email,
            "role": normalize_role(role),
            "password_hash": hash_password(password),
            "disabled": False,
            "created_at": now,
            "updated_at": now,
            "last_login_at": None,
        }
        return self.store.create_user(user)

    def _create_session(
        self,
        user: Dict[str, Any],
        *,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> Dict[str, Any]:
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires_at = (now + self.session_ttl).isoformat()
        session = {
            "session_hash": _token_hash(token),
            "user_id": user["id"],
            "created_at": now.isoformat(),
            "expires_at": expires_at,
            "last_seen_at": now.isoformat(),
            "user_agent": user_agent,
            "ip_address": ip_address,
            "token": token,
        }
        self.store.create_session({key: value for key, value in session.items() if key != "token"})
        return session

    def _record_event(
        self,
        event_type: str,
        *,
        status: str,
        actor: Optional[str] = None,
        user_id: Optional[str] = None,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
        message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.store.record_event(
            {
                "id": _new_id("authevt"),
                "event_type": event_type,
                "actor": actor,
                "user_id": user_id,
                "status": status,
                "ip_address": ip_address,
                "user_agent": user_agent,
                "message": message,
                "metadata": metadata or {},
                "created_at": _now(),
            }
        )


def create_auth_store(storage_url: Optional[str] = None) -> AuthStore:
    resolved = (storage_url or DEFAULT_STORAGE_URL).strip()
    if resolved in {"memory", "memory://", ":memory:"}:
        return InMemoryAuthStore()
    if resolved.startswith("sqlite:"):
        return SQLiteAuthStore(_sqlite_path_from_url(resolved))
    if resolved.startswith("postgresql://") or resolved.startswith("postgres://"):
        return PostgresAuthStore(resolved)
    raise ValueError(f"unsupported auth storage URL: {storage_url}")


class PostgresAuthStore:
    def __init__(self, dsn: str) -> None:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - depends on optional extra.
            raise RuntimeError("Postgres auth storage requires `pip install tenta[postgres]`.") from exc

        self.dsn = dsn
        self._lock = threading.RLock()
        self._connection = psycopg.connect(dsn, row_factory=dict_row)
        self._initialize()

    def count_users(self) -> int:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS count FROM auth_users")
                return int(cursor.fetchone()["count"])

    def create_user(self, user: Dict[str, Any]) -> Dict[str, Any]:
        record = dict(user)
        record["email"] = _normalize_email(record["email"])
        with self._lock:
            with self._connection.transaction():
                with self._connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO auth_users (
                          id, email, display_name, role, password_hash, disabled,
                          created_at, updated_at, last_login_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            record["id"],
                            record["email"],
                            record["display_name"],
                            record["role"],
                            record["password_hash"],
                            bool(record.get("disabled")),
                            record["created_at"],
                            record["updated_at"],
                            record.get("last_login_at"),
                        ),
                    )
        return record

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute("SELECT * FROM auth_users WHERE email = %s", (_normalize_email(email),))
                row = cursor.fetchone()
        return _coerce_record(row) if row else None

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute("SELECT * FROM auth_users WHERE id = %s", (user_id,))
                row = cursor.fetchone()
        return _coerce_record(row) if row else None

    def update_last_login(self, user_id: str, when: str) -> None:
        with self._lock:
            with self._connection.transaction():
                with self._connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE auth_users SET last_login_at = %s, updated_at = %s WHERE id = %s",
                        (when, when, user_id),
                    )

    def create_session(self, session: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            with self._connection.transaction():
                with self._connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO auth_sessions (
                          session_hash, user_id, created_at, expires_at, last_seen_at, user_agent, ip_address
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            session["session_hash"],
                            session["user_id"],
                            session["created_at"],
                            session["expires_at"],
                            session.get("last_seen_at"),
                            session.get("user_agent"),
                            session.get("ip_address"),
                        ),
                    )
        return dict(session)

    def get_session(self, session_hash: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT auth_sessions.*, auth_users.email, auth_users.display_name, auth_users.role, auth_users.disabled
                    FROM auth_sessions
                    JOIN auth_users ON auth_users.id = auth_sessions.user_id
                    WHERE auth_sessions.session_hash = %s
                    """,
                    (session_hash,),
                )
                row = cursor.fetchone()
        return _coerce_record(row) if row else None

    def delete_session(self, session_hash: str) -> None:
        with self._lock:
            with self._connection.transaction():
                with self._connection.cursor() as cursor:
                    cursor.execute("DELETE FROM auth_sessions WHERE session_hash = %s", (session_hash,))

    def create_api_key(self, api_key: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            with self._connection.transaction():
                with self._connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO auth_api_keys (
                          id, key_prefix, key_hash, user_id, label, role,
                          created_at, expires_at, last_used_at, revoked_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            api_key["id"],
                            api_key["key_prefix"],
                            api_key["key_hash"],
                            api_key["user_id"],
                            api_key["label"],
                            api_key["role"],
                            api_key["created_at"],
                            api_key.get("expires_at"),
                            api_key.get("last_used_at"),
                            api_key.get("revoked_at"),
                        ),
                    )
        return dict(api_key)

    def get_api_key(self, key_hash: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT auth_api_keys.*, auth_users.email, auth_users.display_name, auth_users.disabled
                    FROM auth_api_keys
                    JOIN auth_users ON auth_users.id = auth_api_keys.user_id
                    WHERE auth_api_keys.key_hash = %s
                    """,
                    (key_hash,),
                )
                row = cursor.fetchone()
        return _coerce_record(row) if row else None

    def list_api_keys(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        query = """
            SELECT id, key_prefix, user_id, label, role, created_at, expires_at, last_used_at, revoked_at
            FROM auth_api_keys
        """
        params: tuple[Any, ...] = ()
        if user_id:
            query += " WHERE user_id = %s"
            params = (user_id,)
        query += " ORDER BY created_at DESC"
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
        return [_coerce_record(row) for row in rows]

    def revoke_api_key(self, key_id: str, revoked_at: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self._connection.transaction():
                with self._connection.cursor() as cursor:
                    cursor.execute("UPDATE auth_api_keys SET revoked_at = %s WHERE id = %s", (revoked_at, key_id))
            with self._connection.cursor() as cursor:
                cursor.execute("SELECT * FROM auth_api_keys WHERE id = %s", (key_id,))
                row = cursor.fetchone()
        return _coerce_record(row) if row else None

    def record_event(self, event: Dict[str, Any]) -> None:
        with self._lock:
            with self._connection.transaction():
                with self._connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO auth_events (
                          id, event_type, actor, user_id, status, ip_address, user_agent,
                          message, metadata_json, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                        """,
                        (
                            event["id"],
                            event["event_type"],
                            event.get("actor"),
                            event.get("user_id"),
                            event["status"],
                            event.get("ip_address"),
                            event.get("user_agent"),
                            event.get("message"),
                            json.dumps(event.get("metadata") or {}, sort_keys=True, separators=(",", ":")),
                            event["created_at"],
                        ),
                    )

    def health(self) -> Dict[str, Any]:
        with self._lock:
            with self._connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS count FROM auth_users")
                users = int(cursor.fetchone()["count"])
                cursor.execute("SELECT COUNT(*) AS count FROM auth_sessions")
                sessions = int(cursor.fetchone()["count"])
                cursor.execute("SELECT COUNT(*) AS count FROM auth_api_keys")
                api_keys = int(cursor.fetchone()["count"])
        return {
            "status": "healthy",
            "backend": "postgres",
            "dsn": _redact_dsn(self.dsn),
            "schema_version": self._schema_version(),
            "users": users,
            "sessions": sessions,
            "api_keys": api_keys,
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
                        CREATE TABLE IF NOT EXISTS auth_users (
                          id TEXT PRIMARY KEY,
                          email TEXT NOT NULL UNIQUE,
                          display_name TEXT NOT NULL,
                          role TEXT NOT NULL,
                          password_hash TEXT NOT NULL,
                          disabled BOOLEAN NOT NULL DEFAULT FALSE,
                          created_at TIMESTAMPTZ NOT NULL,
                          updated_at TIMESTAMPTZ NOT NULL,
                          last_login_at TIMESTAMPTZ
                        )
                        """
                    )
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS auth_sessions (
                          session_hash TEXT PRIMARY KEY,
                          user_id TEXT NOT NULL REFERENCES auth_users(id),
                          created_at TIMESTAMPTZ NOT NULL,
                          expires_at TIMESTAMPTZ NOT NULL,
                          last_seen_at TIMESTAMPTZ,
                          user_agent TEXT,
                          ip_address TEXT
                        )
                        """
                    )
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS auth_api_keys (
                          id TEXT PRIMARY KEY,
                          key_prefix TEXT NOT NULL,
                          key_hash TEXT NOT NULL UNIQUE,
                          user_id TEXT NOT NULL REFERENCES auth_users(id),
                          label TEXT NOT NULL,
                          role TEXT NOT NULL,
                          created_at TIMESTAMPTZ NOT NULL,
                          expires_at TIMESTAMPTZ,
                          last_used_at TIMESTAMPTZ,
                          revoked_at TIMESTAMPTZ
                        )
                        """
                    )
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS auth_events (
                          id TEXT PRIMARY KEY,
                          event_type TEXT NOT NULL,
                          actor TEXT,
                          user_id TEXT,
                          status TEXT NOT NULL,
                          ip_address TEXT,
                          user_agent TEXT,
                          message TEXT,
                          metadata_json JSONB NOT NULL,
                          created_at TIMESTAMPTZ NOT NULL
                        )
                        """
                    )
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_auth_api_keys_user ON auth_api_keys(user_id)")
                    cursor.execute("CREATE INDEX IF NOT EXISTS idx_auth_events_created_at ON auth_events(created_at)")
                    cursor.execute(
                        """
                        INSERT INTO schema_migrations (component, version, applied_at)
                        VALUES (%s, %s, %s)
                        ON CONFLICT(component, version) DO NOTHING
                        """,
                        (AUTH_MIGRATION_COMPONENT, AUTH_SCHEMA_VERSION, _now()),
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
                    (AUTH_MIGRATION_COMPONENT,),
                )
                row = cursor.fetchone()
        return int(row["version"] or 0)


# Not every CPython build ships OpenSSL with scrypt enabled; fall back to
# PBKDF2-HMAC-SHA256 (always available) so auth works on any interpreter.
_SCRYPT_AVAILABLE = hasattr(hashlib, "scrypt")
_PBKDF2_ITERATIONS = 600_000


def password_hasher_name() -> str:
    return "scrypt" if _SCRYPT_AVAILABLE else "pbkdf2_sha256"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    if _SCRYPT_AVAILABLE:
        n, r, p = 2 ** 14, 8, 1
        digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)
        return "scrypt${}${}${}${}${}".format(
            n,
            r,
            p,
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        )
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS, dklen=32)
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme = encoded.split("$", 1)[0]
        if scheme == "scrypt":
            if not _SCRYPT_AVAILABLE:
                return False
            _, raw_n, raw_r, raw_p, raw_salt, raw_digest = encoded.split("$", 5)
            salt = base64.b64decode(raw_salt.encode("ascii"))
            expected = base64.b64decode(raw_digest.encode("ascii"))
            digest = hashlib.scrypt(
                password.encode("utf-8"),
                salt=salt,
                n=int(raw_n),
                r=int(raw_r),
                p=int(raw_p),
                dklen=len(expected),
            )
            return hmac.compare_digest(digest, expected)
        if scheme == "pbkdf2_sha256":
            _, raw_iter, raw_salt, raw_digest = encoded.split("$", 3)
            salt = base64.b64decode(raw_salt.encode("ascii"))
            expected = base64.b64decode(raw_digest.encode("ascii"))
            digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(raw_iter), dklen=len(expected))
            return hmac.compare_digest(digest, expected)
        return False
    except Exception:
        return False


def _public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": user["id"],
        "email": user["email"],
        "display_name": user["display_name"],
        "role": normalize_role(str(user["role"])),
        "created_at": user.get("created_at"),
        "last_login_at": user.get("last_login_at"),
    }


def _public_api_key(key: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": key["id"],
        "key_prefix": key["key_prefix"],
        "label": key["label"],
        "role": normalize_role(str(key["role"])),
        "created_at": key.get("created_at"),
        "expires_at": key.get("expires_at"),
        "last_used_at": key.get("last_used_at"),
        "revoked_at": key.get("revoked_at"),
    }


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def _is_expired(iso: Optional[str]) -> bool:
    if not iso:
        return False
    try:
        value = datetime.fromisoformat(str(iso))
    except ValueError:
        return True
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_dict(row: sqlite3.Row) -> Dict[str, Any]:
    payload = dict(row)
    if "disabled" in payload:
        payload["disabled"] = bool(payload["disabled"])
    return payload


def _coerce_record(row: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(row)
    if "disabled" in payload:
        payload["disabled"] = bool(payload["disabled"])
    for key, value in list(payload.items()):
        if isinstance(value, datetime):
            payload[key] = value.isoformat()
    return payload


def _redact_dsn(dsn: str) -> str:
    if "@" not in dsn or "://" not in dsn:
        return dsn
    scheme, rest = dsn.split("://", 1)
    credentials, host = rest.split("@", 1)
    if ":" not in credentials:
        return dsn
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


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
