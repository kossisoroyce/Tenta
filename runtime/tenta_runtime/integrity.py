"""Hash-chain verification for runtime and control-plane audit events."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional

from .audit import DecisionEvent
from .operations import OperationEvent


def verify_runtime_store(store: Any) -> Dict[str, Any]:
    health = store.health()
    total = _int_or_zero(health.get("decision_events"))
    events = store.list_decisions(limit=max(total, 1))
    report = verify_decision_events(events, total_events=total)
    report["backend"] = health.get("backend")
    return report


def verify_control_plane_store(store: Any) -> Dict[str, Any]:
    if store is None:
        return {
            "chain": "operations",
            "status": "valid",
            "backend": "memory",
            "events_checked": 0,
            "total_events": 0,
            "complete": True,
            "head_hash": None,
            "tail_hash": None,
            "issues": [],
        }
    health = store.health()
    total = _int_or_zero(health.get("operation_events"))
    events = store.list_operations(limit=max(total, 1))
    report = verify_operation_events(events, total_events=total)
    report["backend"] = health.get("backend")
    return report


def verify_decision_events(
    events_newest_first: Iterable[DecisionEvent],
    *,
    total_events: Optional[int] = None,
) -> Dict[str, Any]:
    return _verify_events(
        "decisions",
        events_newest_first,
        total_events=total_events,
        label_key="transaction_id",
    )


def verify_operation_events(
    events_newest_first: Iterable[OperationEvent],
    *,
    total_events: Optional[int] = None,
) -> Dict[str, Any]:
    return _verify_events(
        "operations",
        events_newest_first,
        total_events=total_events,
        label_key="operation_type",
    )


def combine_reports(decisions: Dict[str, Any], operations: Dict[str, Any]) -> Dict[str, Any]:
    statuses = {decisions.get("status"), operations.get("status")}
    if "invalid" in statuses:
        status = "invalid"
    elif "partial" in statuses:
        status = "partial"
    else:
        status = "valid"
    return {
        "status": status,
        "decisions": decisions,
        "operations": operations,
    }


def _verify_events(
    chain: str,
    events_newest_first: Iterable[Any],
    *,
    total_events: Optional[int],
    label_key: str,
) -> Dict[str, Any]:
    newest_first = list(events_newest_first)
    chronological = list(reversed(newest_first))
    expected_previous_hash = None
    issues: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    verified_events = 0

    for index, event in enumerate(chronological):
        payload = event.to_dict()
        event_id = payload.get("id")
        label = payload.get(label_key)
        actual_previous_hash = payload.get("previous_hash")
        actual_event_hash = payload.get("event_hash")

        if not actual_event_hash:
            warnings.append({
                "type": "legacy_missing_hash",
                "index": index,
                "event_id": event_id,
                "label": label,
                "message": "event predates hash-chain enforcement and cannot be verified",
            })
            expected_previous_hash = None
            continue

        if actual_previous_hash != expected_previous_hash:
            issues.append({
                "type": "previous_hash_mismatch",
                "index": index,
                "event_id": event_id,
                "label": label,
                "expected": expected_previous_hash,
                "actual": actual_previous_hash,
            })

        expected_hashes = _candidate_hashes(event, actual_previous_hash, chain=chain)
        if actual_event_hash not in expected_hashes.values():
            issues.append({
                "type": "event_hash_mismatch",
                "index": index,
                "event_id": event_id,
                "label": label,
                "expected": expected_hashes["current"],
                "actual": actual_event_hash,
            })
        else:
            verified_events += 1
            if actual_event_hash != expected_hashes["current"]:
                warnings.append({
                    "type": "legacy_hash_format",
                    "index": index,
                    "event_id": event_id,
                    "label": label,
                    "message": "event hash matches an older payload format",
                })

        expected_previous_hash = actual_event_hash

    checked = len(chronological)
    known_total = checked if total_events is None else total_events
    status = "invalid" if issues else "partial" if warnings else "valid"
    return {
        "chain": chain,
        "status": status,
        "events_checked": checked,
        "events_verified": verified_events,
        "legacy_events": len([item for item in warnings if item["type"] == "legacy_missing_hash"]),
        "total_events": known_total,
        "complete": checked >= known_total,
        "tail_hash": chronological[0].event_hash if chronological else None,
        "head_hash": chronological[-1].event_hash if chronological else None,
        "issues": issues,
        "warnings": warnings,
    }


def _int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _candidate_hashes(event: Any, previous_hash: Optional[str], *, chain: str) -> Dict[str, str]:
    payload = event.to_dict()
    payload["previous_hash"] = previous_hash
    payload.pop("event_hash", None)
    candidates = {"current": _hash_payload(payload)}

    if chain == "operations":
        legacy_payload = dict(payload)
        for key in ("role", "source", "request_id", "reason"):
            if legacy_payload.get(key) is None:
                legacy_payload.pop(key, None)
        candidates["legacy_optional_context"] = _hash_payload(legacy_payload)

    return candidates


def _hash_payload(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
