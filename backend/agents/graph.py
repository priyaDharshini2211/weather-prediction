"""LangGraph workflow:  route (LLM) -> weather agent | document agent | out-of-scope reply -> END."""
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from .documents.agent import run_document_agent
from .router import route_message
from .weather.agent import run_weather_agent


class ChatState(TypedDict, total=False):
    message: str
    history: list[dict]
    document_id: int | None
    route: dict
    result: dict[str, Any]


OUT_OF_SCOPE_TEXT = (
    "I can help with two things:\n\n"
    "- **Weather** - current conditions, yesterday/past days, forecasts, and 10-day history with charts "
    "(e.g. *\"List the last 10 days of weather in Chennai\"*).\n"
    "- **Your document** - upload a PDF or TXT (such as your resume) and ask about skills, education, "
    "projects or experience.\n\nWhat would you like to know?"
)


def _route_node(state: ChatState) -> ChatState:
    from chat.models import Document  # local import keeps the agents package importable without Django apps ready

    has_document = bool(state.get("document_id")) or Document.objects.exists()
    return {"route": route_message(state["message"], state.get("history", []), has_document)}


def _weather_node(state: ChatState) -> ChatState:
    return {"result": run_weather_agent(state["message"], state.get("history", []))}


def _document_node(state: ChatState) -> ChatState:
    return {"result": run_document_agent(state["message"], state.get("history", []), state.get("document_id"))}


def _out_of_scope_node(_state: ChatState) -> ChatState:
    return {"result": {"agent": "none", "answer": OUT_OF_SCOPE_TEXT, "blocks": [], "tool_trace": []}}


def _select_branch(state: ChatState) -> str:
    return state["route"]["agent"]


def build_graph():
    graph = StateGraph(ChatState)
    graph.add_node("router", _route_node)
    graph.add_node("weather", _weather_node)
    graph.add_node("document", _document_node)
    graph.add_node("none", _out_of_scope_node)
    graph.set_entry_point("router")
    graph.add_conditional_edges("router", _select_branch, {"weather": "weather", "document": "document", "none": "none"})
    for node in ("weather", "document", "none"):
        graph.add_edge(node, END)
    return graph.compile()


_GRAPH = None


def run_chat(message: str, history: list[dict], document_id: int | None = None) -> dict:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    state = _GRAPH.invoke({"message": message, "history": history, "document_id": document_id})
    result = state["result"]
    route = state["route"]
    result["tool_trace"] = [{"step": "router", "agent": route["agent"], "reason": route["reason"]}] + result.get(
        "tool_trace", []
    )
    return result
