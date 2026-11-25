"""Hybrid retrieval over one document: dense vectors (pgvector) + BM25, merged with Reciprocal Rank Fusion.

Why both: embeddings bridge vocabulary ("which database?" -> "PostgreSQL") while BM25 nails exact tokens that embeddings
blur (names, "C++", "CGPA 8.4"). RRF merges the two rankings without having to calibrate their incompatible score scales.
An optional cross-encoder re-ranks the fused candidates.

BM25 is implemented directly with a *smoothed* IDF: the classic Okapi IDF goes negative/zero on tiny corpora such as a
one-page resume split into a handful of chunks.
"""
import logging
import math
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass, field

from django.conf import settings
from django.db.models import BooleanField, ExpressionWrapper, Q

from chat.models import Document, DocumentChunk

from . import vectorstore
from .embeddings import EmbeddingError, get_embedder
from .indexing import ensure_embedded

logger = logging.getLogger(__name__)

STOPWORDS = frozenset(
    "a an and are as at be by for from has have he her his how i in is it its me my of on or she that the their there "
    "they this to was were what when where which who whom why with you your do does did about tell can could please".split()
)
K1, B = 1.5, 0.75
RRF_K = 60


@dataclass
class Passage:
    chunk_id: int
    index: int
    page: int | None
    heading: str
    text: str
    score: float  # final ranking score (fused, or re-ranker score)
    similarity: float | None = None  # dense cosine similarity
    bm25: float | None = None


@dataclass
class Retrieval:
    passages: list[Passage]
    trace: dict = field(default_factory=dict)


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9+#.]+", text.lower()) if t not in STOPWORDS and len(t) > 1]


def bm25_scores(corpus: list[list[str]], query: list[str]) -> list[float]:
    n_docs = len(corpus)
    avg_len = sum(len(doc) for doc in corpus) / n_docs or 1
    doc_freq = Counter(term for doc in corpus for term in set(doc))

    scores = []
    for doc in corpus:
        counts, length, score = Counter(doc), len(doc), 0.0
        for term in set(query):
            tf = counts.get(term, 0)
            if not tf:
                continue
            idf = math.log(1 + (n_docs - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            score += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / avg_len))
        scores.append(score)
    return scores


def reciprocal_rank_fusion(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    """rankings: lists of ids, best first. Returns id -> fused score."""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            fused[item] = fused.get(item, 0.0) + 1.0 / (k + rank)
    return fused


_reranker = None
_reranker_lock = threading.Lock()


def _rerank(query: str, passages: list[Passage]) -> list[Passage]:
    global _reranker
    with _reranker_lock:
        if _reranker is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            _reranker = TextCrossEncoder(settings.RERANK_MODEL, cache_dir=settings.EMBEDDING_CACHE_DIR)
    scores = list(_reranker.rerank(query, [p.text for p in passages]))
    for passage, score in zip(passages, scores):
        passage.score = float(score)
    return sorted(passages, key=lambda p: p.score, reverse=True)


def _contextual_query(question: str, history: list[dict] | None) -> str:
    """A terse follow-up ("and her education?") is meaningless alone, so prepend the previous user question."""
    if history and len(tokenize(question)) <= 4:
        previous = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")
        if previous and previous != question:
            return f"{previous[:300]} {question}"
    return question


def retrieve(document: Document, question: str, history: list[dict] | None = None, top_k: int | None = None, mode: str = "hybrid") -> Retrieval:
    """`mode` is "hybrid" (production) or "dense" / "lexical"; the latter two exist for `manage.py evaluate_rag`."""
    started = time.perf_counter()
    top_k = top_k or settings.RETRIEVAL_TOP_K
    candidates = settings.RETRIEVAL_CANDIDATES
    query = _contextual_query(question, history)
    rows = DocumentChunk.objects.filter(document=document).defer("embedding").annotate(
        unembedded=ExpressionWrapper(Q(embedding__isnull=True), output_field=BooleanField())
    )
    chunks = {c.id: c for c in rows}  # one query: vectors stay in the database, we only learn which chunks lack one
    trace: dict = {"embedding_model": settings.EMBEDDING_MODEL, "chunks_in_document": len(chunks)}
    if not chunks:
        return Retrieval([], trace)

    # --- dense (pgvector) ---
    dense: list[tuple[int, float]] = []
    try:
        if mode == "lexical":
            raise EmbeddingError("dense retrieval disabled")
        if document.embedding_model != settings.EMBEDDING_MODEL or any(c.unembedded for c in chunks.values()):
            trace["chunks_embedded_now"] = ensure_embedded(document)  # self-heal: old document or changed model
        dense = vectorstore.search(document.id, get_embedder().embed_query(query), candidates)
    except EmbeddingError as error:
        logger.warning("Dense retrieval unavailable, falling back to BM25 only: %s", error)
        trace["dense_error"] = str(error)[:200]
    similarity = dict(dense)

    # --- lexical (BM25) ---
    ordered = list(chunks.values())
    lexical_terms = tokenize(query)
    lexical: list[tuple[int, float]] = []
    if lexical_terms and mode != "dense":
        scores = bm25_scores([tokenize(c.text) for c in ordered], lexical_terms)
        lexical = sorted(((c.id, s) for c, s in zip(ordered, scores) if s > 0), key=lambda r: r[1], reverse=True)[:candidates]
    bm25 = dict(lexical)

    # --- fuse, then drop candidates with neither a convincing semantic nor any lexical match ---
    fused = reciprocal_rank_fusion([[i for i, _ in dense], [i for i, _ in lexical]])
    relevant = [i for i in fused if similarity.get(i, 0.0) >= settings.RETRIEVAL_MIN_SIMILARITY or i in bm25]
    relevant.sort(key=lambda i: fused[i], reverse=True)

    passages = [
        Passage(i, chunks[i].index, chunks[i].page, chunks[i].heading, chunks[i].text, fused[i], similarity.get(i), bm25.get(i))
        for i in relevant[: max(top_k, 10) if settings.RERANK_ENABLED else top_k]
    ]
    if settings.RERANK_ENABLED and len(passages) > 1:
        try:
            passages = _rerank(query, passages)
        except Exception:  # model download / ONNX problems must not break answering
            logger.exception("Re-ranking failed; keeping fused order")
    passages = passages[:top_k]

    trace.update(
        mode="hybrid" if dense else "lexical-only",
        dense_hits=len(dense),
        lexical_hits=len(lexical),
        returned=len(passages),
        top_similarity=round(max(similarity.values()), 3) if similarity else None,
        reranked=settings.RERANK_ENABLED,
        ms=round((time.perf_counter() - started) * 1000),
    )
    return Retrieval(passages, trace)
