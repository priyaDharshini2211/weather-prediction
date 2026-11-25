from django.core.management.base import BaseCommand

from agents.documents.indexing import ensure_embedded
from chat.models import Document


class Command(BaseCommand):
    help = "(Re)compute chunk embeddings - after changing EMBEDDING_MODEL, or to backfill documents uploaded before pgvector."

    def add_arguments(self, parser):
        parser.add_argument("--document", type=int, help="only this document id")
        parser.add_argument("--force", action="store_true", help="re-embed even if the stored model matches")

    def handle(self, *args, document=None, force=False, **options):
        documents = Document.objects.filter(pk=document) if document else Document.objects.all()
        total = 0
        for doc in documents:
            count = ensure_embedded(doc, force=force)
            total += count
            self.stdout.write(f"document {doc.pk} ({doc.name}): {count} chunk(s) embedded")
        self.stdout.write(self.style.SUCCESS(f"Done - {total} chunk(s) embedded."))
