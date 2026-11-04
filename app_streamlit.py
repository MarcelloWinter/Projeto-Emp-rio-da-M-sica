"""Chat UI for Mel.  Run with:  streamlit run app_streamlit.py

The LLM provider, API key and model can be set from the sidebar. Keys typed here live only in the
browser session's memory (never written to disk or logs).
"""
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import streamlit as st  # noqa: E402

from emporio_agent.agent import Agent  # noqa: E402
from emporio_agent.history import ConversationStore, history_enabled  # noqa: E402
from emporio_agent.llm_setup import (PRESETS, Settings, is_configured, list_models, load_settings,  # noqa: E402
                                     model_choices)
from emporio_agent.store_hours import store_status  # noqa: E402

GREETING = ("Oi! Eu sou a **Mel**, assistente virtual da Empório da Música 🎸 Posso ajudar com **preços e estoque**, "
            "**promoções**, **pedidos** e **políticas da loja**. Como posso ajudar?")

SUGGESTIONS = [
    ("🎸", "Violões até R$ 1000", "Quais opções de violões vocês têm disponíveis custando até R$1000?"),
    ("💰", "Preço do Takamine GD20", "Quanto custa o Takamine GD20?"),
    ("🏷️", "Promoções ativas", "Quais promoções estão ativas agora?"),
    ("📦", "Onde está meu pedido?", "Quero saber onde está o meu pedido"),
    ("🔄", "Trocas e devoluções", "Me arrependi da minha compra, posso devolver meu pedido?"),
    ("🕘", "Horário e endereço", "Qual o horário de funcionamento e o endereço da loja?"),
]

NAVY, AMBER = "#16324F", "#E8912D"

CSS = f"""
<style>
/* ---------- layout ---------- */
.block-container {{ max-width: 860px; padding-top: 3rem; padding-bottom: 1.5rem; }}
header[data-testid="stHeader"] {{ background: transparent; }}
footer, #MainMenu {{ visibility: hidden; }}

/* ---------- hero ---------- */
.hero {{
  background: linear-gradient(135deg, {NAVY} 0%, #24507C 100%);
  border-radius: 20px; padding: 1.05rem 1.4rem 1.1rem; color: #fff; margin-bottom: .9rem;
  box-shadow: 0 10px 30px rgba(22, 50, 79, .22); position: relative; overflow: hidden;
}}
.hero::after {{
  content: "♪ ♫"; position: absolute; right: 1.4rem; top: .2rem; font-size: 4.5rem;
  opacity: .08; letter-spacing: .4rem;
}}
.hero-row {{ display: flex; align-items: center; gap: 1rem; }}
.hero-logo {{
  width: 50px; height: 50px; border-radius: 14px; background: {AMBER}; display: grid; place-items: center;
  font-size: 1.6rem; box-shadow: 0 4px 12px rgba(0,0,0,.25); flex: none;
}}
.hero h1 {{ margin: 0; padding: 0; font-size: 1.4rem; line-height: 1.2; color: #fff; font-weight: 750; }}
.hero p {{ margin: .15rem 0 0; opacity: .85; font-size: .95rem; }}
.pill {{
  display: inline-flex; align-items: center; gap: .45rem; margin-top: .7rem; padding: .25rem .75rem;
  border-radius: 999px; background: rgba(255,255,255,.14); font-size: .82rem; backdrop-filter: blur(4px);
}}
.dot {{ width: 9px; height: 9px; border-radius: 50%; display: inline-block; margin-right: .1rem; }}
.dot.on {{ background: #4ADE80; box-shadow: 0 0 0 4px rgba(74,222,128,.25); }}
.dot.off {{ background: #FCA5A5; }}

/* ---------- suggestions ---------- */
.section-label {{ font-size: .8rem; font-weight: 650; letter-spacing: .06em; text-transform: uppercase;
  color: #7A6A55; margin: .4rem 0 .5rem; }}
div[data-testid="stButton"] > button {{
  width: 100%; text-align: left; justify-content: flex-start; border-radius: 14px; padding: .7rem .9rem;
  background: #fff; border: 1px solid #E9DFCF; color: {NAVY}; font-weight: 600;
  transition: all .15s ease; box-shadow: 0 1px 2px rgba(0,0,0,.04);
}}
div[data-testid="stButton"] > button:hover {{
  border-color: {AMBER}; color: {NAVY}; transform: translateY(-2px); box-shadow: 0 8px 18px rgba(232,145,45,.18);
}}
div[data-testid="stButton"] > button:active {{ background: #FFF4E3; }}

/* ---------- chat bubbles ---------- */
div[data-testid="stChatMessage"] {{
  background: #fff; border: 1px solid #EEE5D6; border-radius: 18px; padding: .85rem 1.05rem;
  box-shadow: 0 2px 8px rgba(31,42,55,.05); margin-bottom: .35rem;
}}
div[data-testid="stChatMessage"]:has(.role-user) {{
  background: {NAVY}; border-color: {NAVY}; color: #fff; margin-left: auto; width: fit-content; max-width: 88%;
}}
div[data-testid="stChatMessage"]:has(.role-user) * {{ color: #fff !important; }}
div[data-testid="stElementContainer"]:has(.role-user), div[data-testid="stElementContainer"]:has(.role-assistant) {{ display: none; }}
div[data-testid="stChatMessage"]:has(.role-assistant) {{
  border-left: 4px solid {AMBER}; max-width: 94%;
}}

/* ---------- tool pills ---------- */
.tools {{ display: flex; flex-wrap: wrap; gap: .35rem; margin-top: .55rem; }}
.tool {{ font-size: .74rem; padding: .16rem .6rem; border-radius: 999px; background: #FFF4E3; color: #9A5B0B;
  border: 1px solid #F6DDB5; font-weight: 600; }}

/* ---------- chat input ---------- */
div[data-testid="stChatInput"] {{ border-radius: 16px; border: 1px solid #E3D6BF; box-shadow: 0 6px 22px rgba(0,0,0,.07); background: #fff; }}
div[data-testid="stChatInput"] > div, div[data-testid="stChatInput"] textarea {{ background: #fff !important; }}
div[data-testid="stChatInput"]:focus-within {{ border-color: {AMBER}; box-shadow: 0 0 0 3px rgba(232,145,45,.2); }}

/* ---------- sidebar ---------- */
section[data-testid="stSidebar"] div[data-testid="stButton"] > button {{ padding: .45rem .55rem; font-size: .85rem; }}
section[data-testid="stSidebar"] {{ background: #F5EEE2; border-right: 1px solid #E9DFCF; }}
.store-card {{ background: #fff; border-radius: 16px; padding: 1rem 1.05rem; border: 1px solid #EEE5D6;
  font-size: .88rem; line-height: 1.55; box-shadow: 0 2px 8px rgba(31,42,55,.05); }}
.store-card h4 {{ margin: 0 0 .5rem; color: {NAVY}; font-size: 1rem; }}
.store-card .row {{ display: flex; gap: .55rem; margin: .25rem 0; }}
.setup-card {{ background: #fff; border-radius: 18px; padding: 1.3rem 1.5rem; border: 1px solid #EEE5D6;
  border-left: 5px solid {AMBER}; box-shadow: 0 4px 14px rgba(31,42,55,.06); }}
</style>
"""

