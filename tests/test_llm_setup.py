"""Tests for provider presets, env loading, the first-run wizard and friendly error handling."""
import os

import pytest

try:  # newer openai releases ship their own fork of httpx
    import httpx
except ImportError:
    import httpx2 as httpx
from openai import AuthenticationError

from emporio_agent.agent import Agent
from emporio_agent.llm_setup import (PRESETS, Settings, describe_error, interactive_setup, is_configured,
                                     list_models, load_settings, make_client, model_choices, save_env)
from emporio_agent.policies.retriever import PolicyRetriever
from emporio_agent.tools import ToolRegistry

ENV_VARS = ["LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL", "LLM_EMBEDDING_MODEL",
            "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_EMBEDDING_MODEL"]


@pytest.fixture(autouse=True)
def clean_env():
    """Run each test with no LLM_*/OPENAI_* variables and restore the real ones afterwards
    (save_env/apply_to_environ write to os.environ directly, which monkeypatch cannot undo)."""
    saved = {v: os.environ.get(v) for v in ENV_VARS}
    for var in ENV_VARS:
        os.environ.pop(var, None)
    yield
    for var, value in saved.items():
        if value is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = value


def test_defaults_to_openai_with_embeddings():
    s = load_settings()
    assert (s.provider, s.model, s.embedding_model) == ("openai", "gpt-4.1-mini", "text-embedding-3-small")
    assert s.base_url is None


