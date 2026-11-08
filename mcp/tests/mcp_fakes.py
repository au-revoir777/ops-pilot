"""Fake Prometheus / Loki / OpsPilot API for MCP tool tests.

A single httpx transport that answers like the real backends, driven by
simple Python data, so every tool can be tested without containers.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx

from opsmcp.catalog import ServiceCatalog
from opsmcp.config import McpSettings
from opsmcp.server import build_deps

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
CATALOG = """
services:
  checkout: {project: opsdemo, depends_on: [users, payments]}
  payments: {project: opsdemo}
  users: {project: opsdemo}
"""


def vector(*samples: tuple[dict[str, str], float]) -> list[dict[str, Any]]:
    return [{"metric": labels, "value": [NOW.timestamp(), str(value)]} for labels, value in samples]


class FakeBackends:
    def __init__(self) -> None:
        # PromQL substring -> instant-vector result (first matching key wins).
        self.instant: dict[str, list[dict[str, Any]]] = {}
        self.range_result: list[dict[str, Any]] = []
        self.alerts: list[dict[str, Any]] = []
        self.loki_streams: list[dict[str, Any]] = []
        self.incidents: list[dict[str, Any]] = []
        self.down: set[str] = set()  # hosts that fail at the transport level
        self.status_code: dict[str, int] = {}  # host -> forced HTTP status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.url.host
        if host in self.down:
            raise httpx.ConnectError("connection refused")
        if host in self.status_code:
            code = self.status_code[host]
            return httpx.Response(code, json={"status": "error", "error": "parse error: bad query"})
        if request.method != "GET":
            return httpx.Response(405)
        path = request.url.path
        params = dict(request.url.params)
        if path == "/api/v1/query":
            query = params["query"]
            result = next((v for k, v in self.instant.items() if k in query), [])
            return _prom({"resultType": "vector", "result": result})
        if path == "/api/v1/query_range":
            return _prom({"resultType": "matrix", "result": self.range_result})
        if path == "/api/v1/alerts":
            return _prom({"alerts": self.alerts})
        if path == "/loki/api/v1/query_range":
            return httpx.Response(
                200, json={"status": "success", "data": {"result": self.loki_streams}}
            )
        if path == "/api/incidents":
            return httpx.Response(200, json=self.incidents)
        return httpx.Response(404)

    def queries(self) -> list[str]:
        return [dict(r.url.params).get("query", "") for r in self.requests]


def _prom(data: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, content=json.dumps({"status": "success", "data": data}))


def make_deps(fake: FakeBackends, catalog: str | None = CATALOG, **settings: Any):
    cfg = McpSettings(
        _env_file=None,
        prometheus_url="http://prometheus.test",
        loki_url="http://loki.test",
        api_url="http://api.test",
        **settings,
    )
    deps = build_deps(cfg, transport=httpx.MockTransport(fake))
    if catalog is None:
        from opsmcp.catalog import CatalogError

        def missing() -> ServiceCatalog:
            raise CatalogError("service catalog not found")

        deps.catalog = missing
    else:
        parsed = ServiceCatalog.from_yaml(catalog)
        deps.catalog = lambda: parsed
    deps.now = lambda: NOW
    return deps
