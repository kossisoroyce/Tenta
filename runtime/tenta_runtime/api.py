"""Small stdlib HTTP API for the runtime service."""

from __future__ import annotations

import argparse
import json
import mimetypes
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, unquote, urlparse
from typing import Any, Dict, Optional, Type

from .audit import CompositeAuditSink, InMemoryAuditSink, JsonlAuditSink
from .auth import AUTH_COOKIE_NAME, AuthError, InvalidCredentials, LocalAuthService, create_auth_store
from .console_api import ConsoleRoutes
from .control_plane import ControlPlane, RegistryModelWrapper
from .control_plane_store import create_control_plane_store
from .database import (
    DEFAULT_POSTGRES_COMPOSE_FILE,
    DEFAULT_POSTGRES_SERVICE,
    DEFAULT_POSTGRES_STORAGE_URL,
    DatabaseProvisioner,
    default_storage_url_from_config,
    load_runtime_config,
)
from .engine import IdempotencyConflictError, RuntimeEngine
from .governance import ActorContext, GovernanceError
from .models import PayloadValidationError, RuleBasedModelWrapper
from .storage import DEFAULT_STORAGE_URL, create_runtime_store, storage_url_from_options
from .workloads import DEFAULT_USER_WORKLOAD_DIR, default_workload_registry


def create_default_engine(
    audit_path: Optional[str] = None,
    storage_url: Optional[str] = None,
    active_workload_id: Optional[str] = None,
) -> RuntimeEngine:
    memory_sink = InMemoryAuditSink()
    audit_sink = CompositeAuditSink([memory_sink, JsonlAuditSink(audit_path)]) if audit_path else memory_sink
    store = create_runtime_store(storage_url or default_storage_url_from_config())
    config = load_runtime_config()
    workload_id = active_workload_id or config.active_workload_id
    return RuntimeEngine(
        model=RuleBasedModelWrapper(),
        audit_sink=audit_sink,
        store=store,
        workloads=default_workload_registry(active_id=workload_id, user_workload_dir=DEFAULT_USER_WORKLOAD_DIR),
    )


def default_static_dir() -> Path:
    # The dashboard is a Vite/React app; the runtime serves its production build.
    # Run `pnpm build` in `dashboard/` to (re)generate this directory.
    return Path(__file__).resolve().parents[2] / "dashboard" / "dist"


