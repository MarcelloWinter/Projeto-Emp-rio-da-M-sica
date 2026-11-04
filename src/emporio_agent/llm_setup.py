"""LLM provider configuration: presets, env loading, client creation and first-run setup.

Any provider that exposes an OpenAI-compatible Chat Completions API (with tool calling) works
by changing ``base_url`` + key + model. Only OpenAI has been tested end to end; the other
presets are convenience defaults, and the model names may change over time (edit freely).
"""
import getpass
import os
from dataclasses import dataclass, replace
from pathlib import Path

from openai import (APIConnectionError, AuthenticationError, NotFoundError, OpenAI,
                    PermissionDeniedError, RateLimitError)

from .config import ENV_PATH


@dataclass(frozen=True)
class Preset:
    label: str
    base_url: str | None
    model: str
    embedding_model: str | None  # None -> policy search falls back to keyword matching
    needs_key: bool = True
    key_url: str = ""


PRESETS: dict[str, Preset] = {
    "openai": Preset("OpenAI", None, "gpt-4.1-mini", "text-embedding-3-small",
                     key_url="https://platform.openai.com/api-keys"),
    "gemini": Preset("Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai/",
                     "gemini-2.5-flash", None, key_url="https://aistudio.google.com/apikey"),
    "groq": Preset("Groq", "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", None,
                   key_url="https://console.groq.com/keys"),
    "openrouter": Preset("OpenRouter", "https://openrouter.ai/api/v1", "openai/gpt-4.1-mini", None,
                         key_url="https://openrouter.ai/keys"),
    "deepseek": Preset("DeepSeek", "https://api.deepseek.com", "deepseek-chat", None,
                       key_url="https://platform.deepseek.com/api_keys"),
    "mistral": Preset("Mistral", "https://api.mistral.ai/v1", "mistral-small-latest", None,
                      key_url="https://console.mistral.ai/api-keys"),
    "ollama": Preset("Ollama (local, no key)", "http://localhost:11434/v1", "llama3.1", None, needs_key=False),
    "custom": Preset("Other (any OpenAI-compatible endpoint)", None, "", None),
}


@dataclass(frozen=True)
class Settings:
    provider: str
    api_key: str
    base_url: str | None
    model: str
    embedding_model: str | None

    @property
    def label(self) -> str:
        return PRESETS.get(self.provider, PRESETS["custom"]).label


def _is_placeholder(key: str) -> bool:
    k = key.strip().lower()
    return not k or k.startswith("your-") or "your-key" in k or k in {"changeme", "xxx"}


def load_settings() -> Settings:
    """Read settings from the environment. Legacy OPENAI_* variables still work for the openai provider."""
    provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    preset = PRESETS.get(provider, PRESETS["custom"])
    legacy = provider == "openai"
    key = os.getenv("LLM_API_KEY") or (os.getenv("OPENAI_API_KEY") if legacy else "") or ""
    model = os.getenv("LLM_MODEL") or (os.getenv("OPENAI_MODEL") if legacy else "") or preset.model
    embedding = os.getenv("LLM_EMBEDDING_MODEL") or (os.getenv("OPENAI_EMBEDDING_MODEL") if legacy else "") \
        or preset.embedding_model
    return Settings(provider, key.strip(), os.getenv("LLM_BASE_URL") or preset.base_url, model, embedding or None)


def is_configured(s: Settings) -> bool:
    preset = PRESETS.get(s.provider, PRESETS["custom"])
    key_ok = not preset.needs_key or not _is_placeholder(s.api_key)
    return key_ok and bool(s.model) and (s.provider != "custom" or bool(s.base_url))


def make_client(s: Settings) -> OpenAI:
    return OpenAI(api_key=s.api_key or "not-needed", base_url=s.base_url)


def describe_error(exc: Exception) -> str:
    """Operator-facing hint for the most common setup failures."""
    if isinstance(exc, AuthenticationError):
        return "API key rejected by the provider. Set a valid key (CLI: /config, UI: sidebar, or edit .env)."
    if isinstance(exc, NotFoundError):
        return "Model or endpoint not found. Check the model name and base URL (CLI: /config)."
    if isinstance(exc, PermissionDeniedError):
        return "This key has no access to that model/endpoint."
    if isinstance(exc, RateLimitError):
        return "Rate limit or quota exceeded for this key/provider."
    if isinstance(exc, APIConnectionError):
        return "Could not reach the provider. Check your internet connection and the base URL."
    return f"Provider error: {exc}"


def save_env(s: Settings, path: Path = ENV_PATH) -> None:
    """Upsert the LLM_* variables in .env, keeping any other lines, and apply them to this process."""
    values = {"LLM_PROVIDER": s.provider, "LLM_API_KEY": s.api_key, "LLM_MODEL": s.model,
              "LLM_BASE_URL": s.base_url or "", "LLM_EMBEDDING_MODEL": s.embedding_model or ""}
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen = set()
    for i, line in enumerate(lines):
        name = line.split("=", 1)[0].strip()
        if name in values and not line.lstrip().startswith("#"):
            lines[i] = f"{name}={values[name]}"
            seen.add(name)
    lines += [f"{k}={v}" for k, v in values.items() if k not in seen]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    apply_to_environ(s)


def apply_to_environ(s: Settings) -> None:
    for k, v in {"LLM_PROVIDER": s.provider, "LLM_API_KEY": s.api_key, "LLM_MODEL": s.model,
                 "LLM_BASE_URL": s.base_url or "", "LLM_EMBEDDING_MODEL": s.embedding_model or ""}.items():
        os.environ[k] = v


def interactive_setup(current: Settings | None = None, input_fn=input, secret_fn=getpass.getpass,
                      out=print, env_path: Path = ENV_PATH) -> Settings:
    """Ask for provider, key and model; offer to save them to .env. The key is typed hidden."""
    current = current or load_settings()
    names = list(PRESETS)
    out("\nChoose the LLM provider:")
    for i, name in enumerate(names, 1):
        out(f"  {i}. {PRESETS[name].label}")
    default_idx = names.index(current.provider) + 1 if current.provider in names else 1
    raw = input_fn(f"Provider [{default_idx}]: ").strip()
    provider = names[int(raw) - 1] if raw.isdigit() and 1 <= int(raw) <= len(names) else names[default_idx - 1]
    preset = PRESETS[provider]

    base_url = preset.base_url
    if provider == "custom":
        base_url = input_fn("Base URL (e.g. https://host/v1): ").strip() or None
    key = ""
    if preset.needs_key:
        if preset.key_url:
            out(f"Get a key at: {preset.key_url}")
        key = secret_fn("API key (input hidden): ").strip()
    default_model = current.model if provider == current.provider and current.model else preset.model
    model = input_fn(f"Model [{default_model}]: ").strip() or default_model

    settings = Settings(provider, key, base_url, model, preset.embedding_model)
    if provider == current.provider and current.embedding_model:
        settings = replace(settings, embedding_model=current.embedding_model)
    if not preset.embedding_model:
        out("Note: this provider has no embeddings preset; policy search will use keyword matching "
            "(set LLM_EMBEDDING_MODEL in .env if it offers an embeddings endpoint).")
    if input_fn("Save to .env for next time? [Y/n]: ").strip().lower() in {"", "y", "yes", "s", "sim"}:
        save_env(settings, env_path)
        out(f"Saved to {env_path.name}.")
    else:
        apply_to_environ(settings)
    return settings
