"""LLM-based tool selection: decides which of the two agents should handle a message."""
import logging

from .llm import LLMError, chat_json

logger = logging.getLogger(__name__)

AGENTS = ("weather", "document", "none")

ROUTER_PROMPT = """You are the router of a chatbot that has exactly two specialised agents:

1. "weather"  - weather questions about a place: current conditions, past days (history), forecasts, trends.
2. "document" - questions about the user's uploaded document (e.g. a resume: skills, education, projects,
                experience), and general knowledge questions that relate to the document's content.
Use "none" only if the message fits neither (greetings, unrelated chit-chat, requests for other abilities).

Context: a document {doc_state}.
Use the recent conversation to resolve follow-ups (e.g. "and tomorrow?" after a weather question is "weather").

Reply with ONLY a JSON object: {{"agent": "weather" | "document" | "none", "reason": "<short reason>"}}"""


def route_message(message: str, history: list[dict], has_document: bool) -> dict:
    doc_state = "IS uploaded and available" if has_document else "has NOT been uploaded"
    messages = [{"role": "system", "content": ROUTER_PROMPT.format(doc_state=doc_state)}]
    messages += [{"role": m["role"], "content": m["content"][:300]} for m in history[-4:]]
    messages.append({"role": "user", "content": message})

    decision = chat_json(messages, max_tokens=120)
    agent = str(decision.get("agent", "")).strip().lower()
    if agent not in AGENTS:
        raise LLMError(f"router returned an unknown agent: {agent!r}")
    return {"agent": agent, "reason": str(decision.get("reason", ""))[:200]}