def make_handler(
    engine: RuntimeEngine,
    static_dir: Optional[Path] = None,
    console: Optional[ConsoleRoutes] = None,
    database: Optional[DatabaseProvisioner] = None,
    auth: Optional[LocalAuthService] = None,
) -> Type[BaseHTTPRequestHandler]:
    dashboard_dir = Path(static_dir) if static_dir is not None else default_static_dir()

    class RuntimeRequestHandler(BaseHTTPRequestHandler):
        server_version = "TentaRuntime/0.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)

            if auth is not None and parsed.path.startswith("/v1/auth"):
                self._handle_auth_get(parsed)
                return

            auth_principal = self._auth_principal() if auth is not None else None
            if self._requires_auth("GET", parsed.path) and auth_principal is None:
                self._send_json(401, {"error": "unauthorized", "message": "authentication required"})
                return

            if console is not None:
                result = console.dispatch(
                    "GET",
                    parsed.path,
                    None,
                    parse_qs(parsed.query),
                    request_context={"base_url": self._request_base_url(), "auth_principal": _principal_payload(auth_principal)},
                )
                if result is not None:
                    self._send_json(result[0], result[1])
                    return

            if parsed.path == "/v1/health":
                self._send_json(200, engine.health())
                return
            if parsed.path == "/v1/database/status":
                if database is None:
                    self._send_json(500, {"error": "database_unavailable", "message": "database provisioner is not configured"})
                    return
                self._send_json(200, database.status())
                return
            if parsed.path == "/v1/decisions":
                query = parse_qs(parsed.query)
                limit = _parse_limit(query.get("limit", ["25"])[0])
                self._send_json(200, engine.decisions(limit=limit))
                return
            if parsed.path == "/v1/decision-events":
                query = parse_qs(parsed.query)
                limit = _parse_limit(query.get("limit", ["25"])[0])
                self._send_json(200, _decision_events_payload(engine.decisions(limit=limit)))
                return
            if parsed.path.startswith("/v1/decision-requests/"):
                request_id = unquote(parsed.path.removeprefix("/v1/decision-requests/"))
                decision = engine.transaction(request_id)
                if decision is None:
                    self._send_json(404, {"error": "not_found", "message": "decision request not found"})
                    return
                self._send_json(200, _decision_aliases(decision))
                return
            if parsed.path.startswith("/v1/transactions/"):
                transaction_id = unquote(parsed.path.removeprefix("/v1/transactions/"))
                decision = engine.transaction(transaction_id)
                if decision is None:
                    self._send_json(404, {"error": "not_found", "message": "transaction decision not found"})
                    return
                self._send_json(200, decision)
                return
            if parsed.path in {"/", "/dashboard"} or parsed.path.startswith("/dashboard/"):
                self._serve_static(parsed.path)
                return
            self._send_json(404, {"error": "not_found", "message": "endpoint not found"})

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._send_common_headers("application/json", 0)
            self.end_headers()

        def do_POST(self) -> None:
            parsed = urlparse(self.path)

            try:
                payload = self._read_json_body()
            except json.JSONDecodeError:
                self._send_json(400, {"error": "invalid_json", "message": "request body must be valid JSON"})
                return
            except PayloadValidationError as exc:
                self._send_json(422, {"error": "validation_error", "message": str(exc)})
                return

            if auth is not None and parsed.path.startswith("/v1/auth"):
                self._handle_auth_post(parsed, payload)
                return

            auth_principal = self._auth_principal() if auth is not None else None
            if self._requires_auth("POST", parsed.path) and auth_principal is None:
                self._send_json(401, {"error": "unauthorized", "message": "authentication required"})
                return
            if auth_principal is not None:
                payload = {**payload, **auth_principal.actor_payload()}

            if console is not None:
                result = console.dispatch(
                    "POST",
                    parsed.path,
                    payload,
                    request_context={"base_url": self._request_base_url(), "auth_principal": _principal_payload(auth_principal)},
                )
                if result is not None:
                    self._send_json(result[0], result[1])
                    return

            if parsed.path == "/v1/database/provision":
                if database is None:
                    self._send_json(500, {"error": "database_unavailable", "message": "database provisioner is not configured"})
                    return
                try:
                    actor_context = _authorize_database(database, payload)
                    response = _provision_database(database, payload, actor_context)
                except GovernanceError as exc:
                    self._send_json(403, {
                        "error": "forbidden",
                        "message": str(exc),
                        "operation": exc.operation,
                        "role": exc.role,
                        "allowed_roles": exc.allowed_roles,
                    })
                    return
                except ValueError as exc:
                    self._send_json(422, {"error": "provision_error", "message": str(exc)})
                    return
                except RuntimeError as exc:
                    self._send_json(422, {"error": "provision_error", "message": str(exc)})
                    return
                self._send_json(200, response)
                return

            if parsed.path not in {"/v1/score", "/v1/decision-requests"}:
                self._send_json(404, {"error": "not_found", "message": "endpoint not found"})
                return

            try:
                response = engine.score(payload)
            except PayloadValidationError as exc:
                self._send_json(422, {"error": "validation_error", "message": str(exc)})
            except IdempotencyConflictError as exc:
                self._send_json(409, {"error": "idempotency_conflict", "message": str(exc)})
            except Exception as exc:  # pragma: no cover - defensive API boundary.
                self._send_json(500, {"error": "internal_error", "message": str(exc)})
            else:
                self._send_json(200, _decision_aliases(response))

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_json_body(self) -> Dict[str, Any]:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(content_length)
            payload = json.loads(raw.decode("utf-8") if raw else "{}")
            if not isinstance(payload, dict):
                raise PayloadValidationError("request body must be a JSON object")
            return payload

        def _handle_auth_get(self, parsed: Any) -> None:
            if auth is None:
                self._send_json(404, {"error": "not_found", "message": "auth is not configured"})
                return
            if parsed.path == "/v1/auth/status":
                self._send_json(200, auth.status())
                return
            if parsed.path == "/v1/auth/me":
                principal = self._auth_principal()
                if principal is None:
                    self._send_json(401, {"error": "unauthorized", "message": "authentication required"})
                    return
                self._send_json(200, {"user": principal.to_dict()})
                return
            if parsed.path == "/v1/auth/api-keys":
                principal = self._auth_principal()
                if principal is None:
                    self._send_json(401, {"error": "unauthorized", "message": "authentication required"})
                    return
                self._send_json(200, {"api_keys": auth.list_api_keys(principal)})
                return
            self._send_json(404, {"error": "not_found", "message": "auth endpoint not found"})

        def _handle_auth_post(self, parsed: Any, payload: Dict[str, Any]) -> None:
            if auth is None:
                self._send_json(404, {"error": "not_found", "message": "auth is not configured"})
                return
            try:
                if parsed.path == "/v1/auth/bootstrap":
                    result = auth.bootstrap(
                        email=str(payload.get("email") or ""),
                        password=str(payload.get("password") or ""),
                        display_name=str(payload.get("display_name") or "Administrator"),
                        user_agent=self.headers.get("User-Agent"),
                        ip_address=self.client_address[0],
                    )
                    self._send_json(200, {"user": result["user"]}, extra_headers=[self._session_cookie(result["session_token"])])
                    return
                if parsed.path == "/v1/auth/login":
                    result = auth.login(
                        email=str(payload.get("email") or ""),
                        password=str(payload.get("password") or ""),
                        user_agent=self.headers.get("User-Agent"),
                        ip_address=self.client_address[0],
                    )
                    self._send_json(200, {"user": result["user"]}, extra_headers=[self._session_cookie(result["session_token"])])
                    return
                if parsed.path == "/v1/auth/logout":
                    auth.logout(self._session_cookie_value(), user_agent=self.headers.get("User-Agent"), ip_address=self.client_address[0])
                    self._send_json(200, {"status": "logged_out"}, extra_headers=[self._expired_session_cookie()])
                    return
                if parsed.path == "/v1/auth/api-keys":
                    principal = self._auth_principal()
                    if principal is None:
                        self._send_json(401, {"error": "unauthorized", "message": "authentication required"})
                        return
                    result = auth.create_api_key(
                        principal,
                        label=str(payload.get("label") or "API key"),
                        role=str(payload.get("role") or principal.role),
                        expires_at=payload.get("expires_at"),
                    )
                    self._send_json(200, result)
                    return
                if parsed.path.startswith("/v1/auth/api-keys/") and parsed.path.endswith("/revoke"):
                    principal = self._auth_principal()
                    if principal is None:
                        self._send_json(401, {"error": "unauthorized", "message": "authentication required"})
                        return
                    key_id = unquote(parsed.path[len("/v1/auth/api-keys/"):-len("/revoke")])
                    self._send_json(200, {"api_key": auth.revoke_api_key(principal, key_id)})
                    return
            except InvalidCredentials as exc:
                self._send_json(401, {"error": "invalid_credentials", "message": str(exc)})
                return
            except AuthError as exc:
                self._send_json(422, {"error": "auth_error", "message": str(exc)})
                return
            except KeyError as exc:
                self._send_json(404, {"error": "not_found", "message": str(exc).strip("'")})
                return
            self._send_json(404, {"error": "not_found", "message": "auth endpoint not found"})

        def _send_json(self, status: int, payload: Dict[str, Any], extra_headers: Optional[list[tuple[str, str]]] = None) -> None:
            encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self._send_common_headers("application/json", len(encoded))
            for key, value in extra_headers or []:
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(encoded)

        def _serve_static(self, request_path: str) -> None:
            relative_path = request_path.removeprefix("/dashboard/").strip("/")
            if request_path in {"/", "/dashboard"} or not relative_path:
                relative_path = "index.html"

            candidate = (dashboard_dir / relative_path).resolve()
            try:
                candidate.relative_to(dashboard_dir.resolve())
            except ValueError:
                self._send_json(403, {"error": "forbidden", "message": "invalid dashboard path"})
                return

            if not candidate.is_file():
                self._send_json(404, {"error": "not_found", "message": "dashboard asset not found"})
                return

            content = candidate.read_bytes()
            content_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
            self.send_response(200)
            self._send_common_headers(content_type, len(content))
            self.end_headers()
            self.wfile.write(content)

        def _send_common_headers(self, content_type: str, content_length: int) -> None:
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(content_length))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

        def _requires_auth(self, method: str, path: str) -> bool:
            if auth is None or not auth.status()["users_configured"]:
                return False
            if path.startswith("/v1/auth"):
                return False
            if path in {"/v1/health", "/v1/serving-endpoint"}:
                return False
            if method == "POST" and path in {"/v1/score", "/v1/decision-requests"}:
                return False
            return path.startswith("/v1/")

        def _auth_principal(self) -> Any:
            if auth is None:
                return None
            bearer = self._bearer_token()
            if bearer:
                principal = auth.authenticate_api_key(bearer)
                if principal is not None:
                    return principal
            return auth.authenticate_session(self._session_cookie_value())

        def _bearer_token(self) -> Optional[str]:
            header = self.headers.get("Authorization") or ""
            if not header.lower().startswith("bearer "):
                return None
            return header.split(" ", 1)[1].strip()

        def _session_cookie_value(self) -> Optional[str]:
            raw = self.headers.get("Cookie")
            if not raw:
                return None
            cookie = SimpleCookie()
            cookie.load(raw)
            morsel = cookie.get(AUTH_COOKIE_NAME)
            return morsel.value if morsel else None

        def _session_cookie(self, token: str) -> tuple[str, str]:
            secure = "; Secure" if self._request_base_url().startswith("https://") else ""
            return (
                "Set-Cookie",
                f"{AUTH_COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={12 * 60 * 60}{secure}",
            )

        def _expired_session_cookie(self) -> tuple[str, str]:
            return (
                "Set-Cookie",
                f"{AUTH_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
            )

        def _request_base_url(self) -> str:
            proto = (self.headers.get("X-Forwarded-Proto") or "http").split(",")[0].strip() or "http"
            host = (
                self.headers.get("X-Forwarded-Host")
                or self.headers.get("Host")
                or f"{self.server.server_address[0]}:{self.server.server_address[1]}"
            )
            host = host.split(",")[0].strip()
            return f"{proto}://{host}"

    return RuntimeRequestHandler


