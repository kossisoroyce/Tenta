"""Command line utility for the Tenta runtime."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .api import run
from .database import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_POSTGRES_COMPOSE_FILE,
    DEFAULT_POSTGRES_SERVICE,
    DEFAULT_POSTGRES_STORAGE_URL,
    RuntimeConfig,
    save_runtime_config,
)
from .control_plane_store import create_control_plane_store
from .replay import compare_response, load_replay_cases, replay_manifest, summarize_http_replay
from .storage import create_runtime_store, storage_url_from_options
from .workloads import DEFAULT_WORKLOAD_ID

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
COMMANDS = {
    "serve",
    "health",
    "endpoint",
    "decide",
    "decision",
    "score",
    "decisions",
    "transaction",
    "operations",
    "workload",
    "replay",
    "feedback",
    "drift",
    "audit",
    "db",
}


def main(argv: Optional[List[str]] = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or (args[0] not in COMMANDS and args[0] not in {"-h", "--help"}):
        args = ["serve", *args]

    parser = _build_parser()
    parsed = parser.parse_args(args)
    if parsed.command == "serve":
        _serve(parsed)
    elif parsed.command == "health":
        _print_json(_request_json(parsed.url, "/v1/health"))
    elif parsed.command == "endpoint":
        _print_json(_request_json(parsed.url, "/v1/serving-endpoint"))
    elif parsed.command == "decisions":
        _print_json(_request_json(parsed.url, f"/v1/decisions?limit={parsed.limit}"))
    elif parsed.command == "decision":
        _print_json(_request_json(parsed.url, f"/v1/decision-requests/{parsed.decision_request_id}"))
    elif parsed.command == "transaction":
        _print_json(_request_json(parsed.url, f"/v1/transactions/{parsed.transaction_id}"))
    elif parsed.command == "operations":
        _print_json(_request_json(parsed.url, f"/v1/operations?limit={parsed.limit}"))
    elif parsed.command == "workload":
        _workload(parsed)
    elif parsed.command == "replay":
        _replay(parsed)
    elif parsed.command == "feedback":
        payload = {
            "decision_request_id": parsed.decision_request_id,
            "outcome_label": parsed.label,
            "actor": parsed.actor,
            "analyst": parsed.actor,
            "source": parsed.source,
        }
        if parsed.model_decision:
            payload["model_decision"] = parsed.model_decision
        if parsed.segment:
            payload["segment"] = parsed.segment
        if parsed.delay_hours is not None:
            payload["delay_hours"] = parsed.delay_hours
        _print_json(_request_json(parsed.url, "/v1/feedback", method="POST", payload=payload))
    elif parsed.command == "drift":
        _drift(parsed)
    elif parsed.command == "audit":
        _audit(parsed)
    elif parsed.command == "score":
        payload = _score_payload(parsed)
        _print_json(_request_json(parsed.url, "/v1/score", method="POST", payload=payload))
    elif parsed.command == "decide":
        payload = _score_payload(parsed)
        _print_json(_request_json(parsed.url, "/v1/decision-requests", method="POST", payload=payload))
    elif parsed.command == "db":
        _db(parsed)
    else:  # pragma: no cover - argparse prevents this path.
        parser.error(f"unsupported command: {parsed.command}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tenta", description="Tenta runtime utility.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="Run the local runtime API.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8080, type=int)
    serve.add_argument("--audit-path", default=None)
    serve.add_argument("--storage-url", default=None)
    serve.add_argument("--storage-path", default=None)
    serve.add_argument("--memory-storage", action="store_true")

    health = subparsers.add_parser("health", help="Fetch runtime health.")
    health.add_argument("--url", default=DEFAULT_BASE_URL)

    endpoint = subparsers.add_parser("endpoint", help="Fetch the current app-facing serving endpoint.")
    endpoint.add_argument("--url", default=DEFAULT_BASE_URL)

    decisions = subparsers.add_parser("decisions", help="List recent decision audit events.")
    decisions.add_argument("--url", default=DEFAULT_BASE_URL)
    decisions.add_argument("--limit", default=25, type=int)

    decision = subparsers.add_parser("decision", help="Fetch a decision request trail.")
    decision.add_argument("decision_request_id")
    decision.add_argument("--url", default=DEFAULT_BASE_URL)

    transaction = subparsers.add_parser("transaction", help="Fetch a transaction decision trail.")
    transaction.add_argument("transaction_id")
    transaction.add_argument("--url", default=DEFAULT_BASE_URL)

    operations = subparsers.add_parser("operations", help="List recent control-plane operation events.")
    operations.add_argument("--url", default=DEFAULT_BASE_URL)
    operations.add_argument("--limit", default=50, type=int)

    workload = subparsers.add_parser("workload", help="Inspect and manage workload specs.")
    workload_subparsers = workload.add_subparsers(dest="workload_command", required=True)

    workload_list = workload_subparsers.add_parser("list", help="List workload specs.")
    workload_list.add_argument("--url", default=DEFAULT_BASE_URL)

    workload_active = workload_subparsers.add_parser("active", help="Show the active workload spec.")
    workload_active.add_argument("--url", default=DEFAULT_BASE_URL)

    workload_show = workload_subparsers.add_parser("show", help="Show a workload spec.")
    workload_show.add_argument("workload_id")
    workload_show.add_argument("--url", default=DEFAULT_BASE_URL)

    workload_export = workload_subparsers.add_parser("export", help="Export a workload spec.")
    workload_export.add_argument("workload_id")
    workload_export.add_argument("--output", default=None, help="Write the spec to a file instead of stdout.")
    workload_export.add_argument("--url", default=DEFAULT_BASE_URL)

    workload_import = workload_subparsers.add_parser("import", help="Import a workload spec into a running runtime.")
    workload_import.add_argument("path")
    workload_import.add_argument("--activate", action="store_true")
    workload_import.add_argument("--no-persist", action="store_true")
    workload_import.add_argument("--actor", default="operator@cli")
    workload_import.add_argument("--role", default="model-risk")
    workload_import.add_argument("--reason", default=None)
    workload_import.add_argument("--url", default=DEFAULT_BASE_URL)

    workload_sample = workload_subparsers.add_parser("sample", help="Print a sample payload for a workload.")
    workload_sample.add_argument("workload_id", nargs="?", default=DEFAULT_WORKLOAD_ID)
    workload_sample.add_argument("--url", default=DEFAULT_BASE_URL)

    workload_validate = workload_subparsers.add_parser("validate", help="Validate a payload against a workload spec.")
    workload_validate.add_argument("--workload-id", default=None)
    workload_validate.add_argument("--payload", default=None, help="Path to a JSON payload. Reads stdin when omitted.")
    workload_validate.add_argument("--url", default=DEFAULT_BASE_URL)

    workload_activate = workload_subparsers.add_parser("activate", help="Activate a workload on a running runtime.")
    workload_activate.add_argument("workload_id")
    workload_activate.add_argument("--actor", default="operator@cli")
    workload_activate.add_argument("--role", default="model-risk")
    workload_activate.add_argument("--reason", default=None)
    workload_activate.add_argument("--url", default=DEFAULT_BASE_URL)

    replay = subparsers.add_parser("replay", help="List or run workload replay fixtures.")
    replay_subparsers = replay.add_subparsers(dest="replay_command", required=True)

    replay_list = replay_subparsers.add_parser("list", help="List packaged replay fixtures.")
    replay_list.add_argument("--workload-id", default=None)

    replay_run = replay_subparsers.add_parser("run", help="Run packaged replay fixtures against a runtime.")
    replay_run.add_argument("--workload-id", default=None)
    replay_run.add_argument("--stable-ids", action="store_true", help="Use fixture ids instead of unique ids for this run.")
    replay_run.add_argument("--url", default=DEFAULT_BASE_URL)

    feedback = subparsers.add_parser("feedback", help="Record human feedback for a decision request.")
    feedback.add_argument("decision_request_id")
    feedback.add_argument("--label", required=True, choices=["adverse", "expected", "fraud", "legit"])
    feedback.add_argument("--model-decision", choices=["allow", "review", "block", "unknown"], default=None)
    feedback.add_argument("--segment", default=None)
    feedback.add_argument("--delay-hours", default=None, type=float)
    feedback.add_argument("--source", default="analyst")
    feedback.add_argument("--actor", default="operator@cli")
    feedback.add_argument("--url", default=DEFAULT_BASE_URL)

    drift = subparsers.add_parser("drift", help="Inspect or record drift signals.")
    drift_subparsers = drift.add_subparsers(dest="drift_command", required=True)

    drift_list = drift_subparsers.add_parser("list", help="Fetch drift monitors.")
    drift_list.add_argument("--url", default=DEFAULT_BASE_URL)

    drift_record = drift_subparsers.add_parser("record", help="Record a drift detector signal.")
    drift_record.add_argument("--segment", required=True)
    drift_record.add_argument("--feature", required=True)
    drift_record.add_argument("--detector", required=True)
    drift_record.add_argument("--statistic", required=True, type=float)
    drift_record.add_argument("--threshold", required=True, type=float)
    drift_record.add_argument("--severity", choices=["critical", "warn", "watch", "stable"], default=None)
    drift_record.add_argument("--confidence", default=0.0, type=float)
    drift_record.add_argument("--population", default=0, type=int)
    drift_record.add_argument("--baseline-window", default="30d")
    drift_record.add_argument("--current-window", default="24h")
    drift_record.add_argument("--recommended-action", default=None)
    drift_record.add_argument("--actor", default="detector@cli")
    drift_record.add_argument("--url", default=DEFAULT_BASE_URL)

    audit = subparsers.add_parser("audit", help="Inspect audit integrity.")
    audit_subparsers = audit.add_subparsers(dest="audit_command", required=True)

    audit_verify = audit_subparsers.add_parser("verify", help="Verify decision and operation hash chains.")
    audit_verify.add_argument("--url", default=DEFAULT_BASE_URL)

    decide = subparsers.add_parser("decide", help="Run a decision request through a running runtime.")
    decide.add_argument("--url", default=DEFAULT_BASE_URL)
    decide.add_argument("--payload", default=None, help="Path to a JSON decision request. Reads stdin when omitted.")
    decide.add_argument("--sample", action="store_true", help="Send a generated low-risk sample decision request.")
    decide.add_argument("--workload-id", default=None)

    score = subparsers.add_parser("score", help="Legacy alias for running a decision request.")
    score.add_argument("--url", default=DEFAULT_BASE_URL)
    score.add_argument("--payload", default=None, help="Path to a JSON score payload. Reads stdin when omitted.")
    score.add_argument("--sample", action="store_true", help="Send a generated low-risk sample decision request.")
    score.add_argument("--workload-id", default=None)

    db = subparsers.add_parser("db", help="Provision or inspect runtime storage.")
    db_subparsers = db.add_subparsers(dest="db_command", required=True)

    db_status = db_subparsers.add_parser("status", help="Fetch database provisioning status from a running runtime.")
    db_status.add_argument("--url", default=DEFAULT_BASE_URL)

    db_sqlite = db_subparsers.add_parser("provision-sqlite", help="Provision SQLite and connect a running runtime.")
    db_sqlite.add_argument("--url", default=DEFAULT_BASE_URL)
    db_sqlite.add_argument("--path", default="data/tenta.sqlite3")
    db_sqlite.add_argument("--no-persist", action="store_true")

    db_postgres = db_subparsers.add_parser("provision-postgres", help="Provision local Postgres with Docker Compose and connect a running runtime.")
    db_postgres.add_argument("--url", default=DEFAULT_BASE_URL)
    db_postgres.add_argument("--storage-url", default=DEFAULT_POSTGRES_STORAGE_URL)
    db_postgres.add_argument("--compose-file", default=DEFAULT_POSTGRES_COMPOSE_FILE)
    db_postgres.add_argument("--service", default=DEFAULT_POSTGRES_SERVICE)
    db_postgres.add_argument("--no-start", action="store_true")
    db_postgres.add_argument("--no-wait", action="store_true")
    db_postgres.add_argument("--no-persist", action="store_true")

    db_connect = db_subparsers.add_parser("connect", help="Connect a running runtime to a storage URL.")
    db_connect.add_argument("storage_url")
    db_connect.add_argument("--url", default=DEFAULT_BASE_URL)
    db_connect.add_argument("--no-persist", action="store_true")

    db_init = db_subparsers.add_parser("init", help="Initialize storage locally and save runtime config.")
    db_init.add_argument("--storage-url", default=None)
    db_init.add_argument("--storage-path", default=None)
    db_init.add_argument("--memory-storage", action="store_true")
    db_init.add_argument("--config-path", default=DEFAULT_CONFIG_PATH)

    db_migrate = db_subparsers.add_parser("migrate", help="Run storage migrations for runtime and control-plane stores.")
    db_migrate.add_argument("--storage-url", default=None)
    db_migrate.add_argument("--storage-path", default=None)
    db_migrate.add_argument("--memory-storage", action="store_true")

    return parser


def _serve(args: argparse.Namespace) -> None:
    storage_url = None
    if args.storage_url or args.storage_path or args.memory_storage:
        storage_url = storage_url_from_options(
            storage_url=args.storage_url,
            storage_path=args.storage_path,
            memory_storage=args.memory_storage,
        )
    run(host=args.host, port=args.port, audit_path=args.audit_path, storage_url=storage_url)


def _db(args: argparse.Namespace) -> None:
    if args.db_command == "status":
        _print_json(_request_json(args.url, "/v1/database/status"))
        return
    if args.db_command == "provision-sqlite":
        payload = {
            "backend": "sqlite",
            "path": args.path,
            "persist": not args.no_persist,
        }
        _print_json(_request_json(args.url, "/v1/database/provision", method="POST", payload=payload))
        return
    if args.db_command == "provision-postgres":
        payload = {
            "backend": "postgres",
            "storage_url": args.storage_url,
            "compose_file": args.compose_file,
            "service": args.service,
            "start": not args.no_start,
            "wait": not args.no_wait,
            "persist": not args.no_persist,
        }
        _print_json(_request_json(args.url, "/v1/database/provision", method="POST", payload=payload))
        return
    if args.db_command == "connect":
        payload = {
            "storage_url": args.storage_url,
            "persist": not args.no_persist,
        }
        _print_json(_request_json(args.url, "/v1/database/provision", method="POST", payload=payload))
        return
    if args.db_command == "init":
        storage_url = storage_url_from_options(
            storage_url=args.storage_url,
            storage_path=args.storage_path,
            memory_storage=args.memory_storage,
        )
        store = create_runtime_store(storage_url)
        health = store.health()
        control_store = create_control_plane_store(storage_url)
        control_health = control_store.health()
        close = getattr(store, "close", None)
        if callable(close):
            close()
        control_close = getattr(control_store, "close", None)
        if callable(control_close):
            control_close()
        save_runtime_config(RuntimeConfig(storage_url=storage_url), args.config_path)
        _print_json({
            "status": "initialized",
            "storage_url": storage_url,
            "config_path": args.config_path,
            "storage": health,
            "control_plane": control_health,
        })
        return
    if args.db_command == "migrate":
        storage_url = storage_url_from_options(
            storage_url=args.storage_url,
            storage_path=args.storage_path,
            memory_storage=args.memory_storage,
        )
        store = create_runtime_store(storage_url)
        control_store = create_control_plane_store(storage_url)
        health = store.health()
        control_health = control_store.health()
        close = getattr(store, "close", None)
        if callable(close):
            close()
        control_close = getattr(control_store, "close", None)
        if callable(control_close):
            control_close()
        _print_json({
            "status": "migrated",
            "storage_url": storage_url,
            "storage": health,
            "control_plane": control_health,
        })
        return
    raise SystemExit(f"unsupported db command: {args.db_command}")


def _workload(args: argparse.Namespace) -> None:
    if args.workload_command == "list":
        _print_json(_request_json(args.url, "/v1/workloads"))
        return
    if args.workload_command == "active":
        _print_json(_request_json(args.url, "/v1/workloads/active"))
        return
    if args.workload_command == "show":
        _print_json(_request_json(args.url, f"/v1/workloads/{args.workload_id}"))
        return
    if args.workload_command == "export":
        payload = _request_json(args.url, f"/v1/workloads/{args.workload_id}/export")
        spec = payload.get("spec", payload)
        if args.output:
            Path(args.output).write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            _print_json({"status": "exported", "workload_id": args.workload_id, "path": args.output})
        else:
            _print_json(spec)
        return
    if args.workload_command == "import":
        spec = json.loads(Path(args.path).read_text(encoding="utf-8"))
        payload = {
            "spec": spec,
            "activate": args.activate,
            "persist": not args.no_persist,
            "actor": args.actor,
            "role": args.role,
        }
        if args.reason:
            payload["reason"] = args.reason
        _print_json(_request_json(args.url, "/v1/workloads/import", method="POST", payload=payload))
        return
    if args.workload_command == "sample":
        _print_json(_request_json(args.url, f"/v1/workloads/{args.workload_id}/sample"))
        return
    if args.workload_command == "validate":
        payload = _read_payload(args.payload)
        body: Dict[str, Any] = {"payload": payload}
        if args.workload_id:
            body["workload_id"] = args.workload_id
        _print_json(_request_json(args.url, "/v1/workloads/validate", method="POST", payload=body))
        return
    if args.workload_command == "activate":
        payload = {
            "workload_id": args.workload_id,
            "actor": args.actor,
            "role": args.role,
        }
        if args.reason:
            payload["reason"] = args.reason
        _print_json(_request_json(args.url, "/v1/workloads/activate", method="POST", payload=payload))
        return
    raise SystemExit(f"unsupported workload command: {args.workload_command}")


def _replay(args: argparse.Namespace) -> None:
    if args.replay_command == "list":
        _print_json(replay_manifest(args.workload_id))
        return
    if args.replay_command == "run":
        results = []
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        for case in load_replay_cases(args.workload_id):
            payload = dict(case.payload) if args.stable_ids else _fresh_replay_payload(case.payload, run_id)
            response = _request_json(args.url, "/v1/decision-requests", method="POST", payload=payload)
            results.append(compare_response(case, response))
        _print_json(summarize_http_replay(results))
        return
    raise SystemExit(f"unsupported replay command: {args.replay_command}")


def _audit(args: argparse.Namespace) -> None:
    if args.audit_command == "verify":
        _print_json(_request_json(args.url, "/v1/audit/integrity"))
        return
    raise SystemExit(f"unsupported audit command: {args.audit_command}")


def _drift(args: argparse.Namespace) -> None:
    if args.drift_command == "list":
        _print_json(_request_json(args.url, "/v1/drift"))
        return
    if args.drift_command == "record":
        payload = {
            "segment": args.segment,
            "feature": args.feature,
            "detector": args.detector,
            "statistic": args.statistic,
            "threshold": args.threshold,
            "confidence": args.confidence,
            "population": args.population,
            "baseline_window": args.baseline_window,
            "current_window": args.current_window,
            "actor": args.actor,
        }
        if args.severity:
            payload["severity"] = args.severity
        if args.recommended_action:
            payload["recommended_action"] = args.recommended_action
        _print_json(_request_json(args.url, "/v1/drift/events", method="POST", payload=payload))
        return
    raise SystemExit(f"unsupported drift command: {args.drift_command}")


def _request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        _join_url(base_url, path),
        data=body,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        error_payload = json.loads(exc.read().decode("utf-8") or "{}")
        message = error_payload.get("message") or error_payload.get("error") or str(exc)
        raise SystemExit(f"{exc.code}: {message}") from exc


def _score_payload(args: argparse.Namespace) -> Dict[str, Any]:
    if args.sample:
        return _sample_payload(args.workload_id or DEFAULT_WORKLOAD_ID)
    if args.payload:
        payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
        if args.workload_id:
            payload["workload_id"] = args.workload_id
        return payload
    if not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if raw:
            payload = json.loads(raw)
            if args.workload_id:
                payload["workload_id"] = args.workload_id
            return payload
    return _sample_payload(args.workload_id or DEFAULT_WORKLOAD_ID)


def _read_payload(path: Optional[str]) -> Dict[str, Any]:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    if not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if raw:
            return json.loads(raw)
    return _sample_payload(DEFAULT_WORKLOAD_ID)


def _fresh_replay_payload(payload: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    fresh = dict(payload)
    current_id = str(fresh.get("decision_request_id") or fresh.get("transaction_id") or "replay")
    fresh["decision_request_id"] = f"{current_id}-{run_id}"
    fresh.pop("transaction_id", None)
    return fresh


def _sample_payload(workload_id: str = DEFAULT_WORKLOAD_ID) -> Dict[str, Any]:
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return {
        "decision_request_id": f"req-cli-{suffix}",
        "workload_id": workload_id,
        "subject_id": "subject-cli",
        "amount": 120.0,
        "currency": "USD",
        "context_id": "reference-workload",
        "channel": "api",
        "event_time": datetime.now(timezone.utc).isoformat(),
        "features": {
            "entity_risk": 0.2,
            "velocity_10m": 2,
            "subject_age_days": 180,
            "prior_adverse_events": 0,
            "high_risk_segment": False,
        },
    }


def _join_url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def _print_json(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
