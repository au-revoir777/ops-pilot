"""Users service: profile lookups used by checkout."""

from __future__ import annotations

import re

import httpx
from fastapi import Depends, FastAPI
from pydantic import BaseModel

from opsdemo.app import ContextDep, WorkloadError, create_workload_app, inject_request_failures
from opsdemo.config import WorkloadSettings, load_settings

# Demo data: users u-1 .. u-1000 exist; anything else is a 404.
_USER_ID = re.compile(r"^u-(\d{1,4})$")
MAX_USER_NUMBER = 1000


class User(BaseModel):
    user_id: str
    tier: str
    country: str


def lookup_user(user_id: str) -> User | None:
    match = _USER_ID.match(user_id)
    if match is None or not 1 <= int(match.group(1)) <= MAX_USER_NUMBER:
        return None
    number = int(match.group(1))
    return User(
        user_id=user_id,
        tier="premium" if number % 10 == 0 else "standard",
        country=("US", "IN", "DE", "BR")[number % 4],
    )


def create_app(
    settings: WorkloadSettings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or load_settings("users", "1.3.0")
    app = create_workload_app(settings, title="OpsPilot demo: users", transport=transport)

    @app.get("/users/{user_id}", dependencies=[Depends(inject_request_failures)])
    async def get_user(user_id: str, ctx: ContextDep) -> User:
        await ctx.db.query("select_user", base_ms=(5, 20))
        user = lookup_user(user_id)
        if user is None:
            raise WorkloadError(404, "USER_NOT_FOUND", f"User {user_id} not found")
        return user

    return app


app = create_app()
