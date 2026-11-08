"""Knowledge-base repository: documents, chunks and vector search. Never commits."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.knowledge import Document, DocumentChunk, DocumentType


@dataclass(frozen=True)
class ChunkMatch:
    chunk: DocumentChunk
    document: Document
    score: float  # cosine similarity in [-1, 1]; 1 = identical direction


class KnowledgeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_source(self, source: str) -> Document | None:
        result = await self.session.execute(select(Document).where(Document.source == source))
        return result.scalar_one_or_none()

    async def list_documents(self) -> Sequence[tuple[Document, int]]:
        stmt = (
            select(Document, func.count(DocumentChunk.id))
            .outerjoin(DocumentChunk)
            .group_by(Document.id)
            .order_by(Document.source)
        )
        result = await self.session.execute(stmt)
        return [(doc, count) for doc, count in result.all()]

    async def sources(self) -> set[str]:
        return set((await self.session.execute(select(Document.source))).scalars())

    def add_document(self, document: Document) -> Document:
        self.session.add(document)
        return document

    async def replace_chunks(self, document: Document, chunks: list[DocumentChunk]) -> None:
        await self.session.flush()
        await self.session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document.id)
        )
        for chunk in chunks:
            chunk.document_id = document.id
            self.session.add(chunk)

    async def delete_sources(self, sources: set[str]) -> int:
        if not sources:
            return 0
        result = await self.session.execute(delete(Document).where(Document.source.in_(sources)))
        return result.rowcount or 0

    async def search(
        self,
        embedding: list[float],
        *,
        limit: int,
        doc_types: Sequence[DocumentType] | None = None,
        services: Sequence[str] | None = None,
    ) -> list[ChunkMatch]:
        """Nearest chunks by cosine distance, with metadata filters applied in SQL.

        pgvector's iterative index scan keeps the HNSW index useful when filters
        discard many candidates (otherwise filtering after the ANN step could
        return fewer than ``limit`` rows).
        """
        await self.session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        distance = DocumentChunk.embedding.cosine_distance(embedding)
        stmt = select(DocumentChunk, Document, (1 - distance).label("score")).join(Document)
        if doc_types:
            stmt = stmt.where(Document.doc_type.in_(list(doc_types)))
        if services:
            stmt = stmt.where(Document.services.overlap(list(services)))
        stmt = stmt.order_by(distance).limit(limit)
        result = await self.session.execute(stmt)
        return [ChunkMatch(chunk, doc, float(score)) for chunk, doc, score in result.all()]

    async def count_chunks(self, document_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(DocumentChunk.document_id == document_id)
        return int((await self.session.execute(stmt)).scalar_one())
