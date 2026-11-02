"""Tool-calling agent loop on the OpenAI Chat Completions API (no agent framework)."""
import json
import logging
from dataclasses import dataclass, field

from openai import OpenAI, OpenAIError

from .config import MAX_HISTORY_MESSAGES, MAX_TOOL_ITERATIONS, OPENAI_MODEL
from .policies.retriever import PolicyRetriever
from .prompts import build_system_prompt
from .tools import TOOL_SCHEMAS, ToolRegistry

log = logging.getLogger(__name__)

FALLBACK_REPLY = ("Desculpe, tive um probleminha técnico aqui agora. 😕 Pode tentar de novo em instantes? "
                  "Se preferir, fale com a equipe pelo (67) 3341-4444.")


@dataclass
class ToolTrace:
    name: str
    arguments: dict
    result: str


@dataclass
class Reply:
    text: str
    tool_calls: list[ToolTrace] = field(default_factory=list)


class Agent:
    def __init__(self, client: OpenAI | None = None, model: str | None = None,
                 tools: ToolRegistry | None = None):
        self.client = client or OpenAI()
        self.model = model or OPENAI_MODEL
        self.tools = tools or ToolRegistry(retriever=PolicyRetriever(self.client))
        self.history: list[dict] = []

    def reset(self) -> None:
        self.history.clear()

    def _trim_history(self) -> None:
        """Drop the oldest whole turns, always restarting at a user message so tool-call pairs stay intact."""
        while len(self.history) > MAX_HISTORY_MESSAGES:
            next_user = next((i for i, m in enumerate(self.history[1:], 1) if m["role"] == "user"), None)
            if next_user is None:
                break
            del self.history[:next_user]

    def chat(self, user_message: str) -> Reply:
        checkpoint = len(self.history)
        self.history.append({"role": "user", "content": user_message})
        traces: list[ToolTrace] = []
        try:
            for _ in range(MAX_TOOL_ITERATIONS):
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": build_system_prompt()}, *self.history],
                    tools=TOOL_SCHEMAS,
                    temperature=0.3,
                )
                msg = response.choices[0].message
                if not msg.tool_calls:
                    text = (msg.content or "").strip() or FALLBACK_REPLY
                    self.history.append({"role": "assistant", "content": text})
                    self._trim_history()
                    return Reply(text, traces)

                self.history.append({
                    "role": "assistant", "content": msg.content,
                    "tool_calls": [{"id": c.id, "type": "function",
                                    "function": {"name": c.function.name, "arguments": c.function.arguments}}
                                   for c in msg.tool_calls],
                })
                for call in msg.tool_calls:
                    try:
                        args = json.loads(call.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = self.tools.call(call.function.name, args)
                    traces.append(ToolTrace(call.function.name, args, result))
                    self.history.append({"role": "tool", "tool_call_id": call.id, "content": result})
            log.warning("Tool iteration limit reached")
        except OpenAIError:
            log.exception("OpenAI request failed")
        del self.history[checkpoint:]  # roll back the incomplete turn so the next message starts clean
        return Reply(FALLBACK_REPLY, traces)
