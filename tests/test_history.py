"""Tests for the SQLite conversation history and resuming a saved conversation."""
import json
from types import SimpleNamespace

import pytest

from emporio_agent.agent import Agent, Reply, ToolTrace
from emporio_agent.history import ConversationStore, history_enabled
from emporio_agent.llm_setup import Settings
from emporio_agent.policies.retriever import PolicyRetriever
from emporio_agent.tools import ToolRegistry


@pytest.fixture()
def store(tmp_path):
    return ConversationStore(tmp_path / "logs" / "conversations.db")


def reply(text, tools=(), messages=None):
    return Reply(text, [ToolTrace(n, a, "{}") for n, a in tools],
                 messages=messages if messages is not None else [{"role": "user", "content": "q"},
                                                                {"role": "assistant", "content": text}])


def test_empty_store_lists_nothing(store):
    assert store.recent() == []


def test_add_turns_and_load_roundtrip(store):
    conv = store.create("openai", "gpt-4.1-mini")
    store.add_turn(conv, "Quanto custa o Takamine GD20?",
                   reply("R$ 2.199,00", tools=[("get_product_details", {"name": "Takamine GD20"})]))
    store.add_turn(conv, "e no PIX?", reply("R$ 2.089,05"))
    turns = store.load(conv)
    assert [t.user for t in turns] == ["Quanto custa o Takamine GD20?", "e no PIX?"]
    assert turns[0].reply == "R$ 2.199,00"
    assert (turns[0].tools[0].name, turns[0].tools[0].arguments) == ("get_product_details", {"name": "Takamine GD20"})
    assert turns[1].tools == [] and turns[0].messages[-1]["content"] == "R$ 2.199,00"


def test_title_comes_from_first_message_and_is_truncated(store):
    conv = store.create()
    store.add_turn(conv, "  " + "muito " * 30 + "longa ", reply("ok"))
    store.add_turn(conv, "segunda mensagem", reply("ok"))
    info = store.recent()[0]
    assert info.turns == 2 and len(info.title) <= 60 and info.title.endswith("…") and info.title.startswith("muito")


def test_list_is_newest_first_and_skips_empty_conversations(store):
    store.create()  # never got a turn -> not listed
    a, b = store.create(), store.create()
    store.add_turn(a, "primeira", reply("ok"))
    store.add_turn(b, "segunda", reply("ok"))
    assert [c.title for c in store.recent()] == ["segunda", "primeira"]
    store.add_turn(a, "voltei", reply("ok"))  # activity moves it to the top
    assert store.recent()[0].title == "primeira"


def test_delete_removes_conversation_and_turns(store):
    conv = store.create()
    store.add_turn(conv, "oi", reply("olá"))
    store.delete(conv)
    assert store.recent() == [] and store.load(conv) == []


def test_history_flag(monkeypatch):
    monkeypatch.delenv("SAVE_HISTORY", raising=False)
    assert history_enabled()
    for off in ("0", "false", "No", "off"):
        monkeypatch.setenv("SAVE_HISTORY", off)
        assert not history_enabled()


def test_unicode_and_quotes_survive(store):
    conv = store.create()
    store.add_turn(conv, 'Preço do "violão" — R$ 1.299,00? ✓', reply("É 'sim' 🎸"))
    t = store.load(conv)[0]
    assert t.user == 'Preço do "violão" — R$ 1.299,00? ✓' and t.reply == "É 'sim' 🎸"


class FakeClient:
    def __init__(self, texts):
        self.texts, self.requests = list(texts), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        msg = SimpleNamespace(content=self.texts.pop(0), tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def make_agent(client):
    return Agent(client=client, settings=Settings("openai", "k", None, "m", None),
                 tools=ToolRegistry(retriever=PolicyRetriever(client=None)))


def test_turn_messages_are_exposed_by_the_agent():
    agent = make_agent(FakeClient(["r1", "r2"]))
    r1 = agent.chat("m1")
    assert [m["role"] for m in r1.messages] == ["user", "assistant"]
    r2 = agent.chat("m2")
    assert [m["content"] for m in r2.messages] == ["m2", "r2"]  # only this turn, not the whole history


def test_resumed_conversation_keeps_context(store):
    first = make_agent(FakeClient(["a1", "a2"]))
    conv = store.create()
    for text in ("pergunta 1", "pergunta 2"):
        store.add_turn(conv, text, first.chat(text))

    client = FakeClient(["a3"])
    resumed = make_agent(client)
    resumed.load_history([m for t in store.load(conv) for m in t.messages])
    resumed.chat("pergunta 3")
    sent = [m["content"] for m in client.requests[0]["messages"][1:]]  # skip the system prompt
    assert sent == ["pergunta 1", "a1", "pergunta 2", "a2", "pergunta 3"]


def test_failed_turns_have_no_messages_so_they_are_not_saved():
    from openai import OpenAIError

    class Boom:
        chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_: (_ for _ in ()).throw(OpenAIError("x"))))

    assert make_agent(Boom()).chat("oi").messages == []


