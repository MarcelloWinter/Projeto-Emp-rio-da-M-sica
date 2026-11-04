"""Terminal chat with Mel, the Empório da Música assistant.

Interactive:  python app_cli.py
Scripted:     python app_cli.py --script demo.txt --save conversations/01_x.md --title "..."
              (one customer message per line; blank lines and lines starting with # are ignored)

Commands inside the chat: /history (list saved conversations), /resume N, /delete N, /config (change
provider/key/model), /reset (new conversation), /save [path] (export transcript), /tools (toggle tool trace), /quit

Conversations are saved automatically to logs/conversations.db in interactive mode (disable with SAVE_HISTORY=0).
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from rich.console import Console  # noqa: E402
from rich.markdown import Markdown  # noqa: E402

from emporio_agent.agent import Agent  # noqa: E402
from emporio_agent.config import display_timezone, format_when  # noqa: E402
from emporio_agent.history import ConversationStore, history_enabled  # noqa: E402
from emporio_agent.llm_setup import interactive_setup, is_configured, load_settings  # noqa: E402

console = Console()
GREETING = "Oi! Eu sou a Mel, assistente virtual da Empório da Música 🎸 Como posso te ajudar hoje?"


def _short(result: str, limit: int = 160) -> str:
    return result if len(result) <= limit else result[:limit] + "…"


def render_transcript(turns: list[dict], title: str | None) -> str:
    lines = [f"# {title or 'Conversation with Mel (Empório da Música)'}", "",
             f"_Exported {datetime.now(display_timezone()):%Y-%m-%d %H:%M}._", ""]
    lines.append(f"**Mel:** {GREETING}\n")
    for t in turns:
        stamp = lambda iso: f" _({format_when(iso)})_" if iso else ""  # noqa: E731
        lines.append(f"**Customer**{stamp(t.get('asked_at'))}**:** {t['user']}\n")
        if t["tools"]:
            lines.append("<details><summary>Tools called</summary>\n")
            for tc in t["tools"]:
                lines.append(f"- `{tc.name}({json.dumps(tc.arguments, ensure_ascii=False)})`")
            lines.append("\n</details>\n")
        lines.append(f"**Mel**{stamp(t.get('answered_at'))}**:** {t['reply']}\n")
    return "\n".join(lines)


def save(turns: list[dict], path: str | None, title: str | None) -> Path:
    target = Path(path) if path else Path("conversations") / f"chat_{datetime.now():%Y%m%d_%H%M%S}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_transcript(turns, title), encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--script", help="text file with one customer message per line")
    parser.add_argument("--save", help="where to export the transcript (.md)")
    parser.add_argument("--title", help="title for the exported transcript")
    args = parser.parse_args()

    settings = load_settings()
    if not is_configured(settings):
        if args.script or not sys.stdin.isatty():
            console.print("[red]No LLM configured. Run `python app_cli.py` interactively, or set LLM_API_KEY "
                          "(and LLM_PROVIDER / LLM_MODEL) in .env.[/red]")
            sys.exit(1)
        console.print("[yellow]No valid API key found. Let's configure the model provider.[/yellow]")
        settings = interactive_setup(settings)
    agent = Agent(settings=settings)
    turns: list[dict] = []
    show_tools = True
    store = ConversationStore() if history_enabled() and not args.script else None  # demos/scripts are not logged
    current = {"id": None, "listing": []}

    def start_new_conversation() -> None:
        agent.reset()
        turns.clear()
        current["id"] = None

    def ask(text: str) -> None:
        reply = agent.chat(text)
        turns.append({"user": text, "reply": reply.text, "tools": reply.tool_calls,
                      "asked_at": reply.asked_at, "answered_at": reply.answered_at})
        if show_tools:
            for tc in reply.tool_calls:
                console.print(f"  [dim]🔧 {tc.name}({json.dumps(tc.arguments, ensure_ascii=False)})[/dim]")
        console.print("[bold magenta]Mel:[/bold magenta]", Markdown(reply.text))
        console.print(f"[dim]🕒 enviada {format_when(reply.asked_at)} · respondida {format_when(reply.answered_at)}[/dim]")
        if reply.error:
            console.print(f"[yellow]⚠ {reply.error}[/yellow]")
        if store and reply.messages:  # only successful turns are saved
            current["id"] = current["id"] or store.create(settings.provider, settings.model)
            store.add_turn(current["id"], text, reply)

    def pick(arg: str):
        """Resolve '/resume 2' style arguments against the last /history listing."""
        if not arg.strip().isdigit() or not 1 <= int(arg) <= len(current["listing"]):
            console.print("[yellow]Use /history first, then /resume N or /delete N with a number from the list.[/yellow]")
            return None
        return current["listing"][int(arg) - 1]

    console.print(f"[dim]Provider: {settings.label} · model: {settings.model}[/dim]")
    console.print(f"[bold magenta]Mel:[/bold magenta] {GREETING}")

    if args.script:
        for raw in Path(args.script).read_text(encoding="utf-8").splitlines():
            msg = raw.strip()
            if msg and not msg.startswith("#"):
                console.print(f"[bold cyan]Você:[/bold cyan] {msg}")
                ask(msg)
        if args.save:
            console.print(f"[green]Saved → {save(turns, args.save, args.title)}[/green]")
        return

    console.print("[dim]/history · /resume N · /config · /reset · /save <path> · /tools · /quit[/dim]")
    while True:
        try:
            text = console.input("[bold cyan]Você:[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text == "/quit":
            break
        if text == "/reset":
            start_new_conversation()
            console.print("[dim]Nova conversa iniciada.[/dim]")
        elif text.split(" ")[0] in {"/history", "/resume", "/delete"}:
            cmd, _, arg = text.partition(" ")
            if not store:
                console.print("[yellow]History is disabled (SAVE_HISTORY=0).[/yellow]")
            elif cmd == "/history":
                current["listing"] = store.recent()
                if not current["listing"]:
                    console.print("[dim]No saved conversations yet.[/dim]")
                for i, c in enumerate(current["listing"], 1):
                    console.print(f"  [bold]{i}.[/bold] {c.title}  [dim]({c.when} · {c.turns} msgs)[/dim]")
            elif (chosen := pick(arg)) and cmd == "/resume":
                saved = store.load(chosen.id)
                agent.load_history([m for t in saved for m in t.messages])
                turns[:] = [{"user": t.user, "reply": t.reply, "tools": t.tools,
                             "asked_at": t.asked_at, "answered_at": t.answered_at} for t in saved]
                current["id"] = chosen.id
                console.print(f"[dim]Resumed: {chosen.title}[/dim]")
                for t in saved:
                    console.print(f"[bold cyan]Você:[/bold cyan] {t.user}  [dim]{format_when(t.asked_at)}[/dim]")
                    console.print("[bold magenta]Mel:[/bold magenta]", Markdown(t.reply))
                    console.print(f"[dim]🕒 {format_when(t.answered_at)}[/dim]")
            elif chosen:  # /delete
                store.delete(chosen.id)
                if current["id"] == chosen.id:
                    current["id"] = None
                current["listing"] = store.recent()
                console.print(f"[dim]Deleted: {chosen.title}. Run /history to refresh the numbers.[/dim]")
        elif text == "/config":
            settings = interactive_setup(settings)
            agent = Agent(settings=settings)
            turns.clear()
            current["id"] = None
            console.print(f"[dim]Now using {settings.label} · {settings.model}. New conversation started.[/dim]")
        elif text.startswith("/save"):
            console.print(f"[green]Saved → {save(turns, text[5:].strip() or None, args.title)}[/green]")
        elif text == "/tools":
            show_tools = not show_tools
            console.print(f"[dim]tool trace: {'on' if show_tools else 'off'}[/dim]")
        else:
            ask(text)
    if args.save:
        save(turns, args.save, args.title)


if __name__ == "__main__":
    main()
