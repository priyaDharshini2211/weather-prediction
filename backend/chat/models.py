import uuid

from django.conf import settings
from django.db import models

from .fields import EmbeddingField


class Document(models.Model):
    name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=10)
    char_count = models.PositiveIntegerField()
    embedding_model = models.CharField(max_length=100, blank=True, default="")  # model that produced the chunk vectors
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class DocumentChunk(models.Model):
    """A retrievable passage of an uploaded document, with its embedding (pgvector on PostgreSQL)."""

    document = models.ForeignKey(Document, related_name="chunks", on_delete=models.CASCADE)
    index = models.PositiveIntegerField()
    page = models.PositiveIntegerField(null=True, blank=True)
    heading = models.CharField(max_length=100, blank=True, default="")
    text = models.TextField()
    embedding = EmbeddingField(dimensions=settings.EMBEDDING_DIM, null=True, blank=True)

    class Meta:
        ordering = ["document_id", "index"]
        unique_together = [("document", "index")]


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)


class Message(models.Model):
    ROLES = [("user", "user"), ("assistant", "assistant")]

    conversation = models.ForeignKey(Conversation, related_name="messages", on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=ROLES)
    content = models.TextField()
    agent = models.CharField(max_length=20, blank=True, default="")
    blocks = models.JSONField(default=list, blank=True)  # tables / charts / sources rendered by the UI
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
