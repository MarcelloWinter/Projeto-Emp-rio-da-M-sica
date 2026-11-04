"""Smoke tests for the Streamlit UI: the sidebar controls must exist and the app must run without errors."""
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app_streamlit.py")


@pytest.fixture()
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("HISTORY_DB", str(tmp_path / "conversations.db"))
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-test-not-used")
    monkeypatch.setenv("LLM_MODEL", "gpt-4.1-mini")
    st.cache_resource.clear()  # the app caches its ConversationStore
    return AppTest.from_file(APP, default_timeout=60).run()


def test_app_runs_without_errors(app):
    assert not app.exception


def test_sidebar_has_provider_and_model_settings(app):
    labels = [s.label for s in app.sidebar.selectbox]
    assert labels == ["Provedor", "Modelo"]
    assert "gpt-4.1-mini" in app.sidebar.selectbox[1].options
    assert any("Outro" in o for o in app.sidebar.selectbox[1].options)  # free-text escape hatch
    assert {"API key"} <= {t.label for t in app.sidebar.text_input}
    assert any("Modelo e provedor" in e.label for e in app.sidebar.expander)
    assert {"Aplicar"} <= {b.label for b in app.sidebar.button} or any("Buscar modelos" in b.label for b in app.sidebar.button)


def test_sidebar_has_history_controls(app):
    assert any("Conversas anteriores" in e.label for e in app.sidebar.expander)
    assert any(t.key == "save_history" for t in app.sidebar.toggle)
    assert any("Nova conversa" in b.label for b in app.sidebar.button)


def test_suggestion_buttons_are_shown_on_a_fresh_chat(app):
    assert len([b for b in app.button if str(b.key).startswith("sug_")]) == 6


def test_unconfigured_app_shows_setup_help_and_still_offers_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("HISTORY_DB", str(tmp_path / "conversations.db"))
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "your-key-here")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    st.cache_resource.clear()
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any("Falta só um passo" in m.value for m in at.markdown)
    assert [s.label for s in at.sidebar.selectbox] == ["Provedor", "Modelo"]
