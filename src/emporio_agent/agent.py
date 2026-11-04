"""Tool-calling agent loop on the OpenAI Chat Completions API (no agent framework)."""
import json
import logging
from dataclasses import dataclass, field

from openai import BadRequestError, OpenAI, OpenAIError

from .config import MAX_HISTORY_MESSAGES, MAX_TOOL_ITERATIONS
from .llm_setup import Settings, describe_error, load_settings, make_client
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
    error: str | None = None  # operator-facing hint when the provider call failed
    messages: list[dict] = field(default_factory=list)  # context messages added in this turn (for persistence)


class Agent:
    def __init__(self, client: OpenAI | None = None, model: str | None = None,
                 tools: ToolRegistry | None = None, settings: Settings | None = None):
        self.settings = settings or load_settings()
        self.client = client or make_client(self.settings)
        self.model = model or self.settings.model
        self.tools = tools or ToolRegistry(retriever=PolicyRetriever(
            self.client, embedding_model=self.settings.embedding_model))
        self.history: list[dict] = []
        self._temperature: float | None = 0.3  # dropped automatically for models that only accept the default

    def reset(self) -> None:
        self.history.clear()

    def load_history(self, messages: list[dict]) -> None:
        """Restore the context of a saved conversation so the model continues where it stopped."""
        self.history = list(messages)
        self._trim_history()

    def _trim_history(self) -> None:
        """Drop the oldest whole turns, always restarting at a user message so tool-call pairs stay intact."""
        while len(self.history) > MAX_HISTORY_MESSAGES:
            next_user = next((i for i, m in enumerate(self.history[1:], 1) if m["role"] == "user"), None)
            if next_user is None:
                break
            del self.history[:next_user]

    def _complete(self, messages: list[dict]):
        """One chat call. Some models (e.g. GPT-5 / reasoning families) reject a custom temperature: retry without it."""
        kwargs = {"model": self.model, "messages": messages, "tools": TOOL_SCHEMAS}
        if self._temperature is not None:
            kwargs["temperature"] = self._temperature
        try:
            return self.client.chat.completions.create(**kwargs)
        except BadRequestError as exc:
            if self._temperature is None or "temperature" not in str(exc).lower():
                raise
            log.info("Model %s does not accept a custom temperature; retrying with the default", self.model)
            self._temperature = None
            kwargs.pop("temperature")
            return self.client.chat.completions.create(**kwargs)

    def chat(self, user_message: str) -> Reply:
        checkpoint = len(self.history)
        self.history.append({"role": "user", "content": user_message})
        traces: list[ToolTrace] = []
        try:
            for _ in range(MAX_TOOL_ITERATIONS):
                response = self._complete([{"role": "system", "content": build_system_prompt()}, *self.history])
                msg = response.choices[0].message
                if not msg.tool_calls:
                    text = (msg.content or "").strip() or FALLBACK_REPLY
                    self.history.append({"role": "assistant", "content": text})
                    delta = list(self.history[checkpoint:])  # taken before trimming drops old turns
                    self._trim_history()
                    return Reply(text, traces, messages=delta)

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
        except OpenAIError as exc:
            log.warning("LLM request failed: %s", exc)
            del self.history[checkpoint:]
            return Reply(FALLBACK_REPLY, traces, error=describe_error(exc))
        del self.history[checkpoint:]  # roll back the incomplete turn so the next message starts clean
        return Reply(FALLBACK_REPLY, traces)
