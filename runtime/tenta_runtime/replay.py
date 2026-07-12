"""Replay fixtures for workload-aware runtime regression checks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .engine import RuntimeEngine


DEFAULT_REPLAY_DIR = Path(__file__).resolve().parent / "replay_fixtures"


@dataclass(frozen=True)
class ReplayCase:
    case_id: str
    workload_id: str
    payload: Dict[str, Any]
    expected: Dict[str, Any]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ReplayCase":
        return cls(
            case_id=str(payload["case_id"]),
            workload_id=str(payload["workload_id"]),
            payload=dict(payload["payload"]),
            expected=dict(payload.get("expected") or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "workload_id": self.workload_id,
            "payload": dict(self.payload),
            "expected": dict(self.expected),
        }


def load_replay_cases(workload_id: Optional[str] = None, directory: Path = DEFAULT_REPLAY_DIR) -> List[ReplayCase]:
    cases: List[ReplayCase] = []
    if not directory.exists():
        return cases
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        items = data if isinstance(data, list) else data.get("cases", [])
        for item in items:
            case = ReplayCase.from_mapping(item)
            if workload_id is None or case.workload_id == workload_id:
                cases.append(case)
    return cases


def replay_manifest(workload_id: Optional[str] = None) -> Dict[str, Any]:
    cases = load_replay_cases(workload_id)
    return {
        "cases": [
            {
                "case_id": case.case_id,
                "workload_id": case.workload_id,
                "expected": dict(case.expected),
            }
            for case in cases
        ],
        "count": len(cases),
        "workload_id": workload_id,
    }


def run_replay(engine: RuntimeEngine, workload_id: Optional[str] = None) -> Dict[str, Any]:
    results = [_run_case(engine, case) for case in load_replay_cases(workload_id)]
    passed = sum(1 for result in results if result["passed"])
    return {
        "status": "passed" if passed == len(results) else "failed",
        "passed": passed,
        "failed": len(results) - passed,
        "count": len(results),
        "results": results,
    }


def summarize_http_replay(results: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(results)
    passed = sum(1 for row in rows if row.get("passed"))
    return {
        "status": "passed" if passed == len(rows) else "failed",
        "passed": passed,
        "failed": len(rows) - passed,
        "count": len(rows),
        "results": rows,
    }


def _run_case(engine: RuntimeEngine, case: ReplayCase) -> Dict[str, Any]:
    response = engine.score(case.payload)
    return _compare(case, response)


def compare_response(case: ReplayCase, response: Mapping[str, Any]) -> Dict[str, Any]:
    return _compare(case, response)


def _compare(case: ReplayCase, response: Mapping[str, Any]) -> Dict[str, Any]:
    mismatches = []
    for key, expected_value in case.expected.items():
        actual_value = response.get(key)
        if actual_value != expected_value:
            mismatches.append({"field": key, "expected": expected_value, "actual": actual_value})
    return {
        "case_id": case.case_id,
        "workload_id": case.workload_id,
        "passed": not mismatches,
        "expected": dict(case.expected),
        "actual": {key: response.get(key) for key in case.expected.keys()},
        "mismatches": mismatches,
    }
