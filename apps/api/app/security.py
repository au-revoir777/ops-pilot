"""Request-level security controls: API key, investigation concurrency, log redaction.

API key
    When ``API_KEY`` is set, every ``/api/*`` request must send it in
    ``X-API-Key``. The web UI's server-side proxy adds it, so it never reaches
    the browser. Liveness, readiness and Prometheus ``/metrics`` stay open for
    probes. Without a key the API is open, which is allowed only outside
    production (``Settings`` refuses to start production without one).

Concurrency
    An investigation runs the whole agent (many tool calls, optionally an LLM).
    A per-process cap turns a flood of requests into fast 429s instead of a
    pile-up of slow, expensive runs.

Log redaction
    A structlog processor masks values of secret-looking keys and credentials
    embedded in strings, as a last line of defence for anything logged by
    mistake.
"""

from __future__ import annotations

import asyncio
import hmac
import re
from collections.abc import AsyncIterator, MutableMapping
from typing import Annotated, Any

import structlog
from fastapi import Depends, Header

from app.config import get_settings
from app.services.exceptions import OpsPilotError

logger = structlog.get_logger(__name__)

API_KEY_HEADER = "X-API-Key"


class Unauthorized(OpsPilotError):
    code = "UNAUTHORIZED"
    status_code = 401
    public_message = True


class TooManyInvestigations(OpsPilotError):
    code = "TOO_MANY_INVESTIGATIONS"
    status_code = 429
    public_message = True


async def require_api_key(
    x_api_key: Annotated[str | None, Header(alias=API_KEY_HEADER)] = None,
) -> None:
    expected = get_settings().api_key
    if expected is None:
        return  # open mode (development only; see Settings)
    supplied = (x_api_key or "").encode()
    # Constant-time comparison: response timing reveals nothing about the key.
    if not hmac.compare_digest(supplied, expected.get_secret_value().encode()):
        raise Unauthorized(f"Missing or invalid {API_KEY_HEADER} header")


_slots: asyncio.Semaphore | None = None
_slots_size = 0


def _semaphore() -> asyncio.Semaphore:
    global _slots, _slots_size
    size = get_settings().max_concurrent_investigations
    if _slots is None or _slots_size != size:
        _slots, _slots_size = asyncio.Semaphore(size), size
    return _slots


async def investigation_slot() -> AsyncIterator[None]:
    """Hold one of the investigation slots for the duration of the request."""
    slots = _semaphore()
    if slots.locked():
        logger.warning("investigation_rejected", reason="concurrency limit")
        raise TooManyInvestigations(
            "Too many investigations are running; try again when one finishes"
        )
    async with slots:
        yield


InvestigationSlotDep = Annotated[None, Depends(investigation_slot)]


# --- Log redaction -----------------------------------------------------------

_SECRET_KEY = re.compile(
    r"(pass(word|wd)?|secret|token|api[_-]?key|authorization|cookie|credential|private[_-]?key)",
    re.IGNORECASE,
)
_SECRET_IN_TEXT = [
    (re.compile(r"(\b[a-z][a-z0-9+.-]*://[^:\s/@]+:)[^@\s]+@", re.I), r"\1[REDACTED]@"),
    (re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [REDACTED]"),
    (re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_-]{16,}"), "[REDACTED]"),
]
_SAFE_KEYS = {"event", "logger", "level", "timestamp", "request_id", "service", "version"}


def _redact_text(value: str) -> str:
    for pattern, replacement in _SECRET_IN_TEXT:
        value = pattern.sub(replacement, value)
    return value


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return {
            k: "[REDACTED]" if _SECRET_KEY.search(str(k)) else _redact(v) for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return type(value)(_redact(v) for v in value)
    return value


def redact_secrets(_logger: Any, _method: str, event_dict: MutableMapping[str, Any]):
    """structlog processor: mask secret-looking fields and inline credentials."""
    for key in list(event_dict):
        if key in _SAFE_KEYS:
            continue
        if _SECRET_KEY.search(key):
            event_dict[key] = "[REDACTED]"
        else:
            event_dict[key] = _redact(event_dict[key])
    if isinstance(event_dict.get("event"), str):
        event_dict["event"] = _redact_text(event_dict["event"])
    return event_dict
