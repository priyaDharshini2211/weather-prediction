import os
import sys
import threading

from django.apps import AppConfig


class ChatConfig(AppConfig):
    name = "chat"

    def ready(self):
        from django.conf import settings

        if settings.TESTING or not settings.EMBEDDING_WARMUP:
            return
        dev_server = len(sys.argv) > 1 and sys.argv[1] == "runserver" and (os.environ.get("RUN_MAIN") == "true" or "--noreload" in sys.argv)
        serving = dev_server or any(
            server in os.path.basename(sys.argv[0]) for server in ("gunicorn", "uvicorn", "daphne")
        )
        if serving:  # background thread: the server accepts requests immediately while the model loads
            from agents.documents.embeddings import warm_up

            threading.Thread(target=warm_up, name="embedding-warmup", daemon=True).start()
