"""Incident lab: controlled failure injection for the demo workloads (D-034).

The browser never talks to the workloads directly. The API forwards to a fixed
allow-list of demo services (``LAB_TARGETS``), only when ``ENABLE_INCIDENT_LAB``
is true, and passes the workloads' admin token server-side. Monitored external
projects can never be targeted: they are not in the allow-list.

GET  /api/lab            lab status and each demo service's current mode
POST /api/lab/failure    {"service": "checkout", "mode": "db"}
POST /api/lab/traffic    {"requests": 50}  send checkout traffic (in the background)
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Annotated, Literal

import httpx
import structlog
from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.services.exceptions import NotFoundError, OpsPilotError

logger = structlog.get_logger(__name__)
router = APIRouter()

FailureMode = Literal["none", "latency", "errors", "db"]
DEMO_CART = {"user_id": "u-7", "items": [{"sku": "sku-1", "quantity": 1, "unit_price_cents": 999}]}


class LabDisabled(OpsPilotError):
    code = "LAB_DISABLED"
    status_code = 403
    public_message = True


class LabTargetUnavailable(OpsPilotError):
    code = "LAB_TARGET_UNAVAILABLE"
    status_code = 502
    public_message = True


async def get_lab_http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        yield client


LabHttpDep = Annotated[httpx.AsyncClient, Depends(get_lab_http)]


def _headers(settings: Settings) -> dict[str, str]:
    token = settings.failure_admin_token
    return {"X-Admin-Token": token.get_secret_value()} if token else {}


def _enabled(settings: Settings) -> Settings:
    if not settings.enable_incident_lab:
        raise LabDisabled("The incident lab is disabled (set ENABLE_INCIDENT_LAB=true)")
    return settings


class LabService(BaseModel):
    name: str
    mode: FailureMode | None  # None when the service could not be reached
    reachable: bool


class LabStatus(BaseModel):
    enabled: bool
    services: list[LabService]


@router.get("/lab", response_model=LabStatus)
async def lab_status(http: LabHttpDep) -> LabStatus:
    settings = get_settings()
    if not settings.enable_incident_lab:
        return LabStatus(enabled=False, services=[])

    async def mode_of(name: str, url: str) -> LabService:
        try:
            response = await http.get(f"{url}/admin/failure", headers=_headers(settings))
            response.raise_for_status()
            return LabService(name=name, mode=response.json()["mode"], reachable=True)
        except (httpx.HTTPError, KeyError, ValueError):
            return LabService(name=name, mode=None, reachable=False)

    services = await asyncio.gather(*(mode_of(n, u) for n, u in settings.lab_targets.items()))
    return LabStatus(enabled=True, services=list(services))


class FailureRequest(BaseModel):
    service: str = Field(min_length=1, max_length=100)
    mode: FailureMode


@router.post("/lab/failure", response_model=LabService)
async def set_failure(body: FailureRequest, http: LabHttpDep) -> LabService:
    settings = _enabled(get_settings())
    url = settings.lab_targets.get(body.service)
    if url is None:
        raise NotFoundError(f"'{body.service}' is not a lab target")
    try:
        response = await http.post(
            f"{url}/admin/failure", json={"mode": body.mode}, headers=_headers(settings)
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(
            "lab_failure_change_failed", service=body.service, error_type=type(exc).__name__
        )
        raise LabTargetUnavailable(f"Could not change the failure mode of {body.service}") from exc
    logger.info("lab_failure_mode_set", service=body.service, mode=body.mode)
    return LabService(name=body.service, mode=body.mode, reachable=True)


class TrafficRequest(BaseModel):
    requests: int = Field(default=50, ge=1, le=300)


class TrafficAccepted(BaseModel):
    target: str
    requests: int


async def send_traffic(url: str, count: int) -> None:
    """Sequential demo traffic; failures are expected during incidents and ignored."""
    ok = 0
    async with httpx.AsyncClient(timeout=30.0) as client:
        for _ in range(count):
            with contextlib.suppress(httpx.HTTPError):
                ok += (await client.post(f"{url}/checkout", json=DEMO_CART)).status_code == 201
    logger.info("lab_traffic_sent", requests=count, succeeded=ok)


@router.post("/lab/traffic", response_model=TrafficAccepted, status_code=202)
async def generate_traffic(body: TrafficRequest, background: BackgroundTasks) -> TrafficAccepted:
    settings = _enabled(get_settings())
    url = settings.lab_targets.get(settings.lab_traffic_target)
    if url is None:
        raise NotFoundError("No traffic target configured")
    background.add_task(send_traffic, url, body.requests)
    return TrafficAccepted(target=settings.lab_traffic_target, requests=body.requests)
