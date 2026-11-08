"""Knowledge-base ingestion: load -> clean -> chunk -> embed -> store.

Idempotent: a document whose cleaned content and embedding model are unchanged
is skipped; changed documents get all their chunks replaced; documents whose
file disappeared are removed (unless ``prune=False``). Embedding happens before
the database transaction, and all writes commit together.

    python -m app.rag.ingest [--path ../../docs/knowledge] [--no-prune]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models.knowledge import Document, DocumentChunk
from app.db.repositories.knowledge import KnowledgeRepository
from app.metrics import RAG_DOCUMENTS_INGESTED
from app.rag.chunking import chunk_markdown
from app.rag.documents import SourceDocument, load_documents
from app.rag.embeddings import Embedder
from app.services.transactions import transaction

logger = structlog.get_logger(__name__)


@dataclass
class IngestReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    chunks_written: int = 0
    duration_seconds: float = 0.0


class IngestionService:
    def __init__(self, session: AsyncSession, embedder: Embedder, settings: Settings) -> None:
        self.session = session
        self.embedder = embedder
        self.settings = settings
        self.repo = KnowledgeRepository(session)

    def _chunk(self, doc: SourceDocument) -> list[DocumentChunk]:
        chunks = chunk_markdown(
            doc.content, doc.title, self.settings.rag_chunk_size, self.settings.rag_chunk_overlap
        )
        vectors = self.embedder.embed_documents([c.embedding_text(doc.title) for c in chunks])
        return [
            DocumentChunk(
                chunk_index=c.index,
                section=c.section[:500],
                content=c.content,
                word_count=c.word_count,
                embedding=vector,
            )
            for c, vector in zip(chunks, vectors, strict=True)
        ]

    async def ingest_directory(self, root: Path, *, prune: bool = True) -> IngestReport:
        started = time.perf_counter()
        report = IngestReport()
        loaded = load_documents(root)
        report.failed.update(loaded.errors)

        # Decide what changed (read-only), embed outside the write transaction.
        pending: list[tuple[SourceDocument, Document | None, list[DocumentChunk]]] = []
        for doc in loaded.documents:
            existing = await self.repo.get_by_source(doc.source)
            if (
                existing is not None
                and existing.content_hash == doc.content_hash
                and existing.embedding_model == self.embedder.model_name
            ):
                report.unchanged.append(doc.source)
                continue
            chunks = await asyncio.to_thread(self._chunk, doc)
            pending.append((doc, existing, chunks))

        stale = (await self.repo.sources()) - {d.source for d in loaded.documents}
        # A file that failed to parse is not "gone": keep its previous version.
        stale -= set(loaded.errors)

        async with transaction(self.session, "ingest_knowledge_base"):
            for doc, existing, chunks in pending:
                document = existing or self.repo.add_document(
                    Document(source=doc.source, title=doc.title, doc_type=doc.doc_type,
                             content_hash="", content="", embedding_model="")
                )  # fmt: skip
                document.title = doc.title
                document.doc_type = doc.doc_type
                document.services = doc.services
                document.content = doc.content
                document.content_hash = doc.content_hash
                document.metadata_ = doc.metadata
                document.embedding_model = self.embedder.model_name
                await self.repo.replace_chunks(document, chunks)
                report.chunks_written += len(chunks)
                (report.updated if existing else report.added).append(doc.source)
            if prune and stale:
                await self.repo.delete_sources(stale)
                report.removed = sorted(stale)

        report.duration_seconds = round(time.perf_counter() - started, 2)
        for outcome in ("added", "updated", "unchanged", "removed"):
            RAG_DOCUMENTS_INGESTED.labels(outcome=outcome).inc(len(getattr(report, outcome)))
        RAG_DOCUMENTS_INGESTED.labels(outcome="failed").inc(len(report.failed))
        logger.info(
            "knowledge_base_ingested",
            added=len(report.added),
            updated=len(report.updated),
            unchanged=len(report.unchanged),
            removed=len(report.removed),
            failed=len(report.failed),
            chunks=report.chunks_written,
            duration_s=report.duration_seconds,
        )
        return report


async def _main(path: Path, prune: bool) -> IngestReport:
    from app.db.session import build_engine, build_session_factory
    from app.rag.embeddings import build_embedder

    settings = get_settings()
    engine = build_engine(settings)
    try:
        async with build_session_factory(engine)() as session:
            service = IngestionService(session, build_embedder(settings), settings)
            return await service.ingest_directory(path, prune=prune)
    finally:
        await engine.dispose()


def _log_to_stderr() -> None:
    """Keep stdout for the JSON report so it can be piped (e.g. into jq)."""
    import sys

    import structlog

    structlog.configure(logger_factory=structlog.PrintLoggerFactory(sys.stderr))


def main() -> None:
    _log_to_stderr()
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Ingest the OpsPilot knowledge base")
    parser.add_argument("--path", type=Path, default=Path(settings.rag_docs_path))
    parser.add_argument("--no-prune", action="store_true", help="keep documents whose file is gone")
    args = parser.parse_args()
    report = asyncio.run(_main(args.path.resolve(), prune=not args.no_prune))
    print(json.dumps(asdict(report), indent=2))  # noqa: T201 - CLI output
    raise SystemExit(1 if report.failed else 0)


if __name__ == "__main__":
    main()
