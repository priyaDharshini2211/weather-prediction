"""Embedding of document chunks (at upload time, and self-healing for documents indexed with another/no model)."""
import logging

from django.conf import settings

from chat.models import Document

from .embeddings import get_embedder

logger = logging.getLogger(__name__)


def embed_texts(texts: list[str]) -> list[list[float]]:
    return get_embedder().embed_documents(texts)


def ensure_embedded(document: Document, force: bool = False) -> int:
    """Embeds every chunk that has no vector, or all chunks if the document was indexed with a different model.
    Idempotent; returns the number of chunks (re)embedded."""
    model = settings.EMBEDDING_MODEL
    if not force and document.embedding_model == model and not document.chunks.filter(embedding__isnull=True).exists():
        return 0  # the common case: one cheap query, no vectors loaded

    chunks = list(document.chunks.all())
    stale = chunks if (force or document.embedding_model != model) else [c for c in chunks if c.embedding is None]
    if not stale:
        return 0

    vectors = embed_texts([c.text for c in stale])
    for chunk, vector in zip(stale, vectors):
        chunk.embedding = vector
    type(stale[0]).objects.bulk_update(stale, ["embedding"], batch_size=100)
    Document.objects.filter(pk=document.pk).update(embedding_model=model)
    document.embedding_model = model
    logger.info("Embedded %d chunk(s) of document %s with %s", len(stale), document.pk, model)
    return len(stale)
