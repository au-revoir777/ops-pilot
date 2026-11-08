"""Knowledge base models for RAG: source documents and their embedded chunks."""

from __future__ import annotations

import enum
import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum

# Fixed by the embedding model (BAAI/bge-small-en-v1.5; OpenAI is asked for the
# same size). Changing it requires a migration and a full re-ingest (D-027).
EMBEDDING_DIMENSIONS = 384


class DocumentType(enum.StrEnum):
    RUNBOOK = "runbook"
    ARCHITECTURE = "architecture"
    TROUBLESHOOTING = "troubleshooting"
    POSTMORTEM = "postmortem"
    PROCEDURE = "procedure"


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One source file in the knowledge base (the provenance unit)."""

    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_services", "services", postgresql_using="gin"),)

    # Path relative to the knowledge base root, e.g. "runbooks/checkout.md".
    source: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    doc_type: Mapped[DocumentType] = mapped_column(
        pg_enum(DocumentType, "document_type"), nullable=False, index=True
    )
    services: Mapped[list[str]] = mapped_column(
        ARRAY(String(100)), nullable=False, server_default="{}"
    )
    # sha256 of the cleaned content: unchanged files are skipped on re-ingest.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Front-matter extras such as tags and owner. Genuinely free-form.
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)

    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document",
        order_by="DocumentChunk.chunk_index",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DocumentChunk(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A retrievable slice of a document with its embedding."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index"),
        # Approximate nearest neighbour search on cosine distance.
        Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # Heading trail, e.g. "Checkout runbook > Mitigation", kept for provenance.
    section: Mapped[str | None] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)

    document: Mapped[Document] = relationship(back_populates="chunks")
