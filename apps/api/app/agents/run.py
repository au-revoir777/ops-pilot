"""Run an investigation from the command line against the live stack.

    python -m app.agents.run "Investigate why checkout latency increased"
    python -m app.agents.run "..." --service checkout --minutes 30 --json

Uses DATABASE_URL (RAG), MCP_SERVER_URL / MCP_AUTH_TOKEN (tools) and the
optional LLM_* settings.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import structlog

from app.agents.graph import InvestigationAgent
from app.agents.llm import build_llm
from app.agents.render import to_markdown
from app.agents.tools import connect_mcp
from app.config import Settings, get_settings
from app.db.session import build_engine, build_session_factory
from app.rag.embeddings import build_embedder
from app.rag.retrieval import RetrievalService, RetrievedChunk


class SessionRetriever:
    """Adapter: the agent's KnowledgeRetriever on top of the RAG RetrievalService."""

    def __init__(self, service: RetrievalService) -> None:
        self.service = service

    async def retrieve(self, query: str, services: list[str] | None) -> list[RetrievedChunk]:
        return await self.service.retrieve(query, services=services)


async def investigate(settings: Settings, query: str, service: str | None, minutes: int | None):
    engine = build_engine(settings)
    token = settings.mcp_auth_token.get_secret_value() if settings.mcp_auth_token else None
    try:
        async with (
            build_session_factory(engine)() as session,
            connect_mcp(settings.mcp_server_url, token) as tools,
        ):
            retriever = SessionRetriever(
                RetrievalService(session, build_embedder(settings), settings)
            )
            agent = InvestigationAgent(tools, retriever, settings, llm=build_llm(settings))
            return await agent.run(query, service=service, window_minutes=minutes)
    finally:
        await engine.dispose()


def main() -> None:
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(sys.stderr))
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("query")
    parser.add_argument("--service")
    parser.add_argument("--minutes", type=int)
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args()
    report = asyncio.run(investigate(get_settings(), args.query, args.service, args.minutes))
    print(report.model_dump_json(indent=2) if args.json else to_markdown(report))  # noqa: T201


if __name__ == "__main__":
    main()
