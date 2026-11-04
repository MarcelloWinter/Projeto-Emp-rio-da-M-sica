"""Terminal chat with Mel, the Empório da Música assistant.

Interactive:  python app_cli.py
Scripted:     python app_cli.py --script demo.txt --save conversations/01_x.md --title "..."
              (one customer message per line; blank lines and lines starting with # are ignored)

Commands inside the chat: /config (change provider/key/model), /reset (new conversation),
/save [path] (export transcript), /tools (toggle tool trace), /quit
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
from emporio_agent.config import now  # noqa: E402
from emporio_agent.llm_setup import interactive_setup, is_configured, load_settings  # noqa: E402

console = Console()
GREETING = "Oi! Eu sou a Mel, assistente virtual da Empório da Música 🎸 Como posso te ajudar hoje?"


def _short(result: str, limit: int = 160) -> str:
    return result if len(result) <= limit else result[:limit] + "…"


def render_transcript(turns: list[dict], title: str | None) -> str:
    lines = [f"# {title or 'Conversation with Mel (Empório da Música)'}", "",
             f"_Exported {now():%Y-%m-%d %H:%M} (store time)._", ""]
    lines.append(f"**Mel:** {GREETING}\n")
    for t in turns:
        lines.append(f"**Customer:** {t['user']}\n")
        if t["tools"]:
            lines.append("<details><summary>Tools called</summary>\n")
            for tc in t["tools"]:
                lines.append(f"- `{tc.name}({json.dumps(tc.arguments, ensure_ascii=False)})`")
            lines.append("\n</details>\n")
        lines.append(f"**Mel:** {t['reply']}\n")
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

    def ask(text: str) -> None:
        reply = agent.chat(text)
        turns.append({"user": text, "reply": reply.text, "tools": reply.tool_calls})
        if show_tools:
            for tc in reply.tool_calls:
                console.print(f"  [dim]🔧 {tc.name}({json.dumps(tc.arguments, ensure_ascii=False)})[/dim]")
        console.print("[bold magenta]Mel:[/bold magenta]", Markdown(reply.text))
        if reply.error:
            console.print(f"[yellow]⚠ {reply.error}[/yellow]")

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

    console.print("[dim]/config · /reset · /save <path> · /tools · /quit[/dim]")
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
            agent.reset()
            turns.clear()
            console.print("[dim]Nova conversa iniciada.[/dim]")
        elif text == "/config":
            settings = interactive_setup(settings)
            agent = Agent(settings=settings)
            turns.clear()
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
