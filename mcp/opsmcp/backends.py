"""Read-only HTTP clients for Prometheus, Loki and the OpsPilot API.

Only GET requests to configured base URLs. Transport failures and 5xx become
BackendUnavailable (the tool reports the source as unavailable); 4xx become
BackendQueryError (the caller's query was rejected). Response bodies are never
echoed into errors.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx
import structlog

from opsmcp.instrumentation import BACKEND_LATENCY

logger = structlog.get_logger(__name__)


class BackendUnavailable(Exception):
    def __init__(self, source: str, reason: str) -> None:
        super().__init__(f"{source} unavailable: {reason}")
        self.source = source
        self.reason = reason


class BackendQueryError(Exception):
    def __init__(self, source: str, reason: str) -> None:
        super().__init__(f"{source} rejected the query: {reason}")
        self.source = source
        self.reason = reason


class _Backend:
    source = "backend"

    def __init__(self, client: httpx.AsyncClient, base_url: str) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        start = time.perf_counter()
        outcome = "error"
        try:
            response = await self.client.get(f"{self.base_url}{path}", params=params)
            if response.status_code >= 500:
                raise BackendUnavailable(self.source, f"HTTP {response.status_code}")
            if response.status_code >= 400:
                outcome = "rejected"
                raise BackendQueryError(self.source, _error_message(response))
            outcome = "ok"
            return response.json()
        except httpx.HTTPError as exc:
            logger.warning("backend_unreachable", source=self.source, error_type=type(exc).__name__)
            raise BackendUnavailable(self.source, type(exc).__name__) from exc
        except ValueError as exc:  # invalid JSON
            raise BackendUnavailable(self.source, "invalid response") from exc
        finally:
            BACKEND_LATENCY.labels(backend=self.source, outcome=outcome).observe(
                time.perf_counter() - start
            )


def _error_message(response: httpx.Response) -> str:
    """Prometheus/Loki put a short reason in `error`; keep it, cut it short."""
    try:
        return str(response.json().get("error", f"HTTP {response.status_code}"))[:200]
    except ValueError:
        return f"HTTP {response.status_code}"


class PrometheusClient(_Backend):
    source = "prometheus"

    async def instant(self, query: str) -> list[dict[str, Any]]:
        data = await self._get("/api/v1/query", {"query": query})
        return data["data"]["result"]

    async def range(
        self, query: str, start: datetime, end: datetime, step_seconds: int
    ) -> list[dict[str, Any]]:
        params = {
            "query": query,
            "start": start.timestamp(),
            "end": end.timestamp(),
            "step": step_seconds,
        }
        data = await self._get("/api/v1/query_range", params)
        return data["data"]["result"]

    async def alerts(self) -> list[dict[str, Any]]:
        data = await self._get("/api/v1/alerts")
        return data["data"]["alerts"]


class LokiClient(_Backend):
    source = "loki"

    async def query_range(
        self, logql: str, start: datetime, end: datetime, limit: int
    ) -> list[dict[str, Any]]:
        params = {
            "query": logql,
            "start": int(start.timestamp() * 1e9),
            "end": int(end.timestamp() * 1e9),
            "limit": limit,
            "direction": "backward",
        }
        data = await self._get("/loki/api/v1/query_range", params)
        return data["data"]["result"]


class OpsPilotApiClient(_Backend):
    source = "opspilot-api"

    async def list_incidents(self, limit: int = 100) -> list[dict[str, Any]]:
        return await self._get("/api/incidents", {"limit": limit})