def test_api_key_is_never_written_to_the_database(store):
    conv = store.create("openai", "gpt-4.1-mini")
    store.add_turn(conv, "oi", reply("olá"))
    raw = store.path.read_bytes()
    assert b"sk-" not in raw
    assert json.loads(json.dumps(store.load(conv)[0].messages))  # serialisable


def test_turn_records_when_asked_and_answered(store):
    conv = store.create()
    r = reply("ok")
    r.asked_at, r.answered_at = "2026-03-23T10:30:00.000001-04:00", "2026-03-23T10:30:03.500000-04:00"
    store.add_turn(conv, "oi", r)
    t = store.load(conv)[0]
    assert (t.asked_at, t.answered_at) == (r.asked_at, r.answered_at)


def test_agent_stamps_asked_before_answered_even_on_failure():
    from openai import OpenAIError

    ok = make_agent(FakeClient(["r"])).chat("m")
    assert ok.asked_at and ok.answered_at and ok.asked_at <= ok.answered_at

    class Boom:
        chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_: (_ for _ in ()).throw(OpenAIError("x"))))

    failed = make_agent(Boom()).chat("m")
    assert failed.asked_at and failed.answered_at


def test_turns_saved_without_timestamps_fall_back_to_created_at(store):
    conv = store.create()
    store.add_turn(conv, "oi", reply("olá"))  # Reply() built by hand: no asked_at/answered_at
    t = store.load(conv)[0]
    assert t.asked_at and t.answered_at


def test_database_created_before_timestamps_is_migrated(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT NOT NULL, provider TEXT, model TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE turns (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL, seq INTEGER NOT NULL,
            user_text TEXT NOT NULL, reply_text TEXT NOT NULL, tools TEXT NOT NULL, messages TEXT NOT NULL,
            created_at TEXT NOT NULL);
        INSERT INTO conversations VALUES ('c1', 'antiga', 'openai', 'm', '2026-01-05T09:00:00-04:00', '2026-01-05T09:00:00-04:00');
        INSERT INTO turns (conversation_id, seq, user_text, reply_text, tools, messages, created_at)
            VALUES ('c1', 0, 'oi', 'olá', '[]', '[]', '2026-01-05T09:00:00-04:00');
    """)
    con.commit()
    con.close()
    migrated = ConversationStore(path)
    t = migrated.load("c1")[0]
    assert t.asked_at == t.answered_at == "2026-01-05T09:00:00-04:00"
    migrated.add_turn("c1", "de novo", reply("sim"))  # new writes work on the migrated schema
    assert len(migrated.load("c1")) == 2


def test_format_when_shows_only_the_time_for_today():
    import re

    from emporio_agent.config import format_when, stamp

    assert re.fullmatch(r"\d\d:\d\d", format_when(stamp()))
    assert format_when("2020-01-05T14:32:00-04:00") == "05/01 14:32"
    assert format_when("") == ""


def test_display_timezone_can_be_changed(monkeypatch):
    from emporio_agent.config import format_when

    iso = "2020-01-05T14:32:00-04:00"  # Campo Grande, UTC-4
    monkeypatch.delenv("DISPLAY_TZ", raising=False)
    assert format_when(iso) == "05/01 14:32"
    monkeypatch.setenv("DISPLAY_TZ", "America/Sao_Paulo")  # UTC-3 (Brazil has no DST since 2019) -> 15:32
    assert format_when(iso) == "05/01 15:32"
    monkeypatch.setenv("DISPLAY_TZ", "UTC")
    assert format_when(iso) == "05/01 18:32"
    monkeypatch.setenv("DISPLAY_TZ", "not/a-zone")  # invalid -> falls back to the store timezone
    assert format_when(iso) == "05/01 14:32"
