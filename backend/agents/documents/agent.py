"""Document Understanding agent: retrieve passages -> grounded answer -> (optional) clearly separated web fallback."""
import logging

from chat.models import Document

from ..llm import LLMError, chat, chat_json
from .retrieval import Passage, retrieve
from .web_search import search_web

logger = logging.getLogger(__name__)

ANSWER_PROMPT = """You answer questions about a user's uploaded document (for example a resume) using ONLY the numbered passages given.

Rules:
- Every statement about the document must be supported by a passage. Never guess, infer missing details, or add outside facts about the person.
- If the passages do not contain the answer, say so plainly: "That isn't mentioned in the document." Do not fill the gap.
- Cite passages inline like [1], [2].
- If the question ALSO asks for general knowledge not about the document owner (e.g. "what is Kubernetes?"), answer the document part and set "external_query" to a short web search query for the general part. NEVER set external_query to look up personal information about the document owner (their employers, contact details, achievements, etc.).

Return ONLY JSON:
{"answer": "<markdown answer>", "found_in_document": true|false, "external_query": "<query>" | null}"""

EXTERNAL_PROMPT = """Summarise the web results below to answer the general-knowledge question. Use ONLY these results, keep it to 2-4 sentences,
and cite them like [1], [2]. If they do not answer the question, say so."""


def _passage_title(i: int, p: Passage) -> str:
    parts = [p.heading or f"Passage {p.index + 1}"]
    if p.page:
        parts.append(f"page {p.page}")
    if p.similarity is not None:
        parts.append(f"similarity {p.similarity:.2f}")
    return f"[{i}] " + " · ".join(parts)


def _passage_blocks(passages: list[Passage]) -> dict:
    return {
        "type": "sources",
        "title": "From the document",
        "kind": "document",
        "items": [{"title": _passage_title(i, p), "url": "", "snippet": p.text[:400]} for i, p in enumerate(passages, start=1)],
    }


def _external_section(question: str, query: str) -> tuple[str, dict | None]:
    results = search_web(query)
    if not results:
        return "\n\n---\n**External information:** the web search returned no results, so I can't add anything beyond the document.", None

    numbered = "\n".join(f"[{i}] {r['title']}: {r['snippet']}" for i, r in enumerate(results, start=1))
    try:
        summary = chat(
            [{"role": "system", "content": EXTERNAL_PROMPT}, {"role": "user", "content": f"Question: {query}\n\nResults:\n{numbered}"}],
            max_tokens=300,
        )
    except LLMError:
        summary = "See the sources below."
    block = {
        "type": "sources",
        "title": "From the web (external, not from your document)",
        "kind": "web",
        "items": [{"title": f"[{i}] {r['title']}", "url": r["url"], "snippet": r["snippet"]} for i, r in enumerate(results, start=1)],
    }
    return f"\n\n---\n**External information (from the web, not your document):** {summary}", block


def run_document_agent(message: str, history: list[dict], document_id: int | None) -> dict:
    trace: list[dict] = []

    document = Document.objects.filter(pk=document_id).first() if document_id else Document.objects.first()
    if document is None:
        text = "Please upload a PDF or TXT document first (for example your resume), then ask me about it."
        return {"agent": "document", "answer": text, "blocks": [{"type": "notice", "level": "info", "text": text}], "tool_trace": trace}

    retrieval = retrieve(document, message, history)
    passages = retrieval.passages
    trace.append({"step": "tool:document_retrieval", "document": document.name, **retrieval.trace})

    # With no matching passages the model is still consulted: it must say "not in the document" and may
    # request a web search only for the general-knowledge part of the question.
    context = "\n\n".join(f"[{i}] {p.text}" for i, p in enumerate(passages, start=1)) or "(no relevant passages found)"
    messages = [{"role": "system", "content": ANSWER_PROMPT}]
    messages += [{"role": m["role"], "content": m["content"][:300]} for m in history[-4:]]
    messages.append({"role": "user", "content": f"Document: {document.name}\n\nPassages:\n{context}\n\nQuestion: {message}"})
    reply = chat_json(messages, temperature=0.1, max_tokens=700)

    answer = str(reply.get("answer") or "").strip()
    if not answer:
        raise LLMError("the model returned an empty answer")
    blocks = [_passage_blocks(passages)] if passages else []

    external_query = reply.get("external_query")
    if isinstance(external_query, str) and external_query.strip():
        section, web_block = _external_section(message, external_query.strip())
        answer += section
        trace.append({"step": "tool:web_search", "query": external_query.strip(), "results": len(web_block["items"]) if web_block else 0})
        if web_block:
            blocks.append(web_block)

    return {"agent": "document", "answer": answer, "blocks": blocks, "tool_trace": trace}