st.set_page_config(page_title="Empório da Música · Mel", page_icon="🎸", layout="centered")
st.markdown(CSS, unsafe_allow_html=True)


@st.cache_resource
def get_store() -> ConversationStore:
    return ConversationStore()


def new_chat() -> None:
    st.session_state.messages = [{"role": "assistant", "content": GREETING, "tools": []}]
    st.session_state.conv_id = None  # created in the database lazily, on the first saved turn


def tool_pills(tool_calls) -> None:
    pills = "".join(f'<span class="tool">🔧 {html.escape(tc.name)}</span>' for tc in tool_calls)
    st.markdown(f'<div class="tools">{pills}</div>', unsafe_allow_html=True)
    with st.expander("Ver detalhes das consultas"):
        for tc in tool_calls:
            st.code(f"{tc.name}({json.dumps(tc.arguments, ensure_ascii=False)})", language="python")


def write_message(role: str, text: str) -> None:
    """Render chat text safely: no raw HTML, and '$' escaped so prices like R$ 2.199,00 are not read as LaTeX."""
    st.markdown(f'<span class="role-{role}"></span>', unsafe_allow_html=True)  # hidden marker used by the CSS
    st.markdown(html.escape(text, quote=False).replace("$", "\\$"), unsafe_allow_html=True)


def render_message(m: dict, show_tools: bool) -> None:
    avatar = "🎸" if m["role"] == "assistant" else "🙂"
    with st.chat_message(m["role"], avatar=avatar):
        write_message(m["role"], m["content"])
        if show_tools and m["tools"]:
            tool_pills(m["tools"])


if "settings" not in st.session_state:  # first run of this browser session
    st.session_state.settings = load_settings()
    st.session_state.save_history = history_enabled()
    new_chat()