def _parse_limit(raw: str) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 25


def _decision_aliases(payload: Dict[str, Any]) -> Dict[str, Any]:
    response = dict(payload)
    if response.get("transaction_id") and not response.get("decision_request_id"):
        response["decision_request_id"] = response["transaction_id"]
    return response


def _decision_events_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    response = dict(payload)
    response["decisions"] = [_decision_aliases(event) for event in payload.get("decisions", [])]
    return response


def _provision_database(
    database: DatabaseProvisioner,
    payload: Dict[str, Any],
    actor_context: ActorContext,
) -> Dict[str, Any]:
    backend = str(payload.get("backend") or "").lower().strip()
    persist = bool(payload.get("persist", True))
    metadata = {
        "actor": actor_context.actor,
        "role": actor_context.role,
        "source": actor_context.source,
        "request_id": actor_context.request_id,
        "reason": actor_context.reason,
    }
    if backend == "sqlite":
        path = str(payload.get("path") or DEFAULT_STORAGE_URL.removeprefix("sqlite:"))
        return database.provision_sqlite(path=path, persist=persist, **metadata)
    if backend in {"postgres", "postgresql"}:
        storage_url = str(payload.get("storage_url") or payload.get("dsn") or DEFAULT_POSTGRES_STORAGE_URL).strip()
        if not (storage_url.startswith("postgresql://") or storage_url.startswith("postgres://")):
            raise ValueError("postgres storage_url must start with postgresql:// or postgres://")
        return database.provision_postgres(
            storage_url=storage_url,
            persist=persist,
            compose_file=str(payload.get("compose_file") or DEFAULT_POSTGRES_COMPOSE_FILE),
            service=str(payload.get("service") or DEFAULT_POSTGRES_SERVICE),
            start=bool(payload.get("start", True)),
            wait=bool(payload.get("wait", True)),
            **metadata,
        )
    if payload.get("storage_url"):
        return database.connect(storage_url=str(payload["storage_url"]), persist=persist, **metadata)
    raise ValueError("backend must be sqlite or postgres")


