"""RAG integration: documents -> embeddings -> pgvector -> retrieval, on real PostgreSQL.

Uses the deterministic hashing embedder so CI needs no model download; the
real model's retrieval quality is measured separately (tests/evaluation and
`python -m app.rag.evaluate`).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models.knowledge import Document, DocumentChunk, DocumentType
from app.rag.embeddings import HashingEmbedder, get_embedder
from app.rag.ingest import IngestionService
from app.rag.retrieval import RetrievalService

KNOWLEDGE_DIR = Path(__file__).resolve().parents[4] / "docs" / "knowledge"
SETTINGS = Settings(_env_file=None, embedding_provider="hashing", rag_similarity_threshold=0.1)


@pytest.fixture
def knowledge_copy(tmp_path) -> Path:
    target = tmp_path / "knowledge"
    shutil.copytree(KNOWLEDGE_DIR, target)
    return target


@pytest.fixture
def embedder() -> HashingEmbedder:
    return HashingEmbedder()


async def ingest(session: AsyncSession, root: Path, embedder, **kwargs):
    return await IngestionService(session, embedder, SETTINGS).ingest_directory(root, **kwargs)


async def count(session: AsyncSession, model) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_ingest_stores_documents_chunks_and_vectors(db_session, knowledge_copy, embedder):
    report = await ingest(db_session, knowledge_copy, embedder)

    assert report.failed == {}
    assert len(report.added) == await count(db_session, Document) >= 10
    assert report.chunks_written == await count(db_session, DocumentChunk)
    dims = await db_session.scalar(
        text("SELECT vector_dims(embedding) FROM document_chunks LIMIT 1")
    )
    assert dims == 384
    doc = await db_session.scalar(
        select(Document).where(Document.source == "runbooks/checkout-service.md")
    )
    assert doc.doc_type is DocumentType.RUNBOOK
    assert doc.services == ["checkout"]
    assert doc.embedding_model == embedder.model_name
    assert doc.metadata_["owner"] == "commerce-platform"


async def test_reingest_is_idempotent_and_tracks_changes(db_session, knowledge_copy, embedder):
    first = await ingest(db_session, knowledge_copy, embedder)
    again = await ingest(db_session, knowledge_copy, embedder)
    assert again.added == again.updated == [] and sorted(again.unchanged) == sorted(first.added)

    runbook = knowledge_copy / "runbooks" / "payments-service.md"
    runbook.write_text(runbook.read_text(encoding="utf-8") + "\n## New section\nExtra.\n", "utf-8")
    (knowledge_copy / "troubleshooting" / "redis-troubleshooting.md").unlink()
    changed = await ingest(db_session, knowledge_copy, embedder)

    assert changed.updated == ["runbooks/payments-service.md"]
    assert changed.removed == ["troubleshooting/redis-troubleshooting.md"]
    assert await count(db_session, Document) == len(first.added) - 1
    # Chunks of the removed document went with it (ON DELETE CASCADE).
    orphans = await db_session.scalar(
        text(
            "SELECT count(*) FROM document_chunks c "
            "LEFT JOIN documents d ON d.id = c.document_id WHERE d.id IS NULL"
        )
    )
    assert orphans == 0


async def test_malformed_file_is_reported_and_previous_version_kept(
    db_session, knowledge_copy, embedder
):
    await ingest(db_session, knowledge_copy, embedder)
    broken = knowledge_copy / "runbooks" / "checkout-service.md"
    broken.write_text("no front matter any more", encoding="utf-8")
    report = await ingest(db_session, knowledge_copy, embedder)
    assert "runbooks/checkout-service.md" in report.failed
    assert "runbooks/checkout-service.md" not in report.removed
    assert await db_session.scalar(
        select(Document.id).where(Document.source == "runbooks/checkout-service.md")
    )


async def test_retrieval_returns_relevant_chunks_with_provenance(
    db_session, knowledge_copy, embedder
):
    await ingest(db_session, knowledge_copy, embedder)
    service = RetrievalService(db_session, embedder, SETTINGS)

    results = await service.retrieve("deployment rollback procedure previous version", top_k=3)
    assert results[0].source == "procedures/deployment-rollback.md"
    assert results == sorted(results, key=lambda r: -r.score)
    assert all(r.citation.startswith(r.source) and r.section for r in results)


async def test_metadata_filters(db_session, knowledge_copy, embedder):
    await ingest(db_session, knowledge_copy, embedder)
    service = RetrievalService(db_session, embedder, SETTINGS)

    postmortems = await service.retrieve(
        "checkout latency", doc_types=[DocumentType.POSTMORTEM], min_score=0.0
    )
    assert postmortems and {r.doc_type for r in postmortems} == {DocumentType.POSTMORTEM}

    payments = await service.retrieve("errors", services=["payments"], min_score=0.0, top_k=10)
    assert payments and all("payments" in r.services for r in payments)

    nothing = await service.retrieve("errors", services=["no-such-service"], min_score=0.0)
    assert nothing == []


async def test_threshold_produces_empty_retrieval(db_session, knowledge_copy, embedder):
    await ingest(db_session, knowledge_copy, embedder)
    service = RetrievalService(db_session, embedder, SETTINGS)
    assert await service.retrieve("zebra quantum marmalade", min_score=0.5) == []


async def test_search_api_end_to_end(app: FastAPI, client: AsyncClient, db_session, knowledge_copy):
    embedder = HashingEmbedder()
    app.dependency_overrides[get_embedder] = lambda: embedder
    await ingest(db_session, knowledge_copy, embedder)

    response = await client.post(
        "/api/knowledge/search",
        json={"query": "slow_query_detected select_cart_items", "top_k": 3, "min_score": 0.05},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["embedding_model"] == embedder.model_name
    first = body["results"][0]
    assert set(first) >= {"source", "citation", "title", "section", "score", "content", "flags"}

    documents = (await client.get("/api/knowledge/documents")).json()
    assert {d["source"] for d in documents} >= {"runbooks/checkout-service.md"}
    assert all(d["chunks"] > 0 for d in documents)

    assert (await client.post("/api/knowledge/search", json={"query": ""})).status_code == 422
