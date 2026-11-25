# Agentic AI Chatbot - Weather Intelligence & Document Understanding

A Python (Django) backend with **exactly two agents**, orchestrated by **LangGraph**, plus a React chat UI with tables and interactive charts.

```
React (chat UI, upload, Recharts)
   |  REST
Django API ──> LangGraph:  router (LLM) ──┬─> Weather agent  ──> OpenWeatherMap / Open-Meteo ──> table + line/bar/pie charts
                                          ├─> Document agent ──> PDF/TXT parser ─> BM25 RAG ─> grounded answer (+ web fallback w/ sources)
                                          └─> polite out-of-scope reply
PostgreSQL (Neon): documents, chunks, conversations, messages
```

## How the agentic workflow works

1. **LLM routing** (`agents/router.py`): the model decides `weather`, `document` or `none` from the message, the recent conversation and whether a document exists - no keyword rules.
2. **Weather agent** (`agents/weather/`): the LLM extracts a structured plan (intent, city, relative date, number of days, requested chart types). Tools then fetch *real* data; the presentation layer builds metric cards / tables / charts **only from the returned rows**; the LLM writes a short summary restricted to that data.
   - Current & forecast: OpenWeatherMap (when `OPENWEATHER_API_KEY` is set).
   - History: OpenWeatherMap One Call 3.0 needs a paid plan, so if it is unavailable the agent falls back to **Open-Meteo** (free, no key) and **tells the user** which provider was used and why. If no provider can answer, a clear limitation message is shown - nothing is invented.
   - Presentation chosen from the question: single-day -> metric cards; multi-day -> table + temperature **line** chart + precipitation (or humidity) **bar** chart + condition **pie** chart; explicit requests ("pie chart ...") are honoured.
3. **Document agent** (`agents/documents/`): PDF/TXT -> text -> section-aware chunks -> **embeddings stored in PostgreSQL with pgvector** -> hybrid retrieval (see below) -> LLM answers **only** from numbered passages, citing `[1]`, `[2]`, or says *"That isn't mentioned in the document."*
   - **Web fallback** is used only for the *general-knowledge* part of a question (e.g. "what is Kubernetes?"), is rendered in a separate, labelled "External information (from the web, not your document)" section with source links, and is **never** used to look up personal facts about the resume owner.

## Retrieval (RAG)

```
upload:  PDF/TXT -> extract -> section-aware chunks (heading kept in every chunk) -> bge-small embeddings (384-d)
         -> Neon: chat_documentchunk.embedding  vector(384)  + HNSW index (cosine)
query:   question (+ previous question if it is a terse follow-up)
           |-- dense : embed query -> pgvector cosine search  (top 20)
           |-- lexical: BM25 over the document's chunks       (top 20)
         -> Reciprocal Rank Fusion -> noise floor -> (optional cross-encoder rerank) -> top 6 passages -> LLM
```

- **Vector database:** pgvector inside the same Neon database (migration `0002` enables the extension and builds the HNSW index). Searches are scoped per document with pgvector's iterative scan so filtered HNSW queries never come back short.
- **Embedding model:** `BAAI/bge-small-en-v1.5` (open source, 384-d) run locally through `fastembed` (ONNX, no GPU/torch, ~70 MB, cached in `.model_cache/`). Loaded at server start in a background thread. Any OpenAI-compatible embeddings API can be used instead (`EMBEDDING_PROVIDER=openai`).
- **Why hybrid:** dense vectors bridge vocabulary ("which database?" -> "PostgreSQL"); BM25 keeps exact tokens ("C++", "CGPA 8.9", names) that embeddings blur.
- **Resilience:** if the embedding model is unavailable at query time the agent falls back to BM25 (reported in `tool_trace`); at upload a failure returns 503 and stores nothing. Documents indexed with another/no model are re-embedded automatically on first use, or in bulk with `python manage.py reembed`.
- **Changing the model:** the vector dimension is part of the schema. Set `EMBEDDING_MODEL`/`EMBEDDING_DIM`, add a migration for the new `vector(N)` size, then run `python manage.py reembed --force`.

**Measured quality** (`python manage.py evaluate_rag --rerank`: 21 answerable + 3 off-topic questions on a 9-chunk resume, 14 of the 21 are paraphrases, 7 are exact-term lookups):