def _principal_payload(principal: Any) -> Optional[Dict[str, Any]]:
    return principal.to_dict() if principal is not None else None


def _authorize_database(database: DatabaseProvisioner, payload: Dict[str, Any]) -> ActorContext:
    operation = _database_operation(payload)
    actor_context = ActorContext.from_payload(
        payload,
        default_actor="admin@database",
        default_source="database",
    )
    try:
        actor_context.require(operation)
    except GovernanceError as exc:
        control_plane = database.control_plane
        if control_plane is not None:
            control_plane.record_operation(
                "governance.denied",
                actor_context.actor,
                target=str(payload.get("backend") or payload.get("storage_url") or "database"),
                status="denied",
                request={
                    "operation": operation,
                    "backend": payload.get("backend"),
                    "storage_url": _redact_storage_url(str(payload.get("storage_url") or payload.get("dsn") or "")),
                    **actor_context.to_dict(),
                },
                result={"allowed_roles": exc.allowed_roles},
                message=str(exc),
                role=actor_context.role,
                source=actor_context.source,
                request_id=actor_context.request_id,
                reason=actor_context.reason,
            )
        raise
    return actor_context


def _database_operation(payload: Dict[str, Any]) -> str:
    backend = str(payload.get("backend") or "").lower().strip()
    if backend in {"sqlite", "postgres", "postgresql"}:
        return "database.provision"
    return "database.connect"


