import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from agents.documents import agent as document_agent
from agents.documents import embeddings, vectorstore
from agents.documents.embeddings import EmbeddingError
from agents.documents.indexing import embed_texts, ensure_embedded
from agents.documents.ingest import DocumentIngestError, extract_text, split_into_chunks
from agents.documents.retrieval import bm25_scores, reciprocal_rank_fusion, retrieve, tokenize
from chat.models import Document, DocumentChunk

RESUME = """Jane Doe
Backend Engineer

Skills
Python, Django, PostgreSQL, Docker, REST APIs

Education
B.E. Computer Science, Anna University, 2021

Projects
Weather Chatbot - an agentic assistant built with LangGraph and React.

Experience
Software Engineer at Acme Corp, 2021-2024. Built payment services in Django.
"""


def make_document(text: str = RESUME, embed: bool = True) -> Document:
    chunks = split_into_chunks(extract_text(text.encode(), "txt"))
    vectors = embed_texts([c.text for c in chunks]) if embed else [None] * len(chunks)
    document = Document.objects.create(
        name="resume.txt", file_type="txt", char_count=len(text), embedding_model=settings.EMBEDDING_MODEL if embed else ""
    )
    DocumentChunk.objects.bulk_create(
        [DocumentChunk(document=document, index=c.index, page=c.page, heading=c.heading, text=c.text, embedding=v) for c, v in zip(chunks, vectors)]
    )
    return document


# ---------- chunking ----------

def test_chunks_are_section_aware_and_self_describing():
    chunks = split_into_chunks(extract_text(RESUME.encode(), "txt"))
    headings = [c.heading for c in chunks]
    assert {"Skills", "Education", "Projects", "Experience"} <= set(headings)
    skills = next(c for c in chunks if c.heading == "Skills")
    assert skills.text.startswith("Skills\n") and "PostgreSQL" in skills.text


def test_chunking_keeps_all_text_and_splits_long_sections():
    long_section = "Experience\n" + " ".join(f"Delivered feature number {i} for the platform." for i in range(120))
    chunks = split_into_chunks(extract_text(long_section.encode(), "txt"))
    assert len(chunks) > 1
    assert all(len(c.text) < 1100 for c in chunks)
    assert all(c.text.startswith("Experience\n") for c in chunks)  # every piece keeps its heading
    assert "feature number 119" in " ".join(c.text for c in chunks)


def test_all_caps_lines_are_headings():
    chunks = split_into_chunks(extract_text(b"WORK HISTORY\nAcme Corp 2020-2024\n", "txt"))
    assert chunks[0].heading == "Work History"


# ---------- retrieval building blocks ----------

def test_bm25_ranks_exact_term_match_first():
    corpus = [tokenize("python django postgresql"), tokenize("anna university degree"), tokenize("weather chatbot langgraph")]
    scores = bm25_scores(corpus, tokenize("which university"))
    assert scores.index(max(scores)) == 1


def test_reciprocal_rank_fusion_rewards_agreement():
    fused = reciprocal_rank_fusion([[1, 2, 3], [3, 1, 4]])
    assert fused[1] > fused[2] and fused[3] > fused[2]  # items both retrievers like beat single-retriever items
    assert max(fused, key=fused.get) == 1


@pytest.mark.django_db
def test_vector_search_orders_by_cosine_similarity(fake_embedder):
    document = make_document()
    hits = vectorstore.search(document.id, fake_embedder.embed_query("Anna University education"), limit=3)
    best = DocumentChunk.objects.get(pk=hits[0][0])
    assert best.heading == "Education"
    assert hits[0][1] >= hits[1][1]


@pytest.mark.django_db
def test_embedding_round_trips_through_the_field(fake_embedder):
    document = make_document()
    chunk = document.chunks.first()
    assert len(chunk.embedding) == settings.EMBEDDING_DIM
    assert chunk.embedding == pytest.approx(fake_embedder.embed_documents([chunk.text])[0], abs=1e-6)


# ---------- hybrid retrieval ----------

@pytest.mark.django_db
def test_dense_retrieval_bridges_vocabulary_gap(monkeypatch):
    monkeypatch.setattr(settings, "RETRIEVAL_MIN_SIMILARITY", 0.1)
    document = make_document()
    # No shared word between question and passage ("database" vs "PostgreSQL"): BM25 alone finds nothing.
    assert retrieve(document, "Which database does she know?", mode="lexical").passages == []
    result = retrieve(document, "Which database does she know?")
    assert result.passages and "PostgreSQL" in result.passages[0].text
    assert result.trace["mode"] == "hybrid" and result.passages[0].similarity is not None


@pytest.mark.django_db
def test_lexical_match_is_kept_even_when_similarity_is_low():
    document = make_document()
    result = retrieve(document, "LangGraph")
    assert result.passages and "LangGraph" in result.passages[0].text and result.passages[0].bm25 > 0


@pytest.mark.django_db
def test_retrieval_returns_nothing_for_unrelated_question():
    assert retrieve(make_document(), "zebra quantum").passages == []


