"""Simple chat UI for Mel.  Run with:  streamlit run app_streamlit.py

The LLM provider, API key and model can be set from the sidebar. Keys typed here live only in the
browser session's memory (never written to disk or logs).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import streamlit as st  # noqa: E402

from emporio_agent.agent import Agent  # noqa: E402
from emporio_agent.llm_setup import PRESETS, Settings, is_configured, load_settings  # noqa: E402

GREETING = "Oi! Eu sou a Mel, assistente virtual da Empório da Música 🎸 Como posso te ajudar hoje?"

st.set_page_config(page_title="Empório da Música — Mel", page_icon="🎸")
st.title("🎸 Empório da Música")
st.caption("Sua música começa aqui · atendimento com a Mel, assistente virtual")


@st.cache_resource
def get_agent_store() -> dict:
    """One Agent (conversation history) per browser session, keyed by session id."""
    return {}


def new_chat() -> None:
    st.session_state.messages = [{"role": "assistant", "content": GREETING, "tools": []}]


if "session_id" not in st.session_state:
    st.session_state.session_id = id(st.session_state)
    st.session_state.settings = load_settings()
    new_chat()

store = get_agent_store()
settings: Settings = st.session_state.settings

with st.sidebar:
    st.subheader("Modelo e provedor")
    names = list(PRESETS)
    provider = st.selectbox("Provedor", names, index=names.index(settings.provider) if settings.provider in names else 0,
                            format_func=lambda n: PRESETS[n].label)
    preset = PRESETS[provider]
    same = provider == settings.provider
    base_url = (st.text_input("Base URL", value=(settings.base_url or "") if same else "")
                if provider == "custom" else preset.base_url)
    api_key = st.text_input("API key", type="password", value=settings.api_key if same else "",
                            disabled=not preset.needs_key,
                            help="Fica apenas na memória desta sessão; não é gravada em disco.")
    model = st.text_input("Modelo", value=settings.model if same and settings.model else preset.model)
    if preset.key_url:
        st.caption(f"Obtenha uma chave em {preset.key_url}")
    if not preset.embedding_model:
        st.caption("Sem embeddings neste provedor: a busca de políticas usa palavras-chave.")
    if st.button("Aplicar"):
        st.session_state.settings = settings = Settings(
            provider, (api_key or "").strip(), base_url or None, model.strip(),
            settings.embedding_model if same else preset.embedding_model)
        store.pop(st.session_state.session_id, None)
        new_chat()
        st.rerun()

    st.divider()
    show_tools = st.toggle("Mostrar ferramentas usadas", value=True)
    if st.button("Nova conversa"):
        store.pop(st.session_state.session_id, None)
        new_chat()
        st.rerun()

if not is_configured(settings):
    st.warning("Configure o provedor, a chave de API e o modelo na barra lateral e clique em **Aplicar**.")
    st.stop()

agent = store.setdefault(st.session_state.session_id, Agent(settings=settings))
st.caption(f"Provedor: {settings.label} · modelo: {settings.model}")


def show_tools_used(tool_calls) -> None:
    with st.expander("🔧 Ferramentas usadas"):
        for tc in tool_calls:
            st.code(f"{tc.name}({json.dumps(tc.arguments, ensure_ascii=False)})", language="python")


for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if show_tools and m["tools"]:
            show_tools_used(m["tools"])

if prompt := st.chat_input("Escreva sua mensagem…"):
    st.session_state.messages.append({"role": "user", "content": prompt, "tools": []})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Mel está digitando…"):
            reply = agent.chat(prompt)
        st.markdown(reply.text)
        if reply.error:
            st.warning(reply.error)
        if show_tools and reply.tool_calls:
            show_tools_used(reply.tool_calls)
    st.session_state.messages.append({"role": "assistant", "content": reply.text, "tools": reply.tool_calls})
