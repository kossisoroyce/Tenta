"""Small Python client for applications calling a Tenta runtime."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class TentaClientError(RuntimeError):
    """Raised when a Tenta API request fails."""

    def __init__(self, status: int, message: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self.status = status
        self.payload = payload or {}
        super().__init__(message)


class TentaClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 5.0,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = dict(headers or {})

    def endpoint(self) -> Dict[str, Any]:
        return self._request("GET", "/v1/serving-endpoint")

    def health(self) -> Dict[str, Any]:
        return self._request("GET", "/v1/health")

    def decide(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/v1/decision-requests", payload)

    def decision(self, decision_request_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/v1/decision-requests/{decision_request_id}")

    def feedback(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/v1/feedback", payload)

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", **self.headers}
        request = Request(self.base_url + path, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                error_payload = json.loads(raw or "{}")
            except json.JSONDecodeError:
                error_payload = {"message": raw}
            message = error_payload.get("message") or error_payload.get("error") or str(exc)
            raise TentaClientError(exc.code, str(message), error_payload) from exc
