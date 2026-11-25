"""Django settings. All secrets / environment specific values come from environment variables (.env)."""
import os
import sys
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

TESTING = "pytest" in sys.modules

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "chat",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True

# --- Database: Neon (or any PostgreSQL) via DATABASE_URL; in-memory SQLite while running tests ---
if TESTING:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
elif os.environ.get("DATABASE_URL"):
    DATABASES = {"default": dj_database_url.parse(os.environ["DATABASE_URL"], conn_max_age=60)}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

# --- CORS ---
CORS_ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "http://localhost:2000").split(",")]

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "chat.errors.api_exception_handler",
}

# --- LLM: any OpenAI-compatible endpoint. Default = local Ollama. ---
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "llama3.1:8b")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "ollama")  # Ollama ignores it; hosted providers need a real key
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "120"))
LLM_REASONING_TOKENS = int(os.environ.get("LLM_REASONING_TOKENS", "3000"))  # extra budget for models that "think"; 0 for plain models

# --- Weather ---
OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")
WEATHERAPI_KEY = os.environ.get("WEATHERAPI_KEY", "")  # weatherapi.com (optional)
WEATHER_TIMEOUT = float(os.environ.get("WEATHER_TIMEOUT", "15"))

# --- Embeddings / vector search (pgvector). The dimension is part of the DB schema: changing model => migrate + `manage.py reembed`. ---
EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "fastembed")  # fastembed (local, open-source) | openai (any OpenAI-compatible API)
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "384"))
EMBEDDING_QUERY_PREFIX = os.environ.get("EMBEDDING_QUERY_PREFIX", "Represent this sentence for searching relevant passages: ")
EMBEDDING_BATCH_SIZE = int(os.environ.get("EMBEDDING_BATCH_SIZE", "32"))
EMBEDDING_CACHE_DIR = os.environ.get("EMBEDDING_CACHE_DIR", str(BASE_DIR / ".model_cache"))
EMBEDDING_WARMUP = os.environ.get("EMBEDDING_WARMUP", "true").lower() == "true"
EMBEDDING_BASE_URL = os.environ.get("EMBEDDING_BASE_URL", "")  # only for EMBEDDING_PROVIDER=openai
EMBEDDING_API_KEY = os.environ.get("EMBEDDING_API_KEY", "")

RERANK_ENABLED = os.environ.get("RERANK_ENABLED", "false").lower() == "true"
RERANK_MODEL = os.environ.get("RERANK_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2")
RETRIEVAL_TOP_K = int(os.environ.get("RETRIEVAL_TOP_K", "6"))
RETRIEVAL_CANDIDATES = int(os.environ.get("RETRIEVAL_CANDIDATES", "20"))  # per retriever, before fusion
RETRIEVAL_MIN_SIMILARITY = float(os.environ.get("RETRIEVAL_MIN_SIMILARITY", "0.45"))  # cosine floor for dense hits

# --- Documents ---
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "5")) * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_BYTES + 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_BYTES + 1024 * 1024
