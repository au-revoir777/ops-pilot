"""Edges of the agent: LLM providers, the MCP tool client and report rendering.

These talk to the outside world in production; here every transport is faked,
so the tests pin down the request shapes, the failure handling and what never
leaks (API keys in errors, non-allow-listed tools).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.agents import llm as llm_module
from app.agents.llm import AnthropicLLM, LLMUnavailable, OpenAICompatibleLLM
from app.agents.render import to_markdown
from app.agents.simulation import NOW, ScenarioRetriever, ScenarioToolClient, load_cases
from app.agents.tools import McpToolClient, ToolNotAllowed

SECRET = "sk-test-not-a-real-key-123456"


def fake_http(monkeypatch, handler):
    """Route every httpx.AsyncClient the module creates through `handler`."""
    real = httpx.AsyncClient
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(
        llm_module.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(recording), **kw),
    )
    return seen


class TestLLMProviders:
    async def test_openai_request_shape_and_answer(self, monkeypatch):
        seen = fake_http(monkeypatch, lambda r: httpx.Response(200, json={
            "choices": [{"message": {"content": "  The summary.  "}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        }))  # fmt: skip
        out = await OpenAICompatibleLLM("gpt-x", SECRET, "https://gw.example/v1/", 5).complete(
            "sys", "user"
        )
        assert out == "The summary."
        request = seen[0]
        assert str(request.url) == "https://gw.example/v1/chat/completions"
        assert request.headers["authorization"] == f"Bearer {SECRET}"
        body = json.loads(request.content)
        assert body["temperature"] == 0
        assert [m["role"] for m in body["messages"]] == ["system", "user"]

    async def test_anthropic_request_shape_and_answer(self, monkeypatch):
        seen = fake_http(monkeypatch, lambda r: httpx.Response(200, json={
            "content": [{"type": "text", "text": "Part one. "}, {"type": "text", "text": "Two."}],
            "usage": {"input_tokens": 10, "output_tokens": 3},
        }))  # fmt: skip
        out = await AnthropicLLM("claude-x", SECRET, "https://api.example", 5).complete("sys", "u")
        assert out == "Part one. Two."
        request = seen[0]
        assert str(request.url) == "https://api.example/v1/messages"
        assert request.headers["x-api-key"] == SECRET
        assert json.loads(request.content)["system"] == "sys"

    @pytest.mark.parametrize(
        "response",
        [
            httpx.Response(401, json={"error": f"bad key {SECRET}"}),
            httpx.Response(200, content=b"not json"),
        ],
    )
    async def test_failures_raise_without_leaking_the_key(self, monkeypatch, response):
        fake_http(monkeypatch, lambda r: response)
        llm = OpenAICompatibleLLM("gpt-x", SECRET, "https://gw.example/v1", 5)
        with pytest.raises(LLMUnavailable) as caught:
            await llm.complete("s", "u")
        assert SECRET not in str(caught.value)
        assert str(caught.value).startswith("LLM request failed: ")  # exception type only


class FakeSession:
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.result, self.error, self.calls = result, error, []

    async def call_tool(self, tool: str, arguments: dict[str, Any]):
        self.calls.append(tool)
        if self.error:
            raise self.error
        return self.result


class TestMcpToolClient:
    async def test_rejects_tools_outside_the_allow_list(self):
        session = FakeSession()
        with pytest.raises(ToolNotAllowed):
            await McpToolClient(session).call("restart_database", {})
        assert session.calls == []

    async def test_no_session_means_unavailable(self):
        result = await McpToolClient(None).call("get_service_health", {"service": "checkout"})
        assert result["status"] == "unavailable"
        assert result["errors"][0]["error"] == "mcp_unavailable"

    async def test_structured_result_is_returned(self):
        ok = SimpleNamespace(isError=False, structuredContent={"status": "ok", "health": "ok"})
        result = await McpToolClient(FakeSession(ok)).call("get_service_health", {"service": "x"})
        assert result == {"status": "ok", "health": "ok"}

    async def test_tool_error_is_reported_not_raised(self):
        bad = SimpleNamespace(isError=True, content=[SimpleNamespace(text="invalid service")])
        result = await McpToolClient(FakeSession(bad)).call("get_service_health", {"service": "?"})
        assert result["status"] == "error"
        assert result["errors"][0]["detail"] == "invalid service"

    async def test_transport_failure_mid_run_degrades(self):
        session = FakeSession(error=httpx.ReadTimeout("slow"))
        result = await McpToolClient(session).call("query_metrics", {"query": "up"})
        assert result["status"] == "unavailable"


async def test_markdown_report_keeps_epistemic_sections_apart():
    data = load_cases()
    case = next(c for c in data["cases"] if c["id"] == "poisoned-knowledge")
    from app.agents.graph import InvestigationAgent
    from app.config import Settings

    agent = InvestigationAgent(
        ScenarioToolClient(case["telemetry"]),
        ScenarioRetriever(data["knowledge_sets"]["poisoned"]),
        Settings(_env_file=None, llm_provider="none"),
        now=lambda: NOW,
    )
    md = to_markdown(await agent.run(case["question"]))
    order = [
        "## Conclusion",
        "## Observed facts (telemetry)",
        "## Retrieved evidence (knowledge base)",
        "## Hypotheses and validation",
        "## Recommendations (require human action)",
        "## Trace",
    ]
    positions = [md.index(heading) for heading in order]
    assert positions == sorted(positions)
    assert "not a probability" in md
    assert "FLAGGED: possible_prompt_injection" in md
