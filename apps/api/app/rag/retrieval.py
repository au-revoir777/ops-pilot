"""Similarity retrieval with metadata filters and evidence provenance.

Ranking:
  1. pgvector returns the nearest ``candidate_pool`` chunks (cosine distance,
     HNSW index) after SQL metadata filters (document type, services).
  2. Chunks below ``min_score`` are dropped; an empty result is a valid answer
     ("no relevant knowledge"), not an error.
  3. At most ``max_per_document`` chunks per document, so one long document
     cannot crowd out the others.
  4. Sorted by score (ties: source, chunk index), truncated to ``top_k``.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.knowledge import DocumentType
from app.db.repositories.knowledge import ChunkMatch, KnowledgeRepository
from app.metrics import RAG_RETRIEVAL_DURATION, RAG_RETRIEVALS
from app.rag.embeddings import Embedder, EmbeddingError
from app.rag.safety import CONTEXT_PREAMBLE, detect_prompt_injection
from app.services.exceptions import KnowledgeUnavailable

logger = structlog.get_logger(__name__)
CANDIDATE_MULTIPLIER = 4
MAX_QUERY_CHARS = 2000


class RetrievalUnavailable(KnowledgeUnavailable):
    """Embedding or database failure; callers report missing evidence."""


@dataclass(frozen=True)
class RetrievedChunk:
    """One piece of evidence with full provenance."""

    document_id: uuid.UUID
    source: str
    title: str
    doc_type: DocumentType
    services: list[str]
    section: str | None
    chunk_index: int
    content: str
    score: float
    flags: list[str] = field(default_factory=list)

    @property
    def citation(self) -> str:
        return f"{self.source}#chunk-{self.chunk_index}"


def rank(
    matches: Sequence[ChunkMatch], *, top_k: int, min_score: float, max_per_document: int
) -> list[ChunkMatch]:
    """Pure ranking step (unit-tested without a database)."""
    ordered = sorted(
        (m for m in matches if m.score >= min_score),
        key=lambda m: (-m.score, m.document.source, m.chunk.chunk_index),
    )
    per_document: dict[uuid.UUID, int] = defaultdict(int)
    selected: list[ChunkMatch] = []
    for match in ordered:
        if per_document[match.document.id] >= max_per_document:
            continue
        per_document[match.document.id] += 1
        selected.append(match)
        if len(selected) == top_k:
            break
    return selected


def to_retrieved(match: ChunkMatch) -> RetrievedChunk:
    return RetrievedChunk(
        document_id=match.document.id,
        source=match.document.source,
        title=match.document.title,
        doc_type=match.document.doc_type,
        services=list(match.document.services),
        section=match.chunk.section,
        chunk_index=match.chunk.chunk_index,
        content=match.chunk.content,
        score=round(match.score, 4),
        flags=detect_prompt_injection(match.chunk.content),
    )


class RetrievalService:
    def __init__(self, session: AsyncSession, embedder: Embedder, settings: Settings) -> None:
        self.repo = KnowledgeRepository(session)
        self.embedder = embedder
        self.settings = settings

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int | None = None,
        doc_types: Sequence[DocumentType] | None = None,
        services: Sequence[str] | None = None,
        min_score: float | None = None,
    ) -> list[RetrievedChunk]:
        query = " ".join(query.split())[:MAX_QUERY_CHARS]
        if not query:
            RAG_RETRIEVALS.labels(outcome="empty").inc()
            return []
        top_k = top_k or self.settings.rag_top_k
        threshold = self.settings.rag_similarity_threshold if min_score is None else min_score

        start = time.perf_counter()
        try:
            vector = await asyncio.to_thread(self.embedder.embed_query, query)
            matches = await self.repo.search(
                vector,
                limit=top_k * CANDIDATE_MULTIPLIER,
                doc_types=doc_types,
                services=services,
            )
        except (EmbeddingError, SQLAlchemyError) as exc:
            RAG_RETRIEVALS.labels(outcome="error").inc()
            logger.warning("rag_retrieval_failed", error_type=type(exc).__name__)
            raise RetrievalUnavailable("knowledge retrieval is unavailable") from exc
        finally:
            RAG_RETRIEVAL_DURATION.observe(time.perf_counter() - start)

        ranked = rank(
            matches,
            top_k=top_k,
            min_score=threshold,
            max_per_document=self.settings.rag_max_chunks_per_document,
        )
        results = [to_retrieved(m) for m in ranked]
        RAG_RETRIEVALS.labels(outcome="hit" if results else "empty").inc()
        flagged = [r.citation for r in results if r.flags]
        if flagged:
            logger.warning("rag_untrusted_instructions_flagged", citations=flagged)
        return results


def format_context(chunks: Sequence[RetrievedChunk]) -> str:
    """Render retrieved evidence for an LLM prompt, clearly fenced as data."""
    if not chunks:
        return f"{CONTEXT_PREAMBLE}\n\n(no relevant knowledge-base documents were found)"
    parts = [CONTEXT_PREAMBLE]
    for n, chunk in enumerate(chunks, start=1):
        flags = f" flags={','.join(chunk.flags)}" if chunk.flags else ""
        body = chunk.content.replace("</reference>", "&lt;/reference&gt;")
        parts.append(
            f'<reference id="{n}" source="{chunk.citation}" title="{chunk.title}" '
            f'score="{chunk.score}"{flags}>\n{body}\n</reference>'
        )
    return "\n\n".join(parts)
