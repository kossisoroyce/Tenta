"""Database provisioning and connection management."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.util import find_spec
from typing import Any, Callable, Dict, List, Optional

from .control_plane import ControlPlane
from .control_plane_store import create_control_plane_store
from .engine import RuntimeEngine
from .storage import DEFAULT_SQLITE_PATH, DEFAULT_STORAGE_URL, create_runtime_store
from .workloads import DEFAULT_WORKLOAD_ID


DEFAULT_CONFIG_PATH = "data/tenta-runtime.json"
DEFAULT_POSTGRES_STORAGE_URL = "postgresql://tenta:tenta@127.0.0.1:5432/tenta"
DEFAULT_POSTGRES_COMPOSE_FILE = "compose.yaml"
DEFAULT_POSTGRES_SERVICE = "postgres"


@dataclass(frozen=True)
class CommandResult:
    command: List[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[[List[str]], CommandResult]


@dataclass(frozen=True)
class RuntimeConfig:
    storage_url: str = DEFAULT_STORAGE_URL
    active_workload_id: str = DEFAULT_WORKLOAD_ID
    updated_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "storage_url": self.storage_url,
            "active_workload_id": self.active_workload_id,
            "updated_at": self.updated_at,
        }


class DatabaseProvisioner:
    """Provision and connect runtime storage backends."""

    def __init__(
        self,
        engine: RuntimeEngine,
        config_path: str = DEFAULT_CONFIG_PATH,
        control_plane: Optional[ControlPlane] = None,
        command_runner: Optional[CommandRunner] = None,
    ) -> None:
        self.engine = engine
        self.config_path = config_path
        self.control_plane = control_plane
        self.command_runner = command_runner

    def status(self) -> Dict[str, Any]:
        config = load_runtime_config(self.config_path)
        health = self.engine.health().get("storage", {})
        control_plane_health = (
            self.control_plane.persistence_health()
            if self.control_plane is not None
            else {"status": "unavailable", "backend": None}
        )
        return {
            "configured_storage_url": _redact_storage_url(config.storage_url),
            "connected": health,
            "control_plane": control_plane_health,
            "available_backends": [
                {
                    "backend": "sqlite",
                    "label": "Embedded SQLite",
                    "default_storage_url": f"sqlite:{DEFAULT_SQLITE_PATH}",
                    "provisionable": True,
                    "requires": [],
                },
                {
                    "backend": "postgres",
                    "label": "Postgres",
                    "default_storage_url": DEFAULT_POSTGRES_STORAGE_URL,
                    "provisionable": True,
                    "provisioner": "docker-compose",
                    "compose_file": DEFAULT_POSTGRES_COMPOSE_FILE,
                    "compose_file_exists": os.path.exists(DEFAULT_POSTGRES_COMPOSE_FILE),
                    "service": DEFAULT_POSTGRES_SERVICE,
                    "driver_available": find_spec("psycopg") is not None,
                    "requires": ["docker", "tenta[postgres]"],
                },
            ],
        }

    def provision_sqlite(
        self,
        path: str = DEFAULT_SQLITE_PATH,
        persist: bool = True,
        *,
        actor: str = "operator@database",
        role: Optional[str] = None,
        source: Optional[str] = None,
        request_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        storage_url = f"sqlite:{path}"
        return self.connect(
            storage_url=storage_url,
            persist=persist,
            provisioned=True,
            actor=actor,
            role=role,
            source=source,
            request_id=request_id,
            reason=reason,
        )

    def provision_postgres(
        self,
        storage_url: str = DEFAULT_POSTGRES_STORAGE_URL,
        persist: bool = True,
        *,
        compose_file: str = DEFAULT_POSTGRES_COMPOSE_FILE,
        service: str = DEFAULT_POSTGRES_SERVICE,
        start: bool = True,
        wait: bool = True,
        check_driver: bool = True,
        actor: str = "operator@database",
        role: Optional[str] = None,
        source: Optional[str] = None,
        request_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not (storage_url.startswith("postgresql://") or storage_url.startswith("postgres://")):
            raise ValueError("postgres storage_url must start with postgresql:// or postgres://")

        provisioning: Dict[str, Any] = {
            "backend": "postgres",
            "mode": "docker-compose",
            "compose_file": compose_file,
            "service": service,
            "started": False,
            "wait": wait,
        }
        try:
            if check_driver:
                self._require_postgres_driver()
            if start:
                self._ensure_compose_file(compose_file)
                command = ["docker", "compose", "-f", compose_file, "up", "-d"]
                if wait:
                    command.append("--wait")
                command.append(service)
                result = self._run_command(command)
                provisioning["command"] = _command_result_payload(result)
                if result.returncode != 0:
                    detail = (result.stderr or result.stdout or "docker compose returned a non-zero exit code").strip()
                    raise RuntimeError(f"postgres provisioning failed: {detail}")
                provisioning["started"] = True
            return self.connect(
                storage_url=storage_url,
                persist=persist,
                provisioned=True,
                provisioning=provisioning,
                actor=actor,
                role=role,
                source=source,
                request_id=request_id,
                reason=reason,
            )
        except Exception as exc:
            self._record_failed_provision(
                backend="postgres",
                storage_url=storage_url,
                persist=persist,
                provisioning=provisioning,
                error=exc,
                actor=actor,
                role=role,
                source=source,
                request_id=request_id,
                reason=reason,
            )
            raise

    def connect(
        self,
        storage_url: str,
        persist: bool = True,
        provisioned: bool = False,
        provisioning: Optional[Dict[str, Any]] = None,
        *,
        actor: str = "operator@database",
        role: Optional[str] = None,
        source: Optional[str] = None,
        request_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        store = create_runtime_store(storage_url)
        control_plane_store = create_control_plane_store(storage_url) if self.control_plane is not None else None
        storage_health = store.health()
        self.engine.replace_store(store)
        control_plane_health = None
        operation_event = None
        if self.control_plane is not None and control_plane_store is not None:
            self.control_plane.replace_store(control_plane_store)
            control_plane_health = self.control_plane.persistence_health()
        if persist:
            existing = load_runtime_config(self.config_path)
            save_runtime_config(
                RuntimeConfig(
                    storage_url=storage_url,
                    active_workload_id=existing.active_workload_id,
                    updated_at=_now(),
                ),
                self.config_path,
            )
        if self.control_plane is not None:
            request = {
                "storage_url": _redact_storage_url(storage_url),
                "persist": persist,
                "provisioned": provisioned,
            }
            result = {
                "storage": storage_health,
                "control_plane": control_plane_health,
                "config_path": self.config_path if persist else None,
            }
            if provisioning is not None:
                request["provisioning"] = provisioning
                result["provisioning"] = provisioning
            operation_event = self.control_plane.record_operation(
                "database.provision" if provisioned else "database.connect",
                actor,
                target=storage_health.get("backend"),
                request=request,
                result=result,
                role=role,
                source=source,
                request_id=request_id,
                reason=reason,
            )
            control_plane_health = self.control_plane.persistence_health()
        return {
            "status": "connected",
            "provisioned": provisioned,
            "storage_url": _redact_storage_url(storage_url),
            "storage": storage_health,
            "control_plane": control_plane_health,
            "operation": operation_event,
            "provisioning": provisioning,
            "config_path": self.config_path if persist else None,
        }

    def _run_command(self, command: List[str]) -> CommandResult:
        if self.command_runner is not None:
            return self.command_runner(command)
        try:
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
        except FileNotFoundError as exc:
            raise RuntimeError("postgres provisioning requires Docker with the `docker compose` plugin.") from exc
        return CommandResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def _require_postgres_driver(self) -> None:
        if find_spec("psycopg") is None:
            raise RuntimeError("Postgres storage requires `pip install tenta[postgres]`.")

    def _ensure_compose_file(self, compose_file: str) -> None:
        if not os.path.exists(compose_file):
            raise RuntimeError(f"postgres provisioning requires compose file '{compose_file}'.")

    def _record_failed_provision(
        self,
        *,
        backend: str,
        storage_url: str,
        persist: bool,
        provisioning: Dict[str, Any],
        error: Exception,
        actor: str,
        role: Optional[str],
        source: Optional[str],
        request_id: Optional[str],
        reason: Optional[str],
    ) -> None:
        if self.control_plane is None:
            return
        self.control_plane.record_operation(
            "database.provision",
            actor,
            target=backend,
            status="failed",
            request={
                "storage_url": _redact_storage_url(storage_url),
                "persist": persist,
                "provisioned": True,
                "provisioning": provisioning,
            },
            result={"error": str(error), "provisioning": provisioning},
            message=str(error),
            role=role,
            source=source,
            request_id=request_id,
            reason=reason,
        )


def load_runtime_config(path: str = DEFAULT_CONFIG_PATH) -> RuntimeConfig:
    if not os.path.exists(path):
        return RuntimeConfig(storage_url=DEFAULT_STORAGE_URL)
    with open(path, "r", encoding="utf-8") as config_file:
        payload = json.load(config_file)
    return RuntimeConfig(
        storage_url=str(payload.get("storage_url") or DEFAULT_STORAGE_URL),
        active_workload_id=str(payload.get("active_workload_id") or DEFAULT_WORKLOAD_ID),
        updated_at=payload.get("updated_at"),
    )


def save_runtime_config(config: RuntimeConfig, path: str = DEFAULT_CONFIG_PATH) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as config_file:
        json.dump(config.to_dict(), config_file, indent=2, sort_keys=True)
        config_file.write("\n")


def default_storage_url_from_config(path: str = DEFAULT_CONFIG_PATH) -> str:
    return load_runtime_config(path).storage_url


def default_active_workload_from_config(path: str = DEFAULT_CONFIG_PATH) -> str:
    return load_runtime_config(path).active_workload_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _command_result_payload(result: CommandResult) -> Dict[str, Any]:
    payload = {
        "command": list(result.command),
        "returncode": result.returncode,
    }
    if result.stdout:
        payload["stdout"] = _truncate(result.stdout)
    if result.stderr:
        payload["stderr"] = _truncate(result.stderr)
    return payload


def _truncate(value: str, limit: int = 800) -> str:
    stripped = value.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit] + "..."
