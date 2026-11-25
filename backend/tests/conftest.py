"""Test doubles: the real embedding model is never downloaded or run in the unit tests."""
import re
import zlib

import numpy as np
import pytest
from django.conf import settings

from agents.documents import embeddings

# Words that a real embedding model treats as near-synonyms; lets tests exercise the dense path where BM25 cannot match.
CONCEPTS = {
    "database": "concept_db", "databases": "concept_db", "postgresql": "concept_db", "mongodb": "concept_db", "sql": "concept_db",
    "university": "concept_school", "college": "concept_school", "education": "concept_school", "degree": "concept_school",
}


class FakeEmbedder:
    """Deterministic bag-of-words hashing embedder (L2-normalised, 384-dim) with a tiny synonym table."""

    name = "fake-embedder"

    def _vector(self, text: str) -> list[float]:
        vector = np.zeros(settings.EMBEDDING_DIM, dtype=np.float32)
        for token in re.findall(r"[a-z0-9+#]+", text.lower()):
            vector[zlib.crc32(CONCEPTS.get(token, token).encode()) % settings.EMBEDDING_DIM] += 1.0
        norm = np.linalg.norm(vector)
        return (vector / norm if norm else vector).tolist()

    def embed_documents(self, texts):
        return [self._vector(t) for t in texts]

    def embed_query(self, text):
        return self._vector(text)


@pytest.fixture(autouse=True)
def fake_embedder(monkeypatch):
    embedder = FakeEmbedder()
    monkeypatch.setattr(embeddings, "_embedder", embedder)
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "fake-embedder")
    monkeypatch.setattr(settings, "RERANK_ENABLED", False)
    return embedder
