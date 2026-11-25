"""Embedding models behind one small interface.

- `fastembed` (default): runs a quantised open-source ONNX model (BAAI/bge-small-en-v1.5) in-process. No API key, no GPU, no torch.
- `openai`: any OpenAI-compatible embeddings endpoint (hosted or Ollama) for teams that prefer an API.

Vectors are L2-normalised, so cosine similarity == dot product.
"""
import logging
import threading
from typing import Protocol

import numpy as np
from django.conf import settings

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    pass


class Embedder(Protocol):
    name: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def _normalise(vectors) -> list[list[float]]:
    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = matrix / np.where(norms == 0, 1, norms)
    return matrix.tolist()


def _check_dimension(vectors: list[list[float]]) -> None:
    if vectors and len(vectors[0]) != settings.EMBEDDING_DIM:
        raise EmbeddingError(
            f"Embedding model '{settings.EMBEDDING_MODEL}' returns {len(vectors[0])}-dim vectors but EMBEDDING_DIM={settings.EMBEDDING_DIM}. "
            "Set EMBEDDING_DIM to match, add a migration for the new dimension and run `python manage.py reembed`."
        )


class FastEmbedEmbedder:
    def __init__(self):
        self.name = settings.EMBEDDING_MODEL
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from fastembed import TextEmbedding

                    logger.info("Loading embedding model %s", self.name)
                    try:
                        self._model = TextEmbedding(self.name, cache_dir=settings.EMBEDDING_CACHE_DIR)
                    except Exception as error:  # download / ONNX failures
                        raise EmbeddingError(f"Could not load embedding model '{self.name}': {error}") from error
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        vectors = _normalise(list(model.embed(texts, batch_size=settings.EMBEDDING_BATCH_SIZE)))
        _check_dimension(vectors)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([settings.EMBEDDING_QUERY_PREFIX + text])[0]


class OpenAICompatibleEmbedder:
    def __init__(self):
        from openai import OpenAI

        self.name = settings.EMBEDDING_MODEL
        self._client = OpenAI(
            base_url=settings.EMBEDDING_BASE_URL or settings.LLM_BASE_URL,
            api_key=settings.EMBEDDING_API_KEY or settings.LLM_API_KEY,
            timeout=settings.LLM_TIMEOUT,
            max_retries=3,
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), settings.EMBEDDING_BATCH_SIZE):
            batch = texts[start : start + settings.EMBEDDING_BATCH_SIZE]
            try:
                response = self._client.embeddings.create(model=self.name, input=batch, dimensions=settings.EMBEDDING_DIM)
            except Exception as error:
                raise EmbeddingError(f"Embedding API request failed: {error}") from error
            vectors.extend(item.embedding for item in response.data)
        vectors = _normalise(vectors) if vectors else []
        _check_dimension(vectors)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


_embedder: Embedder | None = None
_embedder_lock = threading.Lock()


def get_embedder() -> Embedder:
    """Process-wide singleton (the model is loaded once, lazily or by `warm_up`)."""
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                provider = settings.EMBEDDING_PROVIDER
                if provider == "fastembed":
                    _embedder = FastEmbedEmbedder()
                elif provider == "openai":
                    _embedder = OpenAICompatibleEmbedder()
                else:
                    raise EmbeddingError(f"Unknown EMBEDDING_PROVIDER '{provider}' (use 'fastembed' or 'openai').")
    return _embedder


def warm_up() -> None:
    """Load the model now so the first user request does not pay the start-up cost."""
    try:
        get_embedder().embed_query("warm up")
        logger.info("Embedding model ready: %s", settings.EMBEDDING_MODEL)
    except Exception:
        logger.exception("Embedding warm-up failed; it will be retried on first use")
