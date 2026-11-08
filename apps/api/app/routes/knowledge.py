"""Knowledge-base endpoints: search with provenance, and the document inventory."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.config import get_settings
from app.db.models.knowledge import DocumentType
from app.db.repositories.knowledge import KnowledgeRepository
from app.dependencies import SessionDep
from app.rag.embeddings import Embedder, get_embedder
from app.rag.retrieval import RetrievalService

router = APIRouter()

EmbedderDep = Annotated[Embedder, Depends(get_embedder)]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    doc_types: list[DocumentType] | None = None
    services: list[str] | None = Field(default=None, max_length=20)
    min_score: float | None = Field(default=None, ge=0.0, le=1.0)


class SearchResult(BaseModel):
    source: str
    citation: str
    title: str
    doc_type: DocumentType
    services: list[str]
    section: str | None
    chunk_index: int
    score: float
    content: str
    flags: list[str]


class SearchResponse(BaseModel):
    query: str
    embedding_model: str
    results: list[SearchResult]


class DocumentSummary(BaseModel):
    id: uuid.UUID
    source: str
    title: str
    doc_type: DocumentType
    services: list[str]
    chunks: int
    embedding_model: str
    updated_at: datetime


@router.post("/knowledge/search", response_model=SearchResponse)
async def search_knowledge(
    body: SearchRequest, session: SessionDep, embedder: EmbedderDep
) -> SearchResponse:
    service = RetrievalService(session, embedder, get_settings())
    chunks = await service.retrieve(
        body.query,
        top_k=body.top_k,
        doc_types=body.doc_types,
        services=body.services,
        min_score=body.min_score,
    )
    return SearchResponse(
        query=body.query,
        embedding_model=embedder.model_name,
        results=[
            SearchResult(
                source=c.source,
                citation=c.citation,
                title=c.title,
                doc_type=c.doc_type,
                services=c.services,
                section=c.section,
                chunk_index=c.chunk_index,
                score=c.score,
                content=c.content,
                flags=c.flags,
            )
            for c in chunks
        ],
    )


@router.get("/knowledge/documents", response_model=list[DocumentSummary])
async def list_documents(session: SessionDep) -> list[DocumentSummary]:
    rows = await KnowledgeRepository(session).list_documents()
    return [
        DocumentSummary(
            id=doc.id,
            source=doc.source,
            title=doc.title,
            doc_type=doc.doc_type,
            services=list(doc.services),
            chunks=count,
            embedding_model=doc.embedding_model,
            updated_at=doc.updated_at,
        )
        for doc, count in rows
    ]
