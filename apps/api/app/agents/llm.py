"""Optional LLM, configured by LLM_PROVIDER / LLM_MODEL / LLM_API_KEY.

The agent's reasoning is deterministic and works with no LLM at all
(``LLM_PROVIDER=none``, the default). When a provider is configured, the LLM is
used for two narrow jobs, and its output is always labelled as model-generated:

  * picking the service out of a free-text question when no known service
    name appears in it, and
  * writing a short human summary of the deterministic findings.

It never decides the root cause, the confidence, or which tools to call.
"""

from __future__ import annotations

import re
from typing import Protocol

import httpx
import structlog

from app.config import Settings
from app.metrics import LLM_ERRORS, LLM_TOKENS

logger = structlog.get_logger(__name__)

SUMMARY_SYSTEM = (
    "You summarise incident investigations for on-call engineers. Use ONLY the facts, "
    "hypotheses and conclusion provided. Do not add facts, numbers, causes or documents "
    "that are not in the input. If evidence is missing, say so. At most 120 words."
)


class LLMUnavailable(RuntimeError):
    pass


class LLM(Protocol):
    name: str

    async def complete(self, system: str, user: str, max_tokens: int = 400) -> str: ...


class OpenAICompatibleLLM:
    """OpenAI chat completions API (also works with OpenAI-compatible gateways)."""

    def __init__(self, model: str, api_key: str, base_url: str, timeout: float) -> None:
        self.name = f"openai:{model}"
        self.model, self._key, self.base_url, self.timeout = (
            model,
            api_key,
            base_url.rstrip("/"),
            timeout,
        )

    async def complete(self, system: str, user: str, max_tokens: int = 400) -> str:
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        data = await _post(
            f"{self.base_url}/chat/completions",
            {"Authorization": f"Bearer {self._key}"},
            payload,
            self.timeout,
        )
        usage = data.get("usage", {})
        LLM_TOKENS.labels(kind="input").inc(usage.get("prompt_tokens", 0))
        LLM_TOKENS.labels(kind="output").inc(usage.get("completion_tokens", 0))
        return data["choices"][0]["message"]["content"].strip()


class AnthropicLLM:
    """Anthropic Messages API."""

    def __init__(self, model: str, api_key: str, base_url: str, timeout: float) -> None:
        self.name = f"anthropic:{model}"
        self.model, self._key, self.base_url, self.timeout = (
            model,
            api_key,
            base_url.rstrip("/"),
            timeout,
        )

    async def complete(self, system: str, user: str, max_tokens: int = 400) -> str:
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {"x-api-key": self._key, "anthropic-version": "2023-06-01"}
        data = await _post(f"{self.base_url}/v1/messages", headers, payload, self.timeout)
        usage = data.get("usage", {})
        LLM_TOKENS.labels(kind="input").inc(usage.get("input_tokens", 0))
        LLM_TOKENS.labels(kind="output").inc(usage.get("output_tokens", 0))
        return "".join(b.get("text", "") for b in data.get("content", [])).strip()


async def _post(url: str, headers: dict[str, str], payload: dict, timeout: float) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        # Never include the body or headers: they can echo the API key.
        LLM_ERRORS.labels(error_type=type(exc).__name__).inc()
        raise LLMUnavailable(f"LLM request failed: {type(exc).__name__}") from exc


def build_llm(settings: Settings) -> LLM | None:
    """None means deterministic-only mode (no provider, or provider without a key)."""
    provider = settings.llm_provider.lower()
    if provider in {"", "none"}:
        return None
    key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else ""
    if not key:
        logger.warning("llm_disabled", reason="LLM_API_KEY not set", provider=provider)
        return None
    timeout = float(settings.llm_timeout_seconds)
    if provider == "openai":
        return OpenAICompatibleLLM(
            settings.llm_model, key, settings.llm_base_url or "https://api.openai.com/v1", timeout
        )
    if provider == "anthropic":
        return AnthropicLLM(
            settings.llm_model, key, settings.llm_base_url or "https://api.anthropic.com", timeout
        )
    raise ValueError(f"unsupported LLM_PROVIDER '{settings.llm_provider}'")


async def extract_service(llm: LLM, query: str, known: list[str]) -> str | None:
    """Ask the LLM to choose one of the known services; anything else is discarded."""
    answer = await llm.complete(
        "Answer with exactly one service name from the list, or 'none'.",
        f"Services: {', '.join(known)}\nQuestion: {query}",
        max_tokens=10,
    )
    word = re.sub(r"[^a-z0-9_-]", "", answer.strip().lower())
    return word if word in known else None
