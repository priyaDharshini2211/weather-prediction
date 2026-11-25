import pytest
from rest_framework.test import APIClient

from agents import graph, llm, router
from agents.llm import LLMError, parse_json_object


def test_parse_json_object_tolerates_code_fences_and_prose():
    assert parse_json_object('Sure!\n```json\n{"agent": "weather"}\n```') == {"agent": "weather"}


def test_strip_reasoning_removes_thought_blocks():
    assert llm.strip_reasoning('<thought>hmm {"a": 1}</thought>{"agent": "none"}') == '{"agent": "none"}'
    assert llm.strip_reasoning("<thought>cut off mid thou") == ""


def test_parse_json_object_rejects_garbage():
    with pytest.raises(LLMError):
        parse_json_object("no json here")


@pytest.mark.django_db
def test_router_picks_agent_via_llm(monkeypatch):
    monkeypatch.setattr(router, "chat_json", lambda *a, **k: {"agent": "weather", "reason": "asks about rain"})
    assert router.route_message("Will I need an umbrella in Pune?", [], False)["agent"] == "weather"


@pytest.mark.django_db
def test_router_rejects_unknown_agent(monkeypatch):
    monkeypatch.setattr(router, "chat_json", lambda *a, **k: {"agent": "calendar"})
    with pytest.raises(LLMError):
        router.route_message("hi", [], False)


@pytest.mark.django_db
def test_chat_endpoint_out_of_scope_and_persists(monkeypatch):
    monkeypatch.setattr(router, "chat_json", lambda *a, **k: {"agent": "none", "reason": "greeting"})
    client = APIClient()
    response = client.post("/api/chat/", {"message": "hello"}, format="json")
    assert response.status_code == 200
    body = response.json()
    assert body["agent"] == "none" and body["tool_trace"][0]["step"] == "router"

    history = client.get(f"/api/conversations/{body['conversation_id']}/messages/").json()
    assert [m["role"] for m in history] == ["user", "assistant"]


@pytest.mark.django_db
def test_chat_endpoint_validates_input():
    client = APIClient()
    assert client.post("/api/chat/", {"message": ""}, format="json").status_code == 400
    assert client.post("/api/chat/", {"message": "x" * 2001}, format="json").status_code == 400
    assert client.post("/api/chat/", {"message": "hi", "conversation_id": "00000000-0000-0000-0000-000000000000"}, format="json").status_code == 404


@pytest.mark.django_db
def test_llm_outage_returns_503_not_a_crash(monkeypatch):
    def boom(*a, **k):
        raise LLMError("cannot reach model")

    monkeypatch.setattr(router, "chat_json", boom)
    response = APIClient().post("/api/chat/", {"message": "hello"}, format="json")
    assert response.status_code == 503
    assert "language model is unavailable" in response.json()["error"]


@pytest.mark.django_db
def test_graph_routes_to_weather_agent(monkeypatch):
    monkeypatch.setattr(router, "chat_json", lambda *a, **k: {"agent": "weather", "reason": "x"})
    monkeypatch.setattr(graph, "run_weather_agent", lambda m, h: {"agent": "weather", "answer": "sunny", "blocks": [], "tool_trace": []})
    graph._GRAPH = None
    result = graph.run_chat("weather in Chennai?", [])
    assert result["agent"] == "weather" and result["answer"] == "sunny"
