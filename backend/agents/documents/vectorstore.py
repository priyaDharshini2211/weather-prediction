"""Nearest-neighbour search over a document's chunk embeddings.

PostgreSQL (Neon): cosine distance (`<=>`) served by the HNSW index created in migration 0002.
Other databases (SQLite in tests / local dev): exact search in NumPy - identical results, no index.
"""
import numpy as np
from django.db import connection, transaction

from chat.models import DocumentChunk


def search(document_id: int, query_vector: list[float], limit: int) -> list[tuple[int, float]]:
    """Returns [(chunk_id, cosine_similarity)] best first, for chunks that have an embedding."""
    if connection.vendor == "postgresql":
        return _search_pgvector(document_id, query_vector, limit)
    return _search_numpy(document_id, query_vector, limit)


def _search_pgvector(document_id: int, query_vector: list[float], limit: int) -> list[tuple[int, float]]:
    literal = "[" + ",".join(f"{x:.7g}" for x in query_vector) + "]"
    with transaction.atomic(), connection.cursor() as cursor:
        # pgvector >= 0.8: keep scanning the HNSW graph until `limit` rows pass the document filter.
        cursor.execute("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true), set_config('hnsw.ef_search', '100', true)")
        cursor.execute(
            "SELECT id, 1 - (embedding <=> %s::vector) AS similarity FROM chat_documentchunk "
            "WHERE document_id = %s AND embedding IS NOT NULL ORDER BY embedding <=> %s::vector LIMIT %s",
            [literal, document_id, literal, limit],
        )
        rows = cursor.fetchall()
    return sorted(((int(chunk_id), float(sim)) for chunk_id, sim in rows), key=lambda r: r[1], reverse=True)


def _search_numpy(document_id: int, query_vector: list[float], limit: int) -> list[tuple[int, float]]:
    rows = list(DocumentChunk.objects.filter(document_id=document_id, embedding__isnull=False).values_list("id", "embedding"))
    if not rows:
        return []
    similarities = np.asarray([r[1] for r in rows], dtype=np.float32) @ np.asarray(query_vector, dtype=np.float32)
    order = np.argsort(-similarities)[:limit]
    return [(rows[i][0], float(similarities[i])) for i in order]
