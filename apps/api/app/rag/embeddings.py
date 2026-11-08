"""Embedding providers (DECISIONS D-027).

All providers produce L2-normalised vectors of EMBEDDING_DIMENSIONS (384), so
cosine similarity equals the dot product and providers are interchangeable at
the schema level (switching still requires a full re-ingest).

- LocalEmbedder: BAAI/bge-small-en-v1.5 through fastembed (ONNX Runtime, CPU,
  no API key). Queries get bge's retrieval instruction prefix (query_embed).
- OpenAIEmbedder: text-embedding-3-small with ``dimensions=384``.
- HashingEmbedder: deterministic feature hashing of word unigrams/bigrams.
  Lexical only: for tests and offline development, never for real retrieval.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re
from functools import lru_cache
from typing import Protocol

import httpx

from app.config import Settings, get_settings
from app.db.models.knowledge import EMBEDDING_DIMENSIONS


class EmbeddingError(RuntimeError):
    """The embedding provider failed; callers degrade gracefully."""


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def _normalise(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else vector


def _check(vectors: list[list[float]]) -> list[list[float]]:
    for vector in vectors:
        if len(vector) != EMBEDDING_DIMENSIONS:
            raise EmbeddingError(
                f"embedding has {len(vector)} dimensions, schema expects {EMBEDDING_DIMENSIONS}"
            )
    return vectors


class LocalEmbedder:
    dimensions = EMBEDDING_DIMENSIONS

    def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
        self.model_name = model_name
        self._cache_dir = cache_dir
        self._model = None

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding  # heavy import, loaded on first use

            try:
                self._model = TextEmbedding(self.model_name, cache_dir=self._cache_dir)
            except Exception as exc:  # download / ONNX errors
                raise EmbeddingError(f"could not load {self.model_name}") from exc
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = [list(map(float, v)) for v in self._load().embed(texts)]
        return _check([_normalise(v) for v in vectors])

    def embed_query(self, text: str) -> list[float]:
        vector = next(iter(self._load().query_embed([text])))
        return _check([_normalise(list(map(float, vector)))])[0]


class OpenAIEmbedder:
    dimensions = EMBEDDING_DIMENSIONS
    URL = "https://api.openai.com/v1/embeddings"

    def __init__(self, model_name: str, api_key: str, timeout: float = 30.0) -> None:
        self.model_name = model_name
        self._api_key = api_key
        self._timeout = timeout

    def _embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = httpx.post(
                self.URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self.model_name, "input": texts, "dimensions": self.dimensions},
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            # Never include the response body or headers: they may echo the key.
            raise EmbeddingError(f"embedding request failed: {type(exc).__name__}") from exc
        data = sorted(response.json()["data"], key=lambda item: item["index"])
        return _check([_normalise(item["embedding"]) for item in data])

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts) if texts else []

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]


class HashingEmbedder:
    dimensions = EMBEDDING_DIMENSIONS
    model_name = "hashing-unigram-bigram-384"
    _TOKEN = re.compile(r"[a-z0-9_]+")

    def _vector(self, text: str) -> list[float]:
        tokens = self._TOKEN.findall(text.lower())
        features = tokens + [f"{a} {b}" for a, b in itertools.pairwise(tokens)]
        vector = [0.0] * self.dimensions
        for feature in features:
            digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "little") % self.dimensions
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        return _normalise(vector)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


def build_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "hashing":
        return HashingEmbedder()
    if settings.embedding_provider == "openai":
        if settings.embedding_api_key is None:
            raise EmbeddingError("EMBEDDING_API_KEY is required for EMBEDDING_PROVIDER=openai")
        return OpenAIEmbedder(
            settings.embedding_model, settings.embedding_api_key.get_secret_value()
        )
    return LocalEmbedder(settings.embedding_model, settings.embedding_cache_dir)


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    """Process-wide embedder (the local model is loaded once, lazily)."""
    return build_embedder(get_settings())
