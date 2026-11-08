"""Checkout service: the representative business flow OpsPilot investigates.

POST /checkout
  1. looks up the user in the users service
  2. loads the cart / prices from the (simulated) database
  3. charges the payment through the payments service
  4. writes the order

Normal p95 is roughly 200 ms. With FAILURE_MODE=db every query gains ~900 ms,
p95 climbs to ~2 s and slow-query warnings appear: the primary demo scenario.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import httpx
import structlog
from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel, Field

from opsdemo.app import (
    ContextDep,
    WorkloadContext,
    WorkloadError,
    create_workload_app,
    inject_request_failures,
)
from opsdemo.config import WorkloadSettings, load_settings

logger = structlog.get_logger("checkout")


class CartItem(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, le=100)
    unit_price_cents: int = Field(gt=0, le=1_000_000)


class CheckoutRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    items: list[CartItem] = Field(min_length=1, max_length=50)


class CheckoutResult(BaseModel):
    order_id: str
    status: str
    user_id: str
    amount_cents: int
    payment_id: str


async def call_dependency(
    ctx: WorkloadContext,
    client: httpx.AsyncClient,
    target: str,
    method: str,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    """Call another service, recording latency and mapping transport failures to 5xx."""
    service = ctx.metrics.service
    start = time.perf_counter()
    outcome = "error"
    try:
        response = await client.request(method, url, **kwargs)
        outcome = "server_error" if response.status_code >= 500 else "ok"
        return response
    except httpx.TimeoutException as exc:
        outcome = "timeout"
        logger.error("dependency_timeout", target=target, error_type=type(exc).__name__)
        raise WorkloadError(504, "DEPENDENCY_TIMEOUT", f"{target} did not respond in time") from exc
    except httpx.TransportError as exc:
        logger.error("dependency_unreachable", target=target, error_type=type(exc).__name__)
        raise WorkloadError(502, "DEPENDENCY_UNAVAILABLE", f"{target} is unavailable") from exc
    finally:
        ctx.metrics.downstream_latency.labels(
            service=service, target=target, outcome=outcome
        ).observe(time.perf_counter() - start)


def raise_for_dependency_error(target: str, response: httpx.Response) -> None:
    if response.status_code >= 500:
        logger.error("dependency_error", target=target, status=response.status_code)
        raise WorkloadError(502, "DEPENDENCY_ERROR", f"{target} returned an error")


def create_app(
    settings: WorkloadSettings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or load_settings("checkout", "1.8.2")
    app = create_workload_app(settings, title="OpsPilot demo: checkout", transport=transport)

    @app.post(
        "/checkout",
        status_code=201,
        dependencies=[Depends(inject_request_failures)],
    )
    async def checkout(body: CheckoutRequest, ctx: ContextDep, request: Request) -> CheckoutResult:
        client: httpx.AsyncClient = request.app.state.http

        user_response = await call_dependency(
            ctx, client, "users", "GET", f"{settings.users_url}/users/{body.user_id}"
        )
        raise_for_dependency_error("users", user_response)
        if user_response.status_code == 404:
            raise WorkloadError(422, "UNKNOWN_USER", f"User {body.user_id} does not exist")

        await ctx.db.query("select_cart_items", base_ms=(15, 50))
        amount_cents = sum(item.quantity * item.unit_price_cents for item in body.items)
        order_id = f"ord_{uuid.UUID(int=ctx.rng.getrandbits(128)).hex[:16]}"

        payment_response = await call_dependency(
            ctx,
            client,
            "payments",
            "POST",
            f"{settings.payments_url}/payments",
            json={"order_id": order_id, "user_id": body.user_id, "amount_cents": amount_cents},
        )
        raise_for_dependency_error("payments", payment_response)
        if payment_response.status_code == 402:
            raise WorkloadError(402, "PAYMENT_DECLINED", "Payment was declined")

        await ctx.db.query("insert_order", base_ms=(5, 20))
        payment_id = payment_response.json()["payment_id"]
        logger.info(
            "checkout_completed",
            order_id=order_id,
            amount_cents=amount_cents,
            items=len(body.items),
        )
        return CheckoutResult(
            order_id=order_id,
            status="confirmed",
            user_id=body.user_id,
            amount_cents=amount_cents,
            payment_id=payment_id,
        )

    return app


app = create_app()
