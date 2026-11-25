"""`EmbeddingField`: a pgvector `vector(N)` column on PostgreSQL, JSON text elsewhere (SQLite for tests / local dev)."""
import json

from django.db import models


class EmbeddingField(models.Field):
    def __init__(self, dimensions: int, *args, **kwargs):
        self.dimensions = dimensions
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        kwargs["dimensions"] = self.dimensions
        return name, path, args, kwargs

    def db_type(self, connection):
        return f"vector({self.dimensions})" if connection.vendor == "postgresql" else "text"

    def from_db_value(self, value, expression, connection):
        if value is None:
            return None
        # pgvector returns '[0.1,0.2,...]' (text) and SQLite stores the same JSON text.
        return json.loads(value) if isinstance(value, str) else list(value)

    def get_db_prep_value(self, value, connection, prepared=False):
        if value is None:
            return None
        if len(value) != self.dimensions:
            raise ValueError(f"Expected a {self.dimensions}-dim embedding, got {len(value)}")
        return "[" + ",".join(f"{float(x):.7g}" for x in value) + "]"