| retriever | hit@1 | hit@3 | MRR |
|---|---|---|---|
| BM25 only (previous implementation) | 52% | 52% | 0.52 |
| Dense only | 71% | 90% | 0.81 |
| **Hybrid (default)** | 81% | **95%** | 0.88 |
| Hybrid + cross-encoder rerank | 90% | 95% | 0.92 |

The reranker is off by default: it only reorders the top 6, which the LLM sees anyway (hit@3 is unchanged), and costs extra latency. Enable with `RERANK_ENABLED=true`. The similarity floor (`RETRIEVAL_MIN_SIMILARITY=0.45`) is a coarse noise filter, not a guarantee: very short nonsense queries can still score above it, which is why the answer prompt, not retrieval, enforces "not mentioned in the document". Latency is dominated by database round trips (about 300 ms each to Neon from a laptop); the query embedding itself takes about 10 ms.

## Setup

Prerequisites: Python 3.11+, Node 18+, a PostgreSQL database **with the pgvector extension** (Neon has it; `migrate` runs `CREATE EXTENSION vector`; SQLite works for local dev with exact NumPy search), and an LLM endpoint. The first start downloads the ~70 MB embedding model.

### 1. LLM (open-source model, OpenAI-compatible API)
Option A - local **Ollama**:
```
ollama pull llama3.1:8b
```
Option B - hosted open-source model (e.g. Groq): set `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` in `.env` (see `.env.example`).

### 2. Backend
```
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # then fill in DATABASE_URL, LLM_*, optionally OPENWEATHER_API_KEY
python manage.py migrate
python manage.py runserver 1000 # http://localhost:1000
```
Tests (no network / LLM needed): `python -m pytest`

### 3. Frontend
```
cd frontend
npm install
npm run dev                     # http://localhost:2000 (proxies /api to :1000)
```

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health/` | health check |
| GET/POST | `/api/documents/` | list / upload a PDF or TXT (`multipart`, field `file`, max 5 MB) |
| DELETE | `/api/documents/<id>/` | delete a document |
| POST | `/api/chat/` | `{message, conversation_id?, document_id?}` -> `{answer, agent, blocks, tool_trace, conversation_id}` |
| GET | `/api/conversations/<uuid>/messages/` | conversation history |

Errors are always `{"error": "..."}` (400 validation, 404, 413 too large, 422 unreadable document, 503 LLM unavailable).

## Sample queries

Weather
- What is the weather in Chennai today?
- What was the weather in Bengaluru yesterday?
- What will the weather be like in London tomorrow?
- List the last 10 days of weather in Chennai
- Show a pie chart of weather conditions in Mumbai for the last 10 days

Document (after uploading a resume)
- What are the skills mentioned in my resume?
- Summarise my education and projects
- Where did I work and for how long?
- Is Kubernetes mentioned in my resume? *(grounded: answers "not mentioned" if absent)*
- What is Docker? Also, do I list it as a skill? *(document part + labelled web fallback)*

## Security & quality notes
- All secrets come from environment variables; `.env` is git-ignored, `.env.example` documents every variable.
- Input validation: message length, upload type/size, empty/scanned/encrypted PDFs, unknown conversation/document IDs.
- API/LLM/network failures are caught and returned as clear messages; weather providers degrade gracefully and report provenance.
- Modular layout: `chat/` (Django app: models, views), `agents/` (llm, router, graph, weather/, documents/), `tests/` (44 tests; LLM, HTTP and the embedding model are mocked), `evals/` (labelled retrieval benchmark).

## Screenshots
See `screenshots/`: home + sample queries, 10-day weather table, line/bar charts, pie chart, and a resume answer with the clearly labelled web fallback.

## UI
A ChatGPT/Gemini-style interface: collapsible sidebar (New chat, Documents with upload/delete, Recent conversations stored in the browser and reloaded from the API), centered thread, Gemini-style greeting with suggestion cards, a pill composer (Enter to send, Shift+Enter for a new line, paperclip to attach a PDF/TXT), a typing effect on new answers, copy button, a collapsible "How I answered" trace, dark/light theme (follows the system, switchable), and a drawer sidebar on phones.
