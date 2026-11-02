"""Simple chat UI for Mel.  Run with:  streamlit run app_streamlit.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import streamlit as st  # noqa: E402

from emporio_agent.agent import Agent  # noqa: E402

GREETING = "Oi! Eu sou a Mel, assistente virtual da Empório da Música 🎸 Como posso te ajudar hoje?"

st.set_page_config(page_title="Empório da Música — Mel", page_icon="🎸")
st.title("🎸 Empório da Música")
st.caption("Sua música começa aqui · atendimento com a Mel, assistente virtual")


@st.cache_resource
def get_agent_store() -> dict:
    """One Agent (conversation history) per browser session, keyed by session id."""
    return {}


if "session_id" not in st.session_state:
    st.session_state.session_id = id(st.session_state)
    st.session_state.messages = [{"role": "assistant", "content": GREETING, "tools": []}]

store = get_agent_store()
agent = store.setdefault(st.session_state.session_id, Agent())

with st.sidebar:
    st.subheader("Demonstração")
    show_tools = st.toggle("Mostrar ferramentas usadas", value=True)
    if st.button("Nova conversa"):
        agent.reset()
        st.session_state.messages = [{"role": "assistant", "content": GREETING, "tools": []}]
        st.rerun()

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if show_tools and m["tools"]:
            with st.expander("🔧 Ferramentas usadas"):
                for tc in m["tools"]:
                    st.code(f"{tc.name}({json.dumps(tc.arguments, ensure_ascii=False)})", language="python")

if prompt := st.chat_input("Escreva sua mensagem…"):
    st.session_state.messages.append({"role": "user", "content": prompt, "tools": []})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Mel está digitando…"):
            reply = agent.chat(prompt)
        st.markdown(reply.text)
        if show_tools and reply.tool_calls:
            with st.expander("🔧 Ferramentas usadas"):
                for tc in reply.tool_calls:
                    st.code(f"{tc.name}({json.dumps(tc.arguments, ensure_ascii=False)})", language="python")
    st.session_state.messages.append({"role": "assistant", "content": reply.text, "tools": reply.tool_calls})