def test_legacy_openai_variables_still_work(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-x")
    s = load_settings()
    assert s.api_key == "sk-real" and s.model == "gpt-x" and is_configured(s)


def test_llm_variables_take_precedence_and_set_base_url(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-old")
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("LLM_API_KEY", "gsk-new")
    s = load_settings()
    assert s.api_key == "gsk-new" and s.base_url == PRESETS["groq"].base_url and s.embedding_model is None


@pytest.mark.parametrize("key", ["", "your-key-here", "  "])
def test_placeholder_or_missing_key_is_not_configured(key):
    assert not is_configured(Settings("openai", key, None, "gpt-4.1-mini", None))


def test_ollama_needs_no_key_and_custom_needs_base_url():
    assert is_configured(Settings("ollama", "", PRESETS["ollama"].base_url, "llama3.1", None))
    assert not is_configured(Settings("custom", "k", None, "m", None))
    assert is_configured(Settings("custom", "k", "https://host/v1", "m", None))


def test_make_client_uses_base_url():
    client = make_client(Settings("groq", "k", PRESETS["groq"].base_url, "m", None))
    assert str(client.base_url).startswith("https://api.groq.com/openai/v1")


def test_save_env_upserts_and_preserves_other_lines(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comment\nAGENT_NOW=2026-03-23T10:30\nLLM_MODEL=old\n", encoding="utf-8")
    save_env(Settings("gemini", "AIza-secret", PRESETS["gemini"].base_url, "gemini-x", None), env)
    text = env.read_text(encoding="utf-8")
    assert "# comment" in text and "AGENT_NOW=2026-03-23T10:30" in text
    assert "LLM_MODEL=gemini-x" in text and "LLM_MODEL=old" not in text
    assert "LLM_PROVIDER=gemini" in text and "LLM_API_KEY=AIza-secret" in text
    assert load_settings().provider == "gemini"  # applied to the running process too


def _wizard(tmp_path, answers, secret="sk-typed", fetched=None):
    answers = iter(answers)
    out = []
    s = interactive_setup(current=Settings("openai", "", None, "gpt-4.1-mini", "text-embedding-3-small"),
                          input_fn=lambda _prompt: next(answers), secret_fn=lambda _prompt: secret,
                          out=out.append, env_path=tmp_path / ".env", list_models_fn=lambda _s: fetched or [])
    return s, out


def test_wizard_picks_provider_key_and_model_and_saves(tmp_path):
    names = list(PRESETS)
    s, out = _wizard(tmp_path, [str(names.index("groq") + 1), "llama-x", "y"])
    assert (s.provider, s.api_key, s.model) == ("groq", "sk-typed", "llama-x")
    assert "LLM_API_KEY=sk-typed" in (tmp_path / ".env").read_text(encoding="utf-8")
    assert any("keyword" in line for line in out)  # warns about missing embeddings


def test_wizard_defaults_and_declining_save(tmp_path):
    s, _ = _wizard(tmp_path, ["", "", "n"])
    assert s.provider == "openai" and s.model == "gpt-4.1-mini" and s.embedding_model == "text-embedding-3-small"
    assert not (tmp_path / ".env").exists()


def test_wizard_custom_endpoint_and_no_key_provider(tmp_path):
    names = list(PRESETS)
    s, _ = _wizard(tmp_path, [str(names.index("custom") + 1), "https://host/v1", "my-model", "n"])
    assert s.base_url == "https://host/v1" and s.model == "my-model"
    s, _ = _wizard(tmp_path, [str(names.index("ollama") + 1), "", "n"], secret="SHOULD-NOT-BE-USED")
    assert s.api_key == ""


def test_auth_error_gives_actionable_hint_and_clean_rollback():
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    exc = AuthenticationError("bad key", response=httpx.Response(401, request=request), body=None)
    assert "key" in describe_error(exc).lower()

    class Boom:
        class chat:
            class completions:
                @staticmethod
                def create(**_):
                    raise exc

    agent = Agent(client=Boom(), settings=Settings("openai", "your-key-here", None, "m", None),
                  tools=ToolRegistry(retriever=PolicyRetriever(client=None)))
    reply = agent.chat("oi")
    assert reply.error and "key" in reply.error.lower() and agent.history == []


def test_retriever_without_embedding_model_uses_keywords_silently():
    r = PolicyRetriever(client=object(), embedding_model=None)
    assert r.search("garantia legal 90 dias")[0]["method"] == "keyword"


def test_model_choices_orders_suggestions_fetched_and_current():
    assert model_choices("openai")[0] == "gpt-4.1-mini"
    merged = model_choices("openai", "my-ft-model", fetched=["gpt-4.1", "brand-new"])
    assert merged[0] == "my-ft-model" and "brand-new" in merged and merged.count("gpt-4.1") == 1
    assert model_choices("custom", "") == []


def test_wizard_model_menu_accepts_number_name_or_default(tmp_path):
    names = list(PRESETS)
    openai_choices = model_choices("openai", "gpt-4.1-mini")
    s, out = _wizard(tmp_path, ["1", "2", "n"])
    assert s.model == openai_choices[1] and any("1. gpt-4.1-mini" in line for line in out)
    s, _ = _wizard(tmp_path, ["1", "my-own-model", "n"])
    assert s.model == "my-own-model"
    s, _ = _wizard(tmp_path, ["1", "", "n"])
    assert s.model == "gpt-4.1-mini"
    s, out = _wizard(tmp_path, [str(names.index("groq") + 1), "3", "n"], fetched=["llama-extra"])
    assert s.model == "llama-extra" and any("llama-extra" in line for line in out)


def test_list_models_hides_non_chat_and_dated_snapshots(monkeypatch):
    ids = ["gpt-4.1", "gpt-4.1-2025-04-14", "text-embedding-3-small", "whisper-1", "gpt-image-1", "sora-2", "o3"]
    fake = type("C", (), {"models": type("M", (), {"list": staticmethod(lambda: [type("X", (), {"id": i}) for i in ids])})})()
    monkeypatch.setattr("emporio_agent.llm_setup.make_client", lambda _s: fake)
    assert list_models(Settings("openai", "k", None, "m", None)) == ["gpt-4.1", "o3"]


def test_list_models_returns_empty_on_failure(monkeypatch):
    def boom(_s):
        raise RuntimeError("offline")
    monkeypatch.setattr("emporio_agent.llm_setup.make_client", boom)
    assert list_models(Settings("openai", "k", None, "m", None)) == []


def test_agent_retries_without_temperature_for_models_that_reject_it():
    from types import SimpleNamespace
    from openai import BadRequestError

    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if "temperature" in kwargs:
            request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
            raise BadRequestError("Unsupported value: 'temperature' does not support 0.3 with this model.",
                                  response=httpx.Response(400, request=request), body=None)
        msg = SimpleNamespace(content="ok", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    agent = Agent(client=client, settings=Settings("openai", "k", None, "gpt-5-mini", None),
                  tools=ToolRegistry(retriever=PolicyRetriever(client=None)))
    assert agent.chat("oi").text == "ok"
    agent.chat("de novo")
    assert "temperature" in calls[0] and "temperature" not in calls[1]
    assert all("temperature" not in c for c in calls[2:])  # remembered: no more failed attempts
