"""Tests for policy ingestion/retrieval and the agent loop (LLM mocked, no network)."""
import json
from types import SimpleNamespace

from emporio_agent.agent import FALLBACK_REPLY, Agent
from emporio_agent.config import POLICY_PDF
from emporio_agent.policies.ingest import load_chunks
from emporio_agent.policies.retriever import PolicyRetriever
from emporio_agent.tools import ToolRegistry


def test_chunks_follow_manual_structure():
    sections = {c.section for c in load_chunks(POLICY_PDF)}
    assert {"capa", "2", "3.1", "4.1", "4.2", "4.3", "4.4", "5.1", "5.2", "6.2", "7.3", "8.1", "9"} <= sections


def test_chunk_contains_regret_rule():
    chunk = next(c for c in load_chunks(POLICY_PDF) if c.section == "4.1")
    assert "7 (sete) dias" in chunk.text and "Arrependimento" in chunk.title


def test_keyword_fallback_retrieval_without_client():
    hits = PolicyRetriever(client=None).search("reembolso arrependimento devolução", k=3)
    assert hits[0]["method"] == "keyword"
    assert "4.1" in [h["section"] for h in hits]


def _llm_message(content=None, tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))])


def _tool_call(call_id, name, args):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class FakeClient:
    """Scripted chat.completions: first asks for a tool, then answers."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.script.pop(0)


def test_agent_executes_tool_and_returns_final_answer():
    client = FakeClient([
        _llm_message(tool_calls=[_tool_call("c1", "get_product_details", {"name": "Takamine GD20"})]),
        _llm_message(content="O Takamine GD20 custa R$ 2.199,00."),
    ])
    agent = Agent(client=client, tools=ToolRegistry(retriever=PolicyRetriever(client=None)))
    reply = agent.chat("Quanto custa o Takamine GD20?")
    assert reply.text.startswith("O Takamine")
    assert [t.name for t in reply.tool_calls] == ["get_product_details"]
    assert "2199" in reply.tool_calls[0].result
    # the tool result was fed back to the model in the second request
    assert client.requests[1]["messages"][-1]["role"] == "tool"
    assert [m["role"] for m in agent.history] == ["user", "assistant", "tool", "assistant"]


def test_agent_survives_unknown_tool_and_bad_arguments():
    client = FakeClient([
        _llm_message(tool_calls=[_tool_call("c1", "does_not_exist", {}), _tool_call("c2", "get_order_status", {"order_id": 1})]),
        _llm_message(content="ok"),
    ])
    agent = Agent(client=client, tools=ToolRegistry(retriever=PolicyRetriever(client=None)))
    reply = agent.chat("oi")
    assert reply.text == "ok"
    assert all("error" in json.loads(t.result) for t in reply.tool_calls)


def test_agent_rolls_back_turn_on_api_failure():
    from openai import OpenAIError

    class Boom:
        chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_: (_ for _ in ()).throw(OpenAIError("down"))))

    agent = Agent(client=Boom(), tools=ToolRegistry(retriever=PolicyRetriever(client=None)))
    reply = agent.chat("oi")
    assert reply.text == FALLBACK_REPLY and agent.history == []


def test_history_trim_keeps_turn_boundaries(monkeypatch):
    monkeypatch.setattr("emporio_agent.agent.MAX_HISTORY_MESSAGES", 4)
    client = FakeClient([_llm_message(content=f"r{i}") for i in range(5)])
    agent = Agent(client=client, tools=ToolRegistry(retriever=PolicyRetriever(client=None)))
    for i in range(5):
        agent.chat(f"m{i}")
    assert agent.history[0]["role"] == "user" and len(agent.history) <= 4
