import chat.fields
from django.contrib.postgres.operations import CreateExtension
from django.db import migrations, models


def create_hnsw_index(apps, schema_editor):
    """Approximate-nearest-neighbour index for cosine search (PostgreSQL / pgvector only)."""
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            "CREATE INDEX IF NOT EXISTS chat_chunk_embedding_hnsw ON chat_documentchunk "
            "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
        )


def drop_hnsw_index(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute("DROP INDEX IF EXISTS chat_chunk_embedding_hnsw")


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0001_initial"),
    ]

    operations = [
        CreateExtension("vector"),  # no-op outside PostgreSQL
        migrations.AddField(
            model_name="document",
            name="embedding_model",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="documentchunk",
            name="embedding",
            field=chat.fields.EmbeddingField(blank=True, dimensions=384, null=True),
        ),
        migrations.AddField(
            model_name="documentchunk",
            name="heading",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.RunPython(create_hnsw_index, drop_hnsw_index),
    ]
