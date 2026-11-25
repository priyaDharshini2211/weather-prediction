"""Measures retrieval quality on a labelled resume so retrieval changes are judged by numbers, not impressions.

    python manage.py evaluate_rag [--top-k 3] [--rerank]

Indexes evals/eval_resume.txt as a temporary document (rolled back afterwards) and compares BM25-only, dense-only
and hybrid retrieval: hit@k / MRR for answerable questions, and the false-positive rate for off-topic ones.
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.test.utils import override_settings

from agents.documents import retrieval as retrieval_module
from agents.documents.indexing import embed_texts
from agents.documents.ingest import extract_text, split_into_chunks
from chat.models import Document, DocumentChunk

EVALS = Path(settings.BASE_DIR) / "evals"


class Command(BaseCommand):
    help = "Evaluate retrieval (dense / BM25 / hybrid) on a labelled resume."

    def add_arguments(self, parser):
        parser.add_argument("--top-k", type=int, default=3, help="k for hit@k (default 3)")
        parser.add_argument("--rerank", action="store_true", help="also evaluate hybrid + cross-encoder re-ranking")

    def handle(self, *args, top_k=3, rerank=False, **options):
        queries = json.loads((EVALS / "resume_queries.json").read_text(encoding="utf-8"))["queries"]
        text = (EVALS / "eval_resume.txt").read_bytes()
        chunks = split_into_chunks(extract_text(text, "txt"))
        self.stdout.write(
            f"{len(chunks)} chunks, {len(queries)} queries, model {settings.EMBEDDING_MODEL}, "
            f"min similarity {settings.RETRIEVAL_MIN_SIMILARITY}\n"
        )

        modes = [("BM25 only", "lexical", False), ("Dense only", "dense", False), ("Hybrid (RRF)", "hybrid", False)]
        if rerank:
            modes.append(("Hybrid + rerank", "hybrid", True))

        with transaction.atomic():
            document = Document.objects.create(
                name="eval_resume.txt", file_type="txt", char_count=len(text), embedding_model=settings.EMBEDDING_MODEL
            )
            vectors = embed_texts([c.text for c in chunks])
            DocumentChunk.objects.bulk_create(
                [
                    DocumentChunk(document=document, index=c.index, page=c.page, heading=c.heading, text=c.text, embedding=v)
                    for c, v in zip(chunks, vectors)
                ]
            )
            rows = [self._evaluate(document, queries, mode, rr, top_k, name) for name, mode, rr in modes]
            transaction.set_rollback(True)  # leave no trace in the database

        header = f"{'retriever':<18}{'hit@1':>8}{f'hit@{top_k}':>8}{'MRR':>8}{'neg FP':>9}{'ms/query':>10}"
        self.stdout.write(header)
        self.stdout.write("-" * len(header))
        for row in rows:
            self.stdout.write(
                f"{row['name']:<18}{row['hit1']:>8.0%}{row['hitk']:>8.0%}{row['mrr']:>8.2f}{row['fp']:>9.0%}{row['ms']:>10.0f}"
            )
        self.stdout.write("\nneg FP = off-topic questions that still returned passages (lower is better)")

        for row in rows:
            for q, rank in row["misses"]:
                self.stdout.write(f"  miss [{row['name']}] {q!r}" + (f" (found at rank {rank})" if rank else ""))

    def _evaluate(self, document, queries, mode, rerank, top_k, name):
        answerable = [q for q in queries if q["expect"]]
        negatives = [q for q in queries if not q["expect"]]
        hit1 = hitk = rr_sum = 0
        misses, elapsed = [], 0.0
        with override_settings(RERANK_ENABLED=rerank):
            for item in answerable:
                result = retrieval_module.retrieve(document, item["q"], top_k=top_k * 2, mode=mode)
                elapsed += result.trace.get("ms", 0)
                rank = next((i for i, p in enumerate(result.passages, start=1) if item["expect"] in p.text), None)
                hit1 += rank == 1
                hitk += bool(rank and rank <= top_k)
                rr_sum += 1 / rank if rank else 0
                if not rank or rank > top_k:
                    misses.append((item["q"], rank))
            false_positives = 0
            for item in negatives:
                result = retrieval_module.retrieve(document, item["q"], top_k=top_k, mode=mode)
                elapsed += result.trace.get("ms", 0)
                false_positives += bool(result.passages)
        n = len(answerable)
        return {
            "name": name,
            "hit1": hit1 / n,
            "hitk": hitk / n,
            "mrr": rr_sum / n,
            "fp": false_positives / max(len(negatives), 1),
            "ms": elapsed / len(queries),
            "misses": misses,
        }