def _redact_storage_url(storage_url: str) -> str:
    if not (storage_url.startswith("postgresql://") or storage_url.startswith("postgres://")):
        return storage_url
    if "@" not in storage_url or "://" not in storage_url:
        return storage_url
    scheme, rest = storage_url.split("://", 1)
    credentials, host = rest.split("@", 1)
    if ":" not in credentials:
        return storage_url
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


def run(
    host: str = "127.0.0.1",
    port: int = 8080,
    audit_path: Optional[str] = None,
    storage_url: Optional[str] = None,
) -> None:
    config = load_runtime_config()
    resolved_storage_url = storage_url or config.storage_url
    engine = create_default_engine(
        audit_path=audit_path,
        storage_url=resolved_storage_url,
        active_workload_id=config.active_workload_id,
    )
    control_plane = ControlPlane(store=create_control_plane_store(resolved_storage_url))
    auth_service = LocalAuthService(create_auth_store(resolved_storage_url))
    # The live scorer tracks the control plane's champion so model promotion
    # actually changes production scoring.
    engine.model = RegistryModelWrapper(control_plane)
    console = ConsoleRoutes(
        engine,
        control_plane,
        config_path="data/tenta-runtime.json",
        workload_dir=DEFAULT_USER_WORKLOAD_DIR,
    )
    database = DatabaseProvisioner(engine, control_plane=control_plane, auth=auth_service)
    server = HTTPServer((host, port), make_handler(engine, console=console, database=database, auth=auth_service))
    print(f"Tenta runtime listening on http://{host}:{port}")
    print(f"Tenta dashboard available at http://{host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Tenta runtime API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8080, type=int)
    parser.add_argument("--audit-path", default=None)
    parser.add_argument("--storage-url", default=None)
    parser.add_argument("--storage-path", default=None)
    parser.add_argument("--memory-storage", action="store_true")
    args = parser.parse_args(argv)
    storage_url = None
    if args.storage_url or args.storage_path or args.memory_storage:
        storage_url = storage_url_from_options(
            storage_url=args.storage_url,
            storage_path=args.storage_path,
            memory_storage=args.memory_storage,
        )
    run(host=args.host, port=args.port, audit_path=args.audit_path, storage_url=storage_url)


if __name__ == "__main__":
    main()