@pytest.mark.django_db
def test_falls_back_to_bm25_when_embedding_model_is_down(monkeypatch):
    document = make_document()

    class Broken:
        name = "broken"

        def embed_query(self, text):
            raise EmbeddingError("model offline")

    monkeypatch.setattr(embeddings, "_embedder", Broken())
    result = retrieve(document, "Which university did she attend?")
    assert result.trace["mode"] == "lexical-only" and "model offline" in result.trace["dense_error"]
    assert result.passages and "Anna University" in result.passages[0].text


@pytest.mark.django_db
def test_terse_follow_up_uses_previous_question_for_context():
    document = make_document()
    history = [{"role": "user", "content": "Tell me about her education"}, {"role": "assistant", "content": "Anna University."}]
    result = retrieve(document, "and when?", history)
    assert result.passages and result.passages[0].heading == "Education"


@pytest.mark.django_db
def test_legacy_document_without_vectors_is_embedded_on_first_use():
    document = make_document(embed=False)
    assert DocumentChunk.objects.filter(document=document, embedding__isnull=True).count() == document.chunks.count()
    result = retrieve(document, "Which university did she attend?")
    assert result.trace["chunks_embedded_now"] == document.chunks.count()
    assert not DocumentChunk.objects.filter(document=document, embedding__isnull=True).exists()
    document.refresh_from_db()
    assert document.embedding_model == settings.EMBEDDING_MODEL
    assert ensure_embedded(document) == 0  # idempotent


@pytest.mark.django_db
def test_changing_the_embedding_model_triggers_reindex(monkeypatch):
    document = make_document()
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "another-model")
    assert ensure_embedded(document) == document.chunks.count()


def test_dimension_mismatch_is_reported_clearly(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_DIM", 8)
    with pytest.raises(EmbeddingError, match="EMBEDDING_DIM"):
        embeddings._check_dimension([[0.0] * 384])


# ---------- agent ----------

@pytest.mark.django_db
def test_agent_grounded_answer_cites_passages(monkeypatch):
    make_document()
    monkeypatch.setattr(document_agent, "chat_json", lambda *a, **k: {"answer": "She knows Python and Django [1].", "external_query": None})
    result = document_agent.run_document_agent("What are her skills?", [], None)
    source = result["blocks"][0]
    assert source["kind"] == "document" and "Python" in source["items"][0]["snippet"]
    assert "Skills" in source["items"][0]["title"]
    assert result["tool_trace"][0]["mode"] == "hybrid"


@pytest.mark.django_db
def test_web_fallback_is_labelled_external_and_has_sources(monkeypatch):
    make_document()
    monkeypatch.setattr(document_agent, "chat_json", lambda *a, **k: {"answer": "Python is listed [1].", "external_query": "what is Django"})
    monkeypatch.setattr(document_agent, "search_web", lambda q: [{"title": "Django", "url": "https://www.djangoproject.com", "snippet": "A web framework"}])
    monkeypatch.setattr(document_agent, "chat", lambda *a, **k: "Django is a Python web framework [1].")
    result = document_agent.run_document_agent("Skills? And what is Django?", [], None)
    assert "External information" in result["answer"]
    assert any(b["kind"] == "web" and b["items"][0]["url"].startswith("https://") for b in result["blocks"])


@pytest.mark.django_db
def test_no_document_uploaded_asks_for_upload():
    result = document_agent.run_document_agent("What are my skills?", [], None)
    assert "upload" in result["answer"].lower()


def test_non_pdf_bytes_are_rejected():
    with pytest.raises(DocumentIngestError):
        extract_text(b"not a pdf at all", "pdf")


# ---------- upload endpoint ----------

@pytest.mark.django_db
class TestUploadEndpoint:
    def setup_method(self):
        self.client = APIClient()

    def test_upload_txt_embeds_every_chunk(self):
        response = self.client.post("/api/documents/", {"file": SimpleUploadedFile("cv.txt", RESUME.encode())}, format="multipart")
        assert response.status_code == 201
        body = response.json()
        assert body["chunks"] >= 1
        document = Document.objects.get(pk=body["id"])
        assert document.embedding_model == settings.EMBEDDING_MODEL
        assert not document.chunks.filter(embedding__isnull=True).exists()

    def test_embedding_failure_returns_503_and_stores_nothing(self, monkeypatch):
        class Broken:
            name = "broken"

            def embed_documents(self, texts):
                raise EmbeddingError("model offline")

        monkeypatch.setattr(embeddings, "_embedder", Broken())
        response = self.client.post("/api/documents/", {"file": SimpleUploadedFile("cv.txt", RESUME.encode())}, format="multipart")
        assert response.status_code == 503
        assert Document.objects.count() == 0

    def test_rejects_unsupported_extension(self):
        response = self.client.post("/api/documents/", {"file": SimpleUploadedFile("cv.docx", b"x")}, format="multipart")
        assert response.status_code == 400
        assert "PDF or TXT" in response.json()["error"]

    def test_rejects_empty_text(self):
        response = self.client.post("/api/documents/", {"file": SimpleUploadedFile("cv.txt", b"   \n ")}, format="multipart")
        assert response.status_code == 422

    def test_missing_file(self):
        assert self.client.post("/api/documents/", {}, format="multipart").status_code == 400


def test_ad_redirects_are_not_treated_as_sources():
    from agents.documents.web_search import _is_ad

    assert _is_ad("https://www.bing.com/aclick?ld=abc")
    assert not _is_ad("https://en.wikipedia.org/wiki/Redis")
