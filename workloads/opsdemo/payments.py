"""Payments service: authorises and captures payments for checkout."""

from __future__ import annotations

import uuid

import httpx
import structlog
from fastapi import Depends, FastAPI
from pydantic import BaseModel, Field

from opsdemo.app import ContextDep, WorkloadError, create_workload_app, inject_request_failures
from opsdemo.config import WorkloadSettings, load_settings

logger = structlog.get_logger("payments")

# Simple, deterministic business rule so declines are reproducible in demos.
MAX_AMOUNT_CENTS = 1_000_000


class PaymentRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=64)
    amount_cents: int = Field(gt=0)


class PaymentResult(BaseModel):
    payment_id: str
    order_id: str
    status: str
    amount_cents: int


def create_app(
    settings: WorkloadSettings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or load_settings("payments", "2.1.0")
    app = create_workload_app(settings, title="OpsPilot demo: payments", transport=transport)

    @app.post(
        "/payments",
        status_code=201,
        dependencies=[Depends(inject_request_failures)],
    )
    async def create_payment(body: PaymentRequest, ctx: ContextDep) -> PaymentResult:
        await ctx.simulate_work(20, 50)  # card network round trip
        if body.amount_cents > MAX_AMOUNT_CENTS:
            logger.info("payment_declined", order_id=body.order_id, reason="amount_limit")
            raise WorkloadError(402, "PAYMENT_DECLINED", "Payment declined")
        await ctx.db.query("insert_payment", base_ms=(5, 20))
        payment_id = f"pay_{uuid.UUID(int=ctx.rng.getrandbits(128)).hex[:16]}"
        logger.info("payment_captured", order_id=body.order_id, payment_id=payment_id)
        return PaymentResult(
            payment_id=payment_id,
            order_id=body.order_id,
            status="captured",
            amount_cents=body.amount_cents,
        )

    return app


app = create_app()
