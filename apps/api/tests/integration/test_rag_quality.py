"""Retrieval quality with the real embedding model (marker: evaluation).

    pytest -m evaluation        # downloads BAAI/bge-small-en-v1.5 on first run

Ingests the shipped knowledge base into the test database with the local
model, then scores the labelled questions in tests/fixtures/rag_eval.yml.
Thresholds sit just below the measured baseline (see the Phase 4 report), so a
regression in chunking, embeddings or ranking fails loudly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.config import Settings
from app.rag.embeddings import LocalEmbedder
from app.rag.evaluate import evaluate
from app.rag.ingest import IngestionService
from app.rag.retrieval import RetrievalService

pytestmark = pytest.mark.evaluation

ROOT = Path(__file__).resolve().parents[4]
DATASET = yaml.safe_load((ROOT / "tests/fixtures/rag_eval.yml").read_text(encoding="utf-8"))


async def test_retrieval_quality_with_local_model(db_session):
    settings = Settings(_env_file=None)
    embedder = LocalEmbedder(settings.embedding_model)
    await IngestionService(db_session, embedder, settings).ingest_directory(ROOT / "docs/knowledge")

    report = await evaluate(
        RetrievalService(db_session, embedder, settings),
        DATASET,
        k=5,
        threshold=settings.rag_similarity_threshold,
    )

    assert report.hit_at_k >= 0.9, report
    assert report.mrr >= 0.75, report
    assert report.threshold_recall >= 0.9, report
    assert report.off_topic_clean >= 0.66, report