settings: Settings = st.session_state.settings
status = store_status()

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown("### 🎸 Empório da Música")
    state = (f'<span class="dot on"></span> Aberta agora' if status["is_open"]
             else f'<span class="dot off"></span> Fechada · abre {status["next_opening"]}')
    st.markdown(
        f"""<div class="store-card">
        <h4>Sua música começa aqui</h4>
        <div class="row"><span>📍</span><span>Rua 14 de Maio, 3200 — Centro<br>Campo Grande/MS</span></div>
        <div class="row"><span>📞</span><span>(67) 3341-4444</span></div>
        <div class="row"><span>📧</span><span>contato@emporiodamusica.com.br</span></div>
        <div class="row"><span>🕘</span><span>Seg–Sex 09h–18h<br>Sáb 09h–13h · Dom fechado</span></div>
        <div class="row" style="margin-top:.55rem"><b>{state}</b></div></div>""",
        unsafe_allow_html=True)

    st.write("")
    if st.button("✨ Nova conversa", use_container_width=True):
        st.session_state.pop("agent", None)
        new_chat()
        st.rerun()
    show_tools = st.toggle("Mostrar consultas feitas pela Mel", value=True)
    st.toggle("Salvar histórico das conversas", key="save_history",
              help="Grava as conversas em logs/conversations.db (arquivo local, fora do Git). "
                   "Podem conter dados pessoais de clientes.")

    saved_list = get_store().recent(limit=12)
    with st.expander(f"💬 Conversas anteriores ({len(saved_list)})", expanded=False):
        if not saved_list:
            st.caption("Nenhuma conversa salva ainda.")
        for c in saved_list:
            open_col, del_col = st.columns([4, 1])
            title = c.title if len(c.title) <= 26 else c.title[:25].rstrip() + "…"
            if open_col.button(title, key=f"open_{c.id}", help=c.title, use_container_width=True):
                st.session_state.resume_id = c.id
                st.rerun()
            open_col.caption(f"{c.when} · {c.turns} {'mensagem' if c.turns == 1 else 'mensagens'}")
            if del_col.button("×", key=f"del_{c.id}", help="Apagar esta conversa", use_container_width=True):
                get_store().delete(c.id)
                if st.session_state.conv_id == c.id:
                    st.session_state.conv_id = None
                st.rerun()

# --------------------------------------------------------------------- hero
badge = (f'<span class="dot on"></span> Loja aberta agora' if status["is_open"]
         else f'<span class="dot off"></span> Loja fechada · abre {status["next_opening"]}')
st.markdown(
    f"""<div class="hero"><div class="hero-row">
      <div class="hero-logo">🎸</div>
      <div><h1>Fale com a Mel</h1><p>Assistente virtual da Empório da Música</p></div></div>
      <span class="pill">{badge}</span></div>""",
    unsafe_allow_html=True)

if not is_configured(settings):
    st.markdown(
        """<div class="setup-card"><b>Falta só um passo 🔑</b><br>Abra <b>⚙️ Modelo e provedor</b> na barra lateral
        (no celular, toque na seta no canto superior esquerdo), escolha o provedor, cole sua chave de API e clique em
        <b>Aplicar</b>.</div>""", unsafe_allow_html=True)
    st.stop()

# The Agent (and its conversation history) lives in this browser session only — never shared.
if "agent" not in st.session_state:
    st.session_state.agent = Agent(settings=settings)
agent = st.session_state.agent

if resume_id := st.session_state.pop("resume_id", None):  # reopen a saved conversation and keep its context
    saved = get_store().load(resume_id)
    agent.load_history([m for t in saved for m in t.messages])
    st.session_state.messages = [{"role": "assistant", "content": GREETING, "tools": []}] + [
        m for t in saved for m in ({"role": "user", "content": t.user, "tools": []},
                                   {"role": "assistant", "content": t.reply, "tools": t.tools})]
    st.session_state.conv_id = resume_id

# ------------------------------------------------------------------ the chat
typed = st.chat_input("Escreva sua mensagem para a Mel…")
prompt = st.session_state.pop("pending_prompt", None) or typed

if len(st.session_state.messages) == 1 and not prompt:
    st.markdown('<div class="section-label">Comece por aqui</div>', unsafe_allow_html=True)
    for row in range(0, len(SUGGESTIONS), 3):
        cols = st.columns(3)
        for col, (icon, label, text) in zip(cols, SUGGESTIONS[row:row + 3]):
            if col.button(f"{icon}  {label}", key=f"sug_{label}", use_container_width=True):
                st.session_state.pending_prompt = text
                st.rerun()
    st.write("")

for m in st.session_state.messages:
    render_message(m, show_tools)

if prompt:
    user_msg = {"role": "user", "content": prompt, "tools": []}
    st.session_state.messages.append(user_msg)
    render_message(user_msg, show_tools)
    with st.chat_message("assistant", avatar="🎸"):
        with st.spinner("Mel está digitando…"):
            reply = agent.chat(prompt)
        write_message("assistant", reply.text)
        if reply.error:
            st.warning(reply.error)
        if show_tools and reply.tool_calls:
            tool_pills(reply.tool_calls)
    st.session_state.messages.append({"role": "assistant", "content": reply.text, "tools": reply.tool_calls})
    if st.session_state.save_history and reply.messages:  # only successful turns are saved
        first_turn = st.session_state.conv_id is None
        if first_turn:
            st.session_state.conv_id = get_store().create(settings.provider, settings.model)
        get_store().add_turn(st.session_state.conv_id, prompt, reply)
        if first_turn:
            st.rerun()  # refresh the sidebar list so the new conversation shows up
